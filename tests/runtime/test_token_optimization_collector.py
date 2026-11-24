import asyncio
import io
import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import pytest

from free_claude_code.runtime import token_optimization as runtime_module
from free_claude_code.runtime.token_optimization import (
    ExternalTokenOptimizationCollector,
    OutputLimitExceeded,
    ProcessResult,
    ProcessRunner,
    run_bounded_process,
)
from tests.wire_payload import array_payload, object_payload

FIXTURES = Path(__file__).parents[1] / "application" / "fixtures" / "token_optimization"


class ProcessCall(TypedDict):
    argv: list[str]
    env: dict[str, str]
    timeout: float
    max_output_bytes: int


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def successful_runner(
    calls: list[ProcessCall],
    *,
    rtk: str = "rtk_populated.json",
    headroom: str = "headroom_zero.json",
) -> ProcessRunner:
    def run(
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        max_output_bytes: int,
    ) -> ProcessResult:
        calls.append(
            {
                "argv": list(argv),
                "env": env,
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
            }
        )
        if "--version" in argv:
            version = "rtk 0.44.2" if argv[0].endswith("rtk") else "headroom 0.40.0"
            return ProcessResult(0, version.encode(), b"")
        if "--daily" in argv:
            output = fixture_bytes("rtk_daily_populated.json")
        else:
            output = fixture_bytes(rtk if "gain" in argv else headroom)
        return ProcessResult(0, output, b"")

    return run


def resolver(name: str) -> str:
    return f"/tools/{name}"


@pytest.mark.asyncio
async def test_collector_uses_fixed_direct_argv_and_sanitized_success_contract() -> (
    None
):
    calls: list[ProcessCall] = []
    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver,
        process_runner=successful_runner(calls),
        clock=lambda: datetime(2026, 11, 17, 12, tzinfo=UTC),
    )

    payload = await collector.collect()

    optimizations = object_payload(payload["optimizations"])
    rtk = object_payload(optimizations["rtk"])
    headroom = object_payload(optimizations["headroom"])
    assert rtk["version"] == "0.44.2"
    assert headroom["state"] == "available"
    assert len(array_payload(rtk["daily"])) == 2
    summary_calls = [
        call
        for call in calls
        if "--version" not in call["argv"] and "--daily" not in call["argv"]
    ]
    assert [call["argv"] for call in summary_calls] == [
        ["/tools/rtk", "gain", "--format", "json"],
        ["/tools/headroom", "savings", "--json"],
    ]
    daily_call = next(call for call in calls if "--daily" in call["argv"])
    assert daily_call["argv"] == [
        "/tools/rtk",
        "gain",
        "--daily",
        "--format",
        "json",
    ]
    rtk_call = next(call for call in calls if "gain" in call["argv"])
    assert rtk_call["env"]["RTK_TELEMETRY_DISABLED"] == "1"
    headroom_call = next(call for call in calls if "savings" in call["argv"])
    assert "RTK_TELEMETRY_DISABLED" not in headroom_call["env"]
    assert all("ANTHROPIC_AUTH_TOKEN" not in call["env"] for call in calls)
    assert all("AWS_SECRET_ACCESS_KEY" not in call["env"] for call in calls)
    assert all(call["timeout"] == 3.0 for call in calls)
    assert all("history" not in call["argv"] for call in calls)
    assert "/tools/" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_daily_schema_drift_does_not_invalidate_summary() -> None:
    def run(argv: Sequence[str], **kwargs: object) -> ProcessResult:
        if "--daily" in argv:
            return ProcessResult(0, b"not json", b"")
        if "gain" in argv:
            return ProcessResult(0, fixture_bytes("rtk_populated.json"), b"")
        if "savings" in argv:
            return ProcessResult(0, fixture_bytes("headroom_zero.json"), b"")
        return ProcessResult(0, b"0.44.2", b"")

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    payload = await collector.collect()
    rtk = object_payload(object_payload(payload["optimizations"])["rtk"])
    assert rtk["state"] == "available"
    assert "daily" not in rtk


