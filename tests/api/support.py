"""Explicit test composition for the API adapter."""

import asyncio
from collections.abc import Mapping, MutableMapping
from typing import override

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modelglot.api.app import create_app
from modelglot.api.dependencies import app_services
from modelglot.api.ports import ApiServices
from modelglot.application.code_sessions import CodeApplicationPort
from modelglot.application.connected_accounts import ConnectedAccountPort
from modelglot.application.model_metadata import ProviderModelRefreshResult
from modelglot.config.loader import ManagedConfigStore
from modelglot.config.provider_catalog import PROVIDER_CATALOG
from modelglot.config.settings import Settings
from modelglot.core.json_types import JsonValue
from modelglot.providers.base import BaseProvider
from modelglot.providers.runtime import ProviderRuntime
from modelglot.runtime.application import ApplicationRuntime, RestartCallback
from modelglot.runtime.configuration import ConfigurationService
from modelglot.runtime.provider_manager import (
    ProviderRuntimeManager,
    _ProviderGeneration,
)
from modelglot.runtime.token_optimization import (
    ExternalTokenOptimizationCollector,
)
from tests.config.credential_support import credential_edit
from tests.web_tools_support import StubWebToolsClient
from tests.wire_payload import array_payload, object_payload, response_object


def post_config(client: TestClient, path: str, *, json: Mapping[str, JsonValue]):
    values = object_payload(json.get("values", {}))
    credential_keys = {
        d.credential_env for d in PROVIDER_CATALOG.values() if d.credential_env
    }
    if credential_keys.intersection(values):
        config = response_object(client.get("/admin/api/config"))
        fields = {
            object_payload(field)["key"]: field
            for field in array_payload(config["fields"])
        }
        values = {
            key: credential_edit(
                object_payload(object_payload(fields[key])["value"]), value
            )
            if key in credential_keys
            else value
            for key, value in values.items()
        }
    return client.post(path, json={**json, "values": values})


class ApiTestRuntime(ProviderRuntimeManager):
    """API-only tests supply metadata explicitly; startup/discovery has separate tests."""

    @override
    def _catalog_task(
        self,
        generation: _ProviderGeneration,
        provider_id: str,
        *,
        refresh: bool = False,
    ):
        if refresh:
            return super()._catalog_task(generation, provider_id, refresh=True)
        task = generation.catalog_tasks.get(provider_id)
        if task is None:

            async def supplied_catalog():
                generation.initialized.add(provider_id)
                return ProviderModelRefreshResult()

            task = asyncio.create_task(supplied_catalog())
            generation.catalog_tasks[provider_id] = task
        return task


def create_test_app(
    settings: Settings | None = None,
    *,
    providers: MutableMapping[str, BaseProvider] | None = None,
    restart_callback: RestartCallback | None = None,
    connected_accounts: Mapping[str, ConnectedAccountPort] | None = None,
    code: CodeApplicationPort | None = None,
    token_optimization_collector: ExternalTokenOptimizationCollector | None = None,
) -> FastAPI:
    """Build an API app with explicit in-memory runtime services."""
    store = ManagedConfigStore()
    store.initialize()  # API-only tests do not run the production ASGI lifespan.
    settings = settings or store.read().settings
    connected_accounts = dict(connected_accounts or {})

    def connected_provider_ids() -> tuple[str, ...]:
        return tuple(
            provider_id
            for provider_id, account in connected_accounts.items()
            if account.is_connected()
        )

    if providers is None:
        manager = ApiTestRuntime(
            settings,
            connected_provider_ids=connected_provider_ids,
        )
    else:
        manager = ApiTestRuntime(
            settings,
            runtime_factory=lambda snapshot, admission_registry, history_cache=None: (
                ProviderRuntime(
                    snapshot,
                    admission_registry,
                    None,
                    {
                        (provider_id, 1): provider
                        for provider_id, provider in providers.items()
                    },
                )
            ),
            connected_provider_ids=connected_provider_ids,
        )
    runtime = ApplicationRuntime(
        manager,
        configuration=ConfigurationService(store),
        transcriber=None,
        restart_callback=restart_callback,
        connected_accounts=connected_accounts,
        token_optimization_collector=token_optimization_collector,
    )
    return create_app(
        ApiServices(
            requests=manager,
            admin=runtime,
            integrations=runtime.integrations,
            tasks=runtime,
            code=code,
            web_tools=StubWebToolsClient(),
            usage=runtime,
        )
    )


def runtime_for_app(app: FastAPI) -> ApplicationRuntime:
    """Return the runtime supplied by :func:`create_test_app`."""
    runtime = app_services(app).admin
    if not isinstance(runtime, ApplicationRuntime):
        raise TypeError("Test app does not use ApplicationRuntime")
    return runtime


def provider_manager_for_app(app: FastAPI) -> ProviderRuntimeManager:
    """Return the provider manager supplied by :func:`create_test_app`."""
    manager = app_services(app).requests
    if not isinstance(manager, ProviderRuntimeManager):
        raise TypeError("Test app does not use ProviderRuntimeManager")
    return manager
