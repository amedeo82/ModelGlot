"""Native desktop update confirmation and detached launcher contracts."""

import base64
import os
import shlex
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from free_claude_code.updater import desktop as desktop_update


class FakeMessageBox:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.argtypes: tuple[object, ...] = ()
        self.restype: type[object] = int

    def __call__(self, *arguments: object) -> int:
        self.calls.append(arguments)
        return 6


class FakeQueue:
    def __init__(self) -> None:
        self.operations: list[Callable[[], None]] = []

    def addOperationWithBlock_(self, operation: Callable[[], None]) -> None:
        self.operations.append(operation)
        operation()


class FakePopen:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.kwargs: list[dict[str, object]] = []

    def __call__(self, command: list[str], **kwargs: object) -> None:
        self.commands.append(command)
        self.kwargs.append(kwargs)


def test_windows_confirmation_uses_native_yes_no_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message_box = FakeMessageBox()
    user32 = SimpleNamespace(MessageBoxW=message_box)
    monkeypatch.setattr(desktop_update.sys, "platform", "win32")

    def load_user32(*_arguments: object, **_keywords: object) -> SimpleNamespace:
        return user32

    monkeypatch.setattr(desktop_update.ctypes, "WinDLL", load_user32, raising=False)

    assert desktop_update.confirm_update("2.0.0") is True

    call = message_box.calls[0]
    assert isinstance(call[1], str)
    assert isinstance(call[2], str)
    assert "FCC 2.0.0 is available" in call[1]
    assert "FCC will close" in call[1]
    assert call[2] == "ModelGlot update"


def test_macos_confirmation_runs_alert_on_main_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alert = Mock()
    alert.runModal.return_value = 1000
    queue = FakeQueue()

    def activate_ignoring_other_apps(_value: bool) -> None:
        return None

    def shared_application() -> SimpleNamespace:
        return SimpleNamespace(activateIgnoringOtherApps_=activate_ignoring_other_apps)

    def allocate_alert() -> SimpleNamespace:
        def initialize_alert() -> Mock:
            return alert

        return SimpleNamespace(init=initialize_alert)

    def main_queue() -> FakeQueue:
        return queue

    appkit = SimpleNamespace(
        NSApplication=SimpleNamespace(sharedApplication=shared_application),
        NSAlert=SimpleNamespace(alloc=allocate_alert),
        NSAlertFirstButtonReturn=1000,
        NSOperationQueue=SimpleNamespace(mainQueue=main_queue),
    )

    def import_appkit(_name: str) -> SimpleNamespace:
        return appkit

    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update.importlib, "import_module", import_appkit)

    assert desktop_update.confirm_update("2.0.0") is True

    alert.setInformativeText_.assert_called_once()
    alert.addButtonWithTitle_.assert_any_call("Install")
    alert.addButtonWithTitle_.assert_any_call("Cancel")


def test_windows_launcher_pins_release_and_detaches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    popen = FakePopen()

    def find_powershell(_name: str) -> str:
        return "powershell.exe"

    def installed_commands() -> tuple[str, str]:
        return (
            r"C:\Users\Test\.local\bin\fcc-update.cmd",
            r"C:\Users\Test\.local\bin\fcc-desktop.exe",
        )

    monkeypatch.setattr(desktop_update.sys, "platform", "win32")
    monkeypatch.setattr(
        desktop_update.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False
    )
    monkeypatch.setattr(
        desktop_update.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False
    )
    monkeypatch.setattr(desktop_update.subprocess, "Popen", popen)
    monkeypatch.setattr(desktop_update.shutil, "which", find_powershell)
    monkeypatch.setattr(
        desktop_update,
        "_installed_commands",
        installed_commands,
    )

    log_path = desktop_update.launch_update("2.0.0", tmp_path / "logs")

    command = popen.commands[0]
    script = base64.b64decode(command[-1]).decode("utf-16-le")
    assert "$env:FCC_INSTALL_VERSION = '2.0.0'" in script
    assert "$env:FCC_INSTALL_REF = ''" in script
    assert "fcc-update.cmd" in script
    assert "fcc-desktop.exe" in script
    assert f"$parentPid = {os.getpid()}" in script
    assert popen.kwargs[0]["creationflags"] != 0
    assert log_path.parent == tmp_path / "logs"
    assert log_path.is_file()