@pytest.mark.asyncio
async def test_resolver_failure_does_not_hide_the_other_tool() -> None:
    calls: list[ProcessCall] = []

    def resolve(name: str) -> str:
        if name == "rtk":
            raise OSError("private resolver path")
        return resolver(name)

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolve,
        process_runner=successful_runner(calls),
    )
    payload = await collector.collect()
    optimizations = object_payload(payload["optimizations"])
    assert object_payload(optimizations["rtk"])["state"] == "error"
    assert object_payload(optimizations["headroom"])["state"] == "available"
    assert "private resolver path" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_missing_tools_have_independent_not_installed_states() -> None:
    collector = ExternalTokenOptimizationCollector(
        executable_resolver=lambda name: None
    )
    payload = await collector.collect()
    optimizations = object_payload(payload["optimizations"])
    rtk = object_payload(optimizations["rtk"])
    headroom = object_payload(optimizations["headroom"])
    assert rtk["state"] == "not_installed"
    assert headroom["state"] == "not_installed"
    assert rtk["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "state"),
    [
        (subprocess.TimeoutExpired("rtk", 1), "timeout"),
        (OutputLimitExceeded("too large"), "invalid_output"),
        (OSError("private path must not leak"), "error"),
    ],
)
async def test_tool_failures_are_stable_and_do_not_hide_the_other_tool(
    failure: BaseException, state: str
) -> None:
    def run(argv: Sequence[str], **kwargs: object) -> ProcessResult:
        if "gain" in argv:
            raise failure
        if "--version" in argv:
            return ProcessResult(0, b"0.40.0", b"")
        return ProcessResult(0, fixture_bytes("headroom_populated.json"), b"")

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    payload = await collector.collect()
    optimizations = object_payload(payload["optimizations"])
    assert object_payload(optimizations["rtk"])["state"] == state
    assert object_payload(optimizations["headroom"])["state"] == "available"
    assert "private path" not in json.dumps(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "expected_state"),
    [(b"not json", "invalid_output"), (b'{"summary": {}}', "available")],
)
async def test_invalid_json_and_missing_fields_have_distinct_semantics(
    output: bytes, expected_state: str
) -> None:
    def run(argv: Sequence[str], **kwargs: object) -> ProcessResult:
        if "gain" in argv:
            return ProcessResult(0, output, b"")
        if "savings" in argv:
            return ProcessResult(0, fixture_bytes("headroom_zero.json"), b"")
        return ProcessResult(0, b"0.44.2", b"")

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    payload = await collector.collect()
    rtk = object_payload(object_payload(payload["optimizations"])["rtk"])
    assert rtk["state"] == expected_state


@pytest.mark.asyncio
async def test_nonzero_exit_is_an_error_and_version_failure_does_not_hide_summary() -> (
    None
):
    def run(argv: Sequence[str], **kwargs: object) -> ProcessResult:
        if "gain" in argv:
            return ProcessResult(2, b"private stdout", b"private stderr")
        if "savings" in argv:
            return ProcessResult(0, fixture_bytes("headroom_zero.json"), b"")
        return ProcessResult(1, b"", b"")

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    payload = await collector.collect()
    optimizations = object_payload(payload["optimizations"])
    assert object_payload(optimizations["rtk"])["state"] == "error"
    assert object_payload(optimizations["headroom"])["version"] is None
    assert "private stdout" not in json.dumps(payload)
    assert "private stderr" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_cache_covers_success_and_ttl_and_returns_defensive_copies() -> None:
    calls: list[ProcessCall] = []
    monotonic = [0.0]
    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver,
        process_runner=successful_runner(calls),
        monotonic=lambda: monotonic[0],
        cache_ttl_seconds=5,
    )
    first = await collector.collect()
    first_rtk = object_payload(object_payload(first["optimizations"])["rtk"])
    first_rtk["state"] = "mutated"
    second = await collector.collect()
    second_rtk = object_payload(object_payload(second["optimizations"])["rtk"])
    assert second_rtk["state"] == "available"
    initial_count = len(calls)
    await collector.collect()
    assert len(calls) == initial_count
    monotonic[0] = 5.0
    await collector.collect()
    assert len(calls) > initial_count


