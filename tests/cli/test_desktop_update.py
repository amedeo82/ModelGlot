"""Native desktop update confirmation and detached launcher contracts."""

import base64
import os
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from free_claude_code.updater import desktop as desktop_update


def test_windows_confirmation_uses_native_yes_no_dialog(monkeypatch) -> None:
    user32 = SimpleNamespace(MessageBoxW=Mock(return_value=6))
    monkeypatch.setattr(desktop_update.sys, "platform", "win32")
    monkeypatch.setattr(
        desktop_update.ctypes, "WinDLL", lambda *_args, **_kwargs: user32
    )

    assert desktop_update.confirm_update("2.0.0") is True

    call = user32.MessageBoxW.call_args
    assert "FCC 2.0.0 is available" in call.args[1]
    assert "FCC will close" in call.args[1]
    assert call.args[2] == "Free Claude Code update"


def test_macos_confirmation_runs_alert_on_main_queue(monkeypatch) -> None:
    alert = Mock()
    alert.runModal.return_value = 1000
    queue = Mock()
    queue.addOperationWithBlock_.side_effect = lambda operation: operation()
    appkit = SimpleNamespace(
        NSApplication=SimpleNamespace(
            sharedApplication=lambda: SimpleNamespace(
                activateIgnoringOtherApps_=lambda _value: None
            )
        ),
        NSAlert=SimpleNamespace(alloc=lambda: SimpleNamespace(init=lambda: alert)),
        NSAlertFirstButtonReturn=1000,
        NSOperationQueue=SimpleNamespace(mainQueue=lambda: queue),
    )
    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update.importlib, "import_module", lambda _name: appkit)

    assert desktop_update.confirm_update("2.0.0") is True

    alert.setInformativeText_.assert_called_once()
    alert.addButtonWithTitle_.assert_any_call("Install")
    alert.addButtonWithTitle_.assert_any_call("Cancel")


def test_windows_launcher_pins_release_and_detaches(
    monkeypatch, tmp_path: Path
) -> None:
    popen = Mock()
    monkeypatch.setattr(desktop_update.sys, "platform", "win32")
    monkeypatch.setattr(desktop_update.subprocess, "Popen", popen)
    monkeypatch.setattr(desktop_update.shutil, "which", lambda name: "powershell.exe")
    monkeypatch.setattr(desktop_update, "config_dir_path", lambda: tmp_path)
    monkeypatch.setattr(
        desktop_update,
        "_installed_commands",
        lambda: (
            r"C:\Users\Test\.local\bin\fcc-update.cmd",
            r"C:\Users\Test\.local\bin\fcc-desktop.exe",
        ),
    )

    log_path = desktop_update.launch_update("2.0.0")

    command = popen.call_args.args[0]
    script = base64.b64decode(command[-1]).decode("utf-16-le")
    assert "$env:FCC_INSTALL_VERSION = '2.0.0'" in script
    assert "$env:FCC_INSTALL_REF = ''" in script
    assert "fcc-update.cmd" in script
    assert "fcc-desktop.exe" in script
    assert f"$parentPid = {os.getpid()}" in script
    assert popen.call_args.kwargs["creationflags"] != 0
    assert log_path.parent == tmp_path / "logs"
    assert log_path.is_file()


def test_macos_launcher_waits_then_reopens_app(monkeypatch, tmp_path: Path) -> None:
    popen = Mock()
    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update.subprocess, "Popen", popen)
    monkeypatch.setattr(desktop_update, "config_dir_path", lambda: tmp_path)
    monkeypatch.setattr(
        desktop_update,
        "_installed_commands",
        lambda: (
            "/Users/Test/.local/bin/fcc-update",
            "/Users/Test/.local/bin/fcc-desktop",
        ),
    )

    desktop_update.launch_update("2.0.0")

    command = popen.call_args.args[0]
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
    assert popen.call_args.kwargs["start_new_session"] is True
    helper.unlink()


def test_macos_launcher_removes_helper_when_spawn_fails(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update, "config_dir_path", lambda: tmp_path)
    monkeypatch.setattr(
        desktop_update,
        "_installed_commands",
        lambda: ("/usr/local/bin/fcc-update", "/usr/local/bin/fcc-desktop"),
    )
    monkeypatch.setattr(
        desktop_update.subprocess,
        "Popen",
        Mock(side_effect=OSError("spawn failed")),
    )
    helpers = []
    helper_command = desktop_update._macos_helper_command

    def record_helper(script: str) -> list[str]:
        command = helper_command(script)
        helpers.append(command[1])
        return command

    monkeypatch.setattr(desktop_update, "_macos_helper_command", record_helper)

    with pytest.raises(OSError, match="spawn failed"):
        desktop_update.launch_update("2.0.0")

    assert len(helpers) == 1
    assert not Path(helpers[0]).exists()


def test_installed_commands_prefer_update_next_to_desktop(
    monkeypatch, tmp_path: Path
) -> None:
    desktop = tmp_path / "fcc-desktop"
    update = tmp_path / "fcc-update"
    desktop.write_text("desktop", encoding="utf-8")
    update.write_text("update", encoding="utf-8")
    monkeypatch.setattr(desktop_update.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_update.sys, "argv", [str(desktop)])

    assert desktop_update._installed_commands() == (str(update), str(desktop))


def test_installed_commands_find_update_in_managed_runtime_without_path(
    monkeypatch, tmp_path: Path
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
    monkeypatch.setattr(desktop_update.shutil, "which", lambda _name: None)

    assert desktop_update._installed_commands() == (str(update), str(desktop))


@pytest.mark.parametrize("version", ["", "v2.0.0", "2.0", "2.0.0rc1", "2.0.0;rm"])
def test_update_launcher_rejects_unsafe_or_nonstable_versions(version: str) -> None:
    with pytest.raises(ValueError, match="canonical stable release"):
        desktop_update.launch_update(version)
