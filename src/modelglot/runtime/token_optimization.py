"""Bounded runtime collection of RTK and Headroom optimization summaries."""

import asyncio
import contextlib
import copy
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import BinaryIO, Protocol

from loguru import logger

from modelglot.application.token_optimization import (
    HeadroomOptimizationReport,
    OptimizationReportError,
    OptimizationState,
    RTKDailyReport,
    RTKOptimizationReport,
    parse_headroom_report,
    parse_rtk_report,
    parse_tool_version,
    token_optimization_payload,
    unavailable_headroom,
    unavailable_rtk,
)
from modelglot.core.json_types import JsonObject


class OutputLimitExceeded(ValueError):
    """A child process exceeded the sanitized output budget."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class ProcessRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        max_output_bytes: int,
    ) -> ProcessResult: ...


def _read_bounded(
    stream: BinaryIO, chunks: list[bytes], overflow: list[bool], limit: int
) -> None:
    """Drain one pipe while retaining at most ``limit`` bytes in memory."""

    retained = 0
    try:
        while chunk := stream.read(min(8192, limit + 1)):
            if not chunk:
                break
            remaining = limit - retained
            if remaining > 0:
                chunks.append(chunk[:remaining])
                retained += min(len(chunk), remaining)
            if len(chunk) > remaining:
                overflow[0] = True
    finally:
        stream.close()


def _finish_readers(
    process: subprocess.Popen[bytes], readers: list[threading.Thread]
) -> bool:
    """Finish pipe readers without waiting on inherited descendant handles."""

    for reader in readers:
        reader.join(timeout=0.1)
    if any(reader.is_alive() for reader in readers):
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with contextlib.suppress(OSError, ValueError):
                    stream.close()
        for reader in readers:
            reader.join(timeout=0.1)
    return not any(reader.is_alive() for reader in readers)


def run_bounded_process(
    argv: Sequence[str],
    *,
    env: dict[str, str],
    timeout: float,
    max_output_bytes: int,
) -> ProcessResult:
    """Run fixed argv without a shell and bound time and captured output.

    Both pipes are drained after the limit so a verbose child cannot deadlock;
    excess bytes are discarded rather than accumulated or returned to callers.
    """

    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=env,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_overflow = [False]
    stderr_overflow = [False]
    readers = [
        threading.Thread(
            target=_read_bounded,
            args=(process.stdout, stdout_chunks, stdout_overflow, max_output_bytes),
            daemon=True,
        ),
        threading.Thread(
            target=_read_bounded,
            args=(process.stderr, stderr_chunks, stderr_overflow, max_output_bytes),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        _finish_readers(process, readers)
        raise
    readers_finished = _finish_readers(process, readers)
    if not readers_finished:
        raise OutputLimitExceeded("external tool output did not terminate cleanly")
    if stdout_overflow[0] or stderr_overflow[0]:
        raise OutputLimitExceeded("external tool output exceeded the configured limit")
    return ProcessResult(
        returncode=returncode,
        stdout=b"".join(stdout_chunks),
        stderr=b"".join(stderr_chunks),
    )


class ExternalTokenOptimizationCollector:
    """Collect independent tool reports with TTL caching and single-flight."""

    def __init__(
        self,
        *,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        process_runner: ProcessRunner = run_bounded_process,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timeout_seconds: float = 3.0,
        cache_ttl_seconds: float = 5.0,
        max_output_bytes: int = 1024 * 1024,
    ) -> None:
        if timeout_seconds <= 0 or cache_ttl_seconds < 0 or max_output_bytes <= 0:
            raise ValueError("collector bounds must be positive")
        self._resolve = executable_resolver
        self._runner = process_runner
        self._monotonic = monotonic
        self._clock = clock
        self._timeout = timeout_seconds
        self._cache_ttl = cache_ttl_seconds
        self._max_output_bytes = max_output_bytes
        self._cache: JsonObject | None = None
        self._cache_expires_at = float("-inf")
        self._flight: asyncio.Task[JsonObject] | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def collect(self, *, force_refresh: bool = False) -> JsonObject:
        """Return a defensive copy; cancellation never cancels shared collection."""

        async with self._lock:
            now = self._monotonic()
            if (
                not force_refresh
                and self._cache is not None
                and now < self._cache_expires_at
            ):
                return copy.deepcopy(self._cache)
            if self._closed:
                raise RuntimeError("token optimization collector is closed")
            if self._flight is None or self._flight.done():
                self._flight = asyncio.create_task(self._collect_uncached())
            flight = self._flight
        try:
            result = await asyncio.shield(flight)
        finally:
            if flight.done():
                async with self._lock:
                    if self._flight is flight:
                        self._flight = None
        return copy.deepcopy(result)

    async def close(self) -> None:
        """Reject new work and drain the bounded in-flight collection."""

        async with self._lock:
            self._closed = True
            flight = self._flight
        if flight is not None:
            await asyncio.shield(flight)

    async def _collect_uncached(self) -> JsonObject:
        rtk, headroom = await asyncio.gather(
            self._collect_rtk(), self._collect_headroom()
        )
        payload = token_optimization_payload(
            rtk=rtk, headroom=headroom, generated_at=self._clock()
        )
        self._cache = payload
        self._cache_expires_at = self._monotonic() + self._cache_ttl
        return payload

    def _run(self, argv: Sequence[str], *, rtk: bool = False) -> ProcessResult:
        # Copy only process-launch/locale values. Provider credentials and ModelGlot
        # configuration are neither needed by these CLIs nor allowed to cross
        # this process boundary.
        safe_names = {
            "APPDATA",
            "COMSPEC",
            "HOME",
            "LANG",
            "LOCALAPPDATA",
            "NO_COLOR",
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "TEMP",
            "TERM",
            "TMP",
            "USERPROFILE",
        }
        env = {
            key: value
            for key, value in os.environ.copy().items()
            if key.upper() in safe_names or key.upper().startswith(("LC_", "XDG_"))
        }
        if rtk:
            env["RTK_TELEMETRY_DISABLED"] = "1"
        return self._runner(
            argv,
            env=env,
            timeout=self._timeout,
            max_output_bytes=self._max_output_bytes,
        )

    @staticmethod
    def _log_failure(tool: str, exc: BaseException) -> None:
        # Exception type only: paths, stderr, arguments, and output stay private.
        logger.debug(
            "{} optimization report unavailable ({})", tool, type(exc).__name__
        )

    async def _collect_rtk(self) -> RTKOptimizationReport:
        try:
            executable = self._resolve("rtk")
            if executable is None:
                return unavailable_rtk(
                    OptimizationState.NOT_INSTALLED,
                    "RTK is not installed or not on PATH.",
                )
            result = await asyncio.to_thread(
                self._run, [executable, "gain", "--format", "json"], rtk=True
            )
            if result.returncode != 0:
                return unavailable_rtk(
                    OptimizationState.ERROR, "RTK could not produce a savings report."
                )
            version = await self._read_version(executable, rtk=True)
            summary = parse_rtk_report(result.stdout, version=version)
            daily = await self._read_rtk_daily(executable)
            return replace(summary, daily=daily)
        except subprocess.TimeoutExpired as exc:
            self._log_failure("RTK", exc)
            return unavailable_rtk(OptimizationState.TIMEOUT, "RTK report timed out.")
        except (OptimizationReportError, OutputLimitExceeded, UnicodeError) as exc:
            self._log_failure("RTK", exc)
            return unavailable_rtk(
                OptimizationState.INVALID_OUTPUT,
                "RTK returned an invalid or unsupported report.",
            )
        except Exception as exc:
            self._log_failure("RTK", exc)
            return unavailable_rtk(
                OptimizationState.ERROR, "RTK report is unavailable."
            )

    async def _read_rtk_daily(
        self, executable: str
    ) -> tuple[RTKDailyReport, ...] | None:
        """Daily schema drift never invalidates an otherwise valid summary."""

        try:
            result = await asyncio.to_thread(
                self._run,
                [executable, "gain", "--daily", "--format", "json"],
                rtk=True,
            )
            if result.returncode != 0:
                return None
            return parse_rtk_report(result.stdout).daily
        except Exception as exc:
            self._log_failure("RTK daily trend", exc)
            return None

    async def _collect_headroom(self) -> HeadroomOptimizationReport:
        try:
            executable = self._resolve("headroom")
            if executable is None:
                return unavailable_headroom(
                    OptimizationState.NOT_INSTALLED,
                    "Headroom is not installed or not on PATH.",
                )
            result = await asyncio.to_thread(
                self._run, [executable, "savings", "--json"]
            )
            if result.returncode != 0:
                return unavailable_headroom(
                    OptimizationState.ERROR,
                    "Headroom could not produce a savings report.",
                )
            version = await self._read_version(executable, rtk=False)
            return parse_headroom_report(result.stdout, version=version)
        except subprocess.TimeoutExpired as exc:
            self._log_failure("Headroom", exc)
            return unavailable_headroom(
                OptimizationState.TIMEOUT, "Headroom report timed out."
            )
        except (OptimizationReportError, OutputLimitExceeded, UnicodeError) as exc:
            self._log_failure("Headroom", exc)
            return unavailable_headroom(
                OptimizationState.INVALID_OUTPUT,
                "Headroom returned an invalid or unsupported report.",
            )
        except Exception as exc:
            self._log_failure("Headroom", exc)
            return unavailable_headroom(
                OptimizationState.ERROR, "Headroom report is unavailable."
            )

    async def _read_version(self, executable: str, *, rtk: bool) -> str | None:
        """Version enrichment is optional and never invalidates a valid summary."""

        try:
            result = await asyncio.to_thread(
                self._run, [executable, "--version"], rtk=rtk
            )
            if result.returncode != 0:
                return None
            return parse_tool_version(result.stdout)
        except Exception as exc:
            self._log_failure("RTK version" if rtk else "Headroom version", exc)
            return None