@pytest.mark.asyncio
async def test_force_refresh_coalesces_with_an_existing_flight() -> None:
    calls: list[ProcessCall] = []
    started = threading.Event()
    release = threading.Event()
    base = successful_runner(calls)

    def run(
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        max_output_bytes: int,
    ) -> ProcessResult:
        if "gain" in argv:
            started.set()
            assert release.wait(2)
        return base(
            argv,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    first = asyncio.create_task(collector.collect())
    await asyncio.to_thread(started.wait, 1)
    second = asyncio.create_task(collector.collect(force_refresh=True))
    await asyncio.sleep(0.02)
    release.set()
    await asyncio.gather(first, second)
    assert (
        sum("gain" in call["argv"] and "--daily" not in call["argv"] for call in calls)
        == 1
    )


@pytest.mark.asyncio
async def test_cancelling_one_caller_does_not_cancel_shared_collection() -> None:
    calls: list[ProcessCall] = []
    started = threading.Event()
    release = threading.Event()
    base = successful_runner(calls)

    def run(
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        max_output_bytes: int,
    ) -> ProcessResult:
        if "gain" in argv:
            started.set()
            assert release.wait(2)
        return base(
            argv,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    cancelled = asyncio.create_task(collector.collect())
    await asyncio.to_thread(started.wait, 1)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release.set()
    result = await collector.collect()
    rtk = object_payload(object_payload(result["optimizations"])["rtk"])
    assert rtk["state"] == "available"


@pytest.mark.asyncio
async def test_close_drains_shared_work_and_rejects_new_collection() -> None:
    calls: list[ProcessCall] = []
    started = threading.Event()
    release = threading.Event()
    base = successful_runner(calls)

    def run(
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        max_output_bytes: int,
    ) -> ProcessResult:
        if "gain" in argv:
            started.set()
            assert release.wait(2)
        return base(
            argv,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    pending = asyncio.create_task(collector.collect())
    await asyncio.to_thread(started.wait, 1)
    closing = asyncio.create_task(collector.close())
    release.set()
    await asyncio.gather(pending, closing)
    with pytest.raises(RuntimeError, match="closed"):
        await collector.collect(force_refresh=True)


@pytest.mark.asyncio
async def test_cache_also_covers_tool_failure() -> None:
    calls: list[Sequence[str]] = []

    def run(argv: Sequence[str], **kwargs: object) -> ProcessResult:
        calls.append(argv)
        raise OSError("unavailable")

    collector = ExternalTokenOptimizationCollector(
        executable_resolver=resolver, process_runner=run
    )
    first = await collector.collect()
    second = await collector.collect()
    assert first == second
    assert len(calls) == 2


class FakeProcess:
    def __init__(
        self, stdout: bytes = b"{}", stderr: bytes = b"", timeout: bool = False
    ) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.timeout = timeout
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired(
                "fixed", timeout if timeout is not None else 0.0
            )
        return 0

    def kill(self) -> None:
        self.killed = True


def test_default_runner_passes_shell_false_and_bounded_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(stdout=b'{"ok": true}')
    captured: dict[str, object] = {}

    def popen(argv: Sequence[str], **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured.update(kwargs)
        return process

    monkeypatch.setattr(
        runtime_module.subprocess,
        "Popen",
        cast("Callable[..., subprocess.Popen[bytes]]", popen),
    )
    result = run_bounded_process(
        ["rtk", "gain"], env={"SAFE": "1"}, timeout=1, max_output_bytes=100
    )
    assert result.stdout == b'{"ok": true}'
    assert captured["argv"] == ["rtk", "gain"]
    assert captured["shell"] is False
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["stdout"] is subprocess.PIPE
    assert captured["stderr"] is subprocess.PIPE


def test_default_runner_discards_oversized_output_and_kills_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def popen_oversized(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(stdout=b"x" * 100)

    monkeypatch.setattr(
        runtime_module.subprocess,
        "Popen",
        cast("Callable[..., subprocess.Popen[bytes]]", popen_oversized),
    )
    with pytest.raises(OutputLimitExceeded):
        run_bounded_process(["fixed"], env={}, timeout=1, max_output_bytes=10)

    process = FakeProcess(timeout=True)

    def popen_timeout(*args: object, **kwargs: object) -> FakeProcess:
        return process

    monkeypatch.setattr(
        runtime_module.subprocess,
        "Popen",
        cast("Callable[..., subprocess.Popen[bytes]]", popen_timeout),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded_process(["fixed"], env={}, timeout=0.01, max_output_bytes=10)
    assert process.killed
