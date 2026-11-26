import asyncio
import io
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from free_claude_code.config import loader
from free_claude_code.config.admin.persistence import prepare_admin_update
from free_claude_code.config.env_files import MODELGLOT_CONFIG_SCHEMA_ENV
from free_claude_code.config.env_migrations import CONFIG_SCHEMA_VERSION
from free_claude_code.config.loader import ManagedConfigStore
from free_claude_code.config.paths import config_lock_path
from free_claude_code.core.interprocess_lock import InterprocessFileLock
from free_claude_code.runtime.configuration import ConfigurationService


def test_reads_are_fresh_read_only_snapshots() -> None:
    store = ManagedConfigStore()
    store.initialize()
    for port in (8123, 8124):
        store.path.write_text(
            f"{MODELGLOT_CONFIG_SCHEMA_ENV}={CONFIG_SCHEMA_VERSION}\nMODELGLOT_PORT={port}\n"
        )
        with patch(
            "free_claude_code.config.loader.consolidate_managed_config",
            side_effect=AssertionError("read migrated"),
        ):
            snapshot = store.read()
        assert snapshot.settings.port == port
        assert snapshot.managed["MODELGLOT_PORT"] == str(port)


def test_read_does_not_recreate_missing_storage() -> None:
    store = ManagedConfigStore()
    with pytest.raises(ValueError, match="initializ"):
        store.read()
    assert not store.path.exists()


def test_preparation_uses_captured_disk_and_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ManagedConfigStore()
    store.initialize()
    snapshot = store.read({"MODELGLOT_PORT": "8123"})
    monkeypatch.setenv("MODELGLOT_PORT", "9999")
    store.path.unlink()
    prepared = prepare_admin_update(
        {"MODELGLOT_PORT": "8124"},
        snapshot,
        snapshot.settings,
        revision_key=b"test-revision-key",
    )
    assert prepared.settings is not None
    assert prepared.settings.port == 8123
    assert "MODELGLOT_PORT" not in prepared.target_values


@pytest.mark.asyncio
async def test_read_waits_for_storage_lock_without_blocking_event_loop() -> None:
    store = ManagedConfigStore()
    store.initialize()
    service = ConfigurationService(store)
    with InterprocessFileLock(config_lock_path()):
        reader = asyncio.create_task(service.admin_values())
        done, _ = await asyncio.wait({reader}, timeout=0.1)
    try:
        assert not done
    finally:
        await asyncio.wait_for(reader, 5)


@pytest.mark.parametrize("schema", ["", "999"])
def test_reads_and_commits_fail_closed_on_uninitialized_or_newer_schema(
    schema: str,
) -> None:
    store = ManagedConfigStore()
    store.initialize()
    text = f"MODELGLOT_CONFIG_SCHEMA={schema}\nANTHROPIC_AUTH_TOKEN=preserve\n"
    store.path.write_text(text)
    with pytest.raises(ValueError, match="schema"):
        store.read()
    with pytest.raises(ValueError, match="schema"):
        store.commit({"MODELGLOT_CONFIG_SCHEMA": "1"})
    assert store.path.read_text() == text


def test_cooperative_commits_are_serialized_and_leave_complete_files() -> None:
    store = ManagedConfigStore()
    store.initialize()
    original = loader.atomic_write_managed_config
    writing = threading.Lock()
    seen = []

    def checked_write(
        values: Mapping[str, str],
        *,
        path: Path | None = None,
        mask_secrets: bool = False,
    ):
        probe = InterprocessFileLock(config_lock_path())
        try:
            assert not probe.acquire(), "commit does not hold the shared write lock"
        finally:
            probe.release()
        assert writing.acquire(blocking=False), "cooperative writes overlap"
        try:
            seen.append(values["MODELGLOT_PORT"])
            return original(values, path=path, mask_secrets=mask_secrets)
        finally:
            writing.release()

    def write(port: int):
        ManagedConfigStore().commit(
            {"MODELGLOT_CONFIG_SCHEMA": "1", "MODELGLOT_PORT": str(port)}
        )

    with (
        patch(
            "free_claude_code.config.loader.atomic_write_managed_config", checked_write
        ),
        ThreadPoolExecutor(max_workers=8) as executor,
    ):
        list(executor.map(write, range(8120, 8128)))
    assert len(seen) == 8
    assert store.read().managed["MODELGLOT_PORT"] == seen[-1]
    assert not list(store.path.parent.glob("*.tmp"))


