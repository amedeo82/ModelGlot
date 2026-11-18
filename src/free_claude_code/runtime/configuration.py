"""Worker boundary for managed configuration; runtime state stays on the loop."""

from collections.abc import Mapping
from secrets import token_bytes

from anyio import CapacityLimiter, to_thread

from free_claude_code.config.admin.custom_providers import CustomProviderMutation
from free_claude_code.config.admin.persistence import (
    PreparedAdminUpdate,
    prepare_admin_update,
)
from free_claude_code.config.admin.state import ConfigInputValue, ValueState
from free_claude_code.config.admin.values import load_config_response, load_value_state
from free_claude_code.config.errors import ManagedConfigMissingError
from free_claude_code.config.loader import ManagedConfigSnapshot, ManagedConfigStore
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject


class ConfigurationService:
    def __init__(self, store: ManagedConfigStore) -> None:
        self._store = store
        self._revision_key = token_bytes(32)
        # Storage is serialized; its waiters must not exhaust FastAPI's worker pool.
        self._worker_limiter = CapacityLimiter(1)

    async def initialize(self) -> None:
        await to_thread.run_sync(self._store.initialize, limiter=self._worker_limiter)

    def _read_snapshot(self) -> ManagedConfigSnapshot:
        """Read managed configuration, recreating it when the file disappeared."""

        try:
            return self._store.read()
        except ManagedConfigMissingError:
            # The managed file can vanish while the server runs (cleanup, reset,
            # or a manual delete). Recreate it instead of failing every request.
            self._store.initialize()
            return self._store.read()

    async def admin_config(self) -> JsonObject:
        snapshot = await to_thread.run_sync(
            self._read_snapshot, limiter=self._worker_limiter
        )
        return load_config_response(snapshot, revision_key=self._revision_key)

    async def admin_values(self) -> ValueState:
        snapshot = await to_thread.run_sync(
            self._read_snapshot, limiter=self._worker_limiter
        )
        return load_value_state(snapshot)

    async def prepare(
        self,
        updates: Mapping[str, ConfigInputValue],
        active_settings: Settings,
        custom_provider: CustomProviderMutation | None = None,
    ) -> PreparedAdminUpdate:
        snapshot = await to_thread.run_sync(
            self._read_snapshot, limiter=self._worker_limiter
        )
        return prepare_admin_update(
            updates,
            snapshot,
            active_settings,
            custom_provider,
            revision_key=self._revision_key,
        )

    async def commit(self, prepared: PreparedAdminUpdate) -> JsonObject:
        if not prepared.valid:
            raise ValueError("Cannot commit an invalid Admin update")
        await to_thread.run_sync(
            self._commit_values,
            prepared.target_values,
            prepared.expected,
            limiter=self._worker_limiter,
        )
        return prepared.applied_response()

    def _commit_values(
        self,
        values: Mapping[str, str],
        expected: ManagedConfigSnapshot | None,
    ) -> None:
        try:
            self._store.commit(values, expected)
        except ManagedConfigMissingError:
            # The file vanished after the edit was prepared; restore the managed
            # configuration and apply the prepared values to the fresh file.
            self._store.initialize()
            self._store.commit(values)