def test_macos_launcher_waits_then_reopens_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    popen = FakePopen()

    def installed_commands() -> tuple[str, str]:
        return (
            "/Users/Test/.local/bin/fcc-update",
            "/Users/Test/.local/bin/fcc-desktop",
        )

    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update.subprocess, "Popen", popen)
    monkeypatch.setattr(
        desktop_update,
        "_installed_commands",
        installed_commands,
    )

    desktop_update.launch_update("2.0.0", tmp_path / "logs")

    command = popen.commands[0]
    assert len(command) == 2
    assert command[0] == "/bin/sh"
    helper = Path(command[1])
    assert helper.name.startswith("fcc-desktop-update-")
    assert "/Users/Test/.local/bin/fcc-update" not in command
    script = helper.read_text(encoding="utf-8")
    assert "FCC_INSTALL_VERSION=2.0.0" in script
    assert "FCC_INSTALL_REF=''" in script
    assert "kill -0" in script
    assert "/usr/bin/open" in script
    assert shlex.quote("/Users/Test/.local/bin/fcc-desktop") in script
    assert popen.kwargs[0]["start_new_session"] is True
    helper.unlink()


def test_macos_launcher_removes_helper_when_spawn_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def installed_commands() -> tuple[str, str]:
        return ("/usr/local/bin/fcc-update", "/usr/local/bin/fcc-desktop")

    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(
        desktop_update,
        "_installed_commands",
        installed_commands,
    )
    monkeypatch.setattr(
        desktop_update.subprocess,
        "Popen",
        Mock(side_effect=OSError("spawn failed")),
    )
    helpers: list[str] = []
    helper_command = desktop_update._macos_helper_command

    def record_helper(script: str) -> list[str]:
        command = helper_command(script)
        helpers.append(command[1])
        return command

    monkeypatch.setattr(desktop_update, "_macos_helper_command", record_helper)

    with pytest.raises(OSError, match="spawn failed"):
        desktop_update.launch_update("2.0.0", tmp_path / "logs")

    assert len(helpers) == 1
    assert not Path(helpers[0]).exists()


def test_installed_commands_prefer_update_next_to_desktop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    desktop = tmp_path / "fcc-desktop"
    update = tmp_path / "fcc-update"
    desktop.write_text("desktop", encoding="utf-8")
    update.write_text("update", encoding="utf-8")
    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update.sys, "argv", [str(desktop)])

    assert desktop_update._installed_commands() == (str(update), str(desktop))


def test_installed_commands_find_update_in_managed_runtime_without_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "Free Claude Code.app/Contents/MacOS"
    bundle.mkdir(parents=True)
    desktop = bundle / "fcc-desktop"
    desktop.write_text("desktop", encoding="utf-8")
    runtime = tmp_path / "runtime/bin"
    runtime.mkdir(parents=True)
    python = runtime / "python"
    python.write_text("python", encoding="utf-8")
    update = runtime / "fcc-update"
    update.write_text("update", encoding="utf-8")
    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update.sys, "argv", [str(desktop)])
    monkeypatch.setattr(desktop_update.sys, "executable", str(python))

    def find_command(_name: str) -> None:
        return None

    monkeypatch.setattr(desktop_update.shutil, "which", find_command)

    assert desktop_update._installed_commands() == (str(update), str(desktop))


@pytest.mark.parametrize("version", ["", "v2.0.0", "2.0", "2.0.0rc1", "2.0.0;rm"])
def test_update_launcher_rejects_unsafe_or_nonstable_versions(
    version: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="canonical stable release"):
        desktop_update.launch_update(version, tmp_path / "logs")