def test_atomic_commit_waits_for_an_open_snapshot_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ManagedConfigStore()
    store.initialize()
    store.commit({"MODELGLOT_CONFIG_SCHEMA": "1", "MODELGLOT_PORT": "8123"})
    opened, release = threading.Event(), threading.Event()
    original_open = io.open
    reader_thread = None

    def hold_reader(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ):
        handle = original_open(path, mode, buffering, encoding, errors, newline)
        if path == store.path and threading.current_thread() is reader_thread:
            opened.set()
            if not release.wait(5):
                handle.close()
                raise TimeoutError("snapshot reader was not released")
        return handle

    def read_snapshot():
        nonlocal reader_thread
        reader_thread = threading.current_thread()
        return store.read({})

    monkeypatch.setattr(io, "open", hold_reader)
    with ThreadPoolExecutor(max_workers=2) as executor:
        reader = executor.submit(read_snapshot)
        writer = None
        try:
            assert opened.wait(5)
            writer = executor.submit(
                store.commit, {"MODELGLOT_CONFIG_SCHEMA": "1", "MODELGLOT_PORT": "8124"}
            )
            with pytest.raises(TimeoutError):
                writer.result(timeout=0.1)
        finally:
            release.set()
        assert reader.result(timeout=5).settings.port == 8123
        assert writer.result(timeout=5) is None
    assert store.read({}).settings.port == 8124
    assert not list(store.path.parent.glob("*.tmp"))


@pytest.mark.asyncio
async def test_admin_reads_recreate_missing_managed_storage():
    store = ManagedConfigStore()
    store.initialize()
    store.path.unlink()
    service = ConfigurationService(store)

    values = await service.admin_values()
    config = await service.admin_config()

    assert values
    assert config["fields"]
    assert store.path.is_file()
    assert store.read().managed[MODELGLOT_CONFIG_SCHEMA_ENV] == CONFIG_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_admin_reads_fail_closed_on_unsupported_schema():
    store = ManagedConfigStore()
    store.initialize()
    store.path.write_text(f"{MODELGLOT_CONFIG_SCHEMA_ENV}=999\n")
    service = ConfigurationService(store)

    with pytest.raises(ValueError, match="schema"):
        await service.admin_values()

    assert store.path.read_text() == f"{MODELGLOT_CONFIG_SCHEMA_ENV}=999\n"


@pytest.mark.asyncio
async def test_commit_recreates_missing_managed_storage():
    store = ManagedConfigStore()
    store.initialize()
    service = ConfigurationService(store)
    prepared = await service.prepare({"MODELGLOT_PORT": "8123"}, store.read().settings)
    store.path.unlink()

    result = await service.commit(prepared)

    assert result["applied"] is True
    assert store.path.is_file()
    assert store.read().managed["MODELGLOT_PORT"] == "8123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["initialize", "admin_config", "admin_values", "prepare", "commit"]
)
async def test_storage_work_does_not_block_event_loop(operation: str) -> None:
    store = ManagedConfigStore()
    store.initialize()
    service = ConfigurationService(store)
    active = store.read().settings
    prepared = await service.prepare({"MODELGLOT_PORT": "8123"}, active)
    entered = threading.Event()
    release = threading.Event()
    heartbeat = asyncio.Event()
    method = {"admin_config": "read", "admin_values": "read", "prepare": "read"}.get(
        operation, operation
    )
    original: Callable[..., object] = getattr(store, method)

    def blocked(*args: object, **kwargs: object):
        entered.set()
        assert release.wait(5), "event loop failed to release storage"
        assert heartbeat.is_set()
        return original(*args, **kwargs)

    async def observe():
        while not entered.is_set():
            await asyncio.sleep(0)
        heartbeat.set()
        release.set()

    observer = asyncio.create_task(observe())
    try:
        with patch.object(store, method, side_effect=blocked):
            if operation == "prepare":
                await service.prepare({"MODELGLOT_PORT": "8124"}, active)
            elif operation == "commit":
                await service.commit(prepared)
            else:
                await getattr(service, operation)()
        await asyncio.wait_for(observer, 5)
    finally:
        release.set()
        observer.cancel()
