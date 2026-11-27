"""Test-only instrumentation installed in a disposable ModelGlot environment."""

import asyncio
import multiprocessing
import os
import sys
import traceback
from collections.abc import Callable, Sequence
from importlib import import_module
from multiprocessing.context import DefaultContext
from multiprocessing.queues import Queue
from pathlib import Path
from typing import Never, Protocol, cast
from unittest.mock import patch

from modelglot.core.json_types import JsonObject


class _Timer(Protocol):
    def invalidate(self) -> None: ...


_installed = False


def _spawned_child(queue: Queue[dict[str, str | None]]):
    import modelglot

    queue.put(
        {
            "executable": sys.executable,
            "prefix": sys.prefix,
            "package": modelglot.__file__,
        }
    )


def subprocess_checks() -> JsonObject:
    from modelglot.runtime.folder_picker import NativeFolderPicker

    expected = str(Path.home())
    os.environ["MODELGLOT_NATIVE_DIALOG_RESULT"] = expected
    try:
        selected = asyncio.run(NativeFolderPicker().pick_folder(expected))
    finally:
        del os.environ["MODELGLOT_NATIVE_DIALOG_RESULT"]
    context = cast(DefaultContext, multiprocessing.get_context("spawn"))
    queue: Queue[dict[str, str | None]] = context.Queue()
    child = context.Process(target=_spawned_child, args=(queue,))
    child.start()
    try:
        result = queue.get(timeout=20)
        child.join(20)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.kill()
            child.join()
        queue.close()
        queue.join_thread()
    return {"folder": selected, "child": result}


def install():
    global _installed
    case = os.environ.get("MODELGLOT_NATIVE_CASE")
    if not case or _installed:
        return
    _installed = True
    if "MODELGLOT_NATIVE_DIALOG_RESULT" in os.environ:
        original_exec = os.execv

        def dialog_exec(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            argv: Sequence[str | bytes],
            /,
        ) -> Never:
            if path == "/usr/bin/osascript":
                print(os.environ["MODELGLOT_NATIVE_DIALOG_RESULT"], flush=True)
                raise SystemExit(0)
            original_exec(path, tuple(argv))

        patch.object(os, "execv", dialog_exec).start()
    identity = import_module("modelglot_identity_probe")
    if case == "identity":
        from modelglot.cli import desktop_entrypoint

        main: Callable[[], None] | None = getattr(identity, "main", None)
        if main is None:
            raise RuntimeError("The native identity probe has no main entry point")
        patch.object(desktop_entrypoint, "launch", main).start()
        return
    from modelglot.cli.desktop_tray import PystrayDesktopTray
    from modelglot.runtime.integration_service import IntegrationService
    from modelglot.runtime.provider_manager import ProviderRuntimeManager

    # Keep the real tray/server lifecycle, with external discovery and harness writes disabled.
    def skip_refresh(manager: ProviderRuntimeManager) -> None:
        pass

    patch.object(
        ProviderRuntimeManager, "start_model_list_refresh", skip_refresh
    ).start()

    async def no_integrations(service: IntegrationService):
        return None

    patch.object(IntegrationService, "start", no_integrations).start()
    original_run = PystrayDesktopTray.run

    def observed_run(self: PystrayDesktopTray, setup: Callable[[], None]):
        output = Path(os.environ["MODELGLOT_MACOS_PROBE_OUTPUT"])
        control = output.with_suffix(".command")
        process_report: Callable[[], JsonObject] | None = getattr(
            identity, "process_report", None
        )
        if process_report is None:
            raise RuntimeError(
                "The native identity probe has no process_report entry point"
            )
        write_report: Callable[[Path, JsonObject], None] | None = getattr(
            identity, "write_report", None
        )
        if write_report is None:
            raise RuntimeError(
                "The native identity probe has no write_report entry point"
            )
        tray_report: Callable[[object], JsonObject] | None = getattr(
            identity, "tray_report", None
        )
        if tray_report is None:
            raise RuntimeError(
                "The native identity probe has no tray_report entry point"
            )
        schedule_probe: Callable[[Callable[[object], None]], _Timer] | None = getattr(
            identity, "schedule_probe", None
        )
        if schedule_probe is None:
            raise RuntimeError(
                "The native identity probe has no schedule_probe entry point"
            )
        report = process_report()
        actions: list[str] = []
        write_report(output, report)

        def observe(_timer: object) -> None:
            try:
                report.update(tray_report(self._icon))
                report["server_status"] = str(self._controller.status)
                if control.exists():
                    command = control.read_text()
                    control.unlink()
                    if command == "subprocess":
                        report["subprocess"] = subprocess_checks()
                    else:
                        menu = self._icon._status_item.menu()
                        index = menu.indexOfItemWithTitle_(command)
                        assert index >= 0, command
                        menu.performActionForItemAtIndex_(index)
                        actions.append(command)
                        report["actions"] = actions
                write_report(output, report)
            except Exception:
                report["error"] = traceback.format_exc()
                write_report(output, report)
                self._controller.quit()

        timer = schedule_probe(observe)
        try:
            original_run(self, setup)
        finally:
            timer.invalidate()
            report["loop_finished"] = True
            write_report(output, report)

    patch.object(PystrayDesktopTray, "run", observed_run).start()
