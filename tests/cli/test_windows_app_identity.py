"""Windows application identity used by branded native toast notifications."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from free_claude_code.cli import windows_app_identity
from free_claude_code.cli.desktop_notifications import DesktopIcon

if sys.platform != "win32":
    pytest.skip(
        "Windows application identity is available only on Windows",
        allow_module_level=True,
    )


APP_USER_MODEL_ID = "io.github.amedeo82.free-claude-code"


class FakeRun:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> SimpleNamespace:
        self.commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_register_app_user_model_id_writes_branded_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_value = Mock()
    key = MagicMock()
    key.__enter__.return_value = Mock()
    create_key = Mock(return_value=key)
    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER=1,
        KEY_WRITE=2,
        REG_SZ=3,
        CreateKeyEx=create_key,
        SetValueEx=set_value,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    registered = windows_app_identity.register_app_user_model_id(
        APP_USER_MODEL_ID,
        Path("C:/Users/test/.fcc/app-icon.ico"),
    )

    assert registered is True
    create_key.assert_called_once_with(
        1,
        rf"Software\Classes\AppUserModelId\{APP_USER_MODEL_ID}",
        0,
        2,
    )
    values = {call.args[1]: call.args[4] for call in set_value.call_args_list}
    assert values == {
        "DisplayName": "Free Claude Code",
        "IconUri": str(Path("C:/Users/test/.fcc/app-icon.ico")),
        "IconBackgroundColor": "FF000000",
    }


def test_ensure_windows_app_identity_exports_icons_and_repairs_shortcut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exported: list[Path] = []
    monkeypatch.setattr(
        windows_app_identity,
        "app_icon_paths",
        lambda: (tmp_path / "app-icon.png", tmp_path / "app-icon.ico"),
    )

    def export_icon(destination: Path) -> None:
        exported.append(destination)

    def register_identity(app_user_model_id: str, _icon_path: Path) -> bool:
        return app_user_model_id == APP_USER_MODEL_ID

    shortcut_calls: list[tuple[str, Path]] = []

    def ensure_shortcut(app_user_model_id: str, icon_path: Path) -> bool:
        shortcut_calls.append((app_user_model_id, icon_path))
        return True

    monkeypatch.setattr(
        windows_app_identity,
        "export_app_icon",
        export_icon,
    )
    monkeypatch.setattr(
        windows_app_identity,
        "register_app_user_model_id",
        register_identity,
    )
    monkeypatch.setattr(
        windows_app_identity,
        "ensure_start_menu_shortcut",
        ensure_shortcut,
    )

    ensured = windows_app_identity.ensure_windows_app_identity(APP_USER_MODEL_ID)

    assert ensured is True
    assert exported == [tmp_path / "app-icon.png", tmp_path / "app-icon.ico"]
    assert shortcut_calls == [(APP_USER_MODEL_ID, tmp_path / "app-icon.ico")]


def test_ensure_windows_app_identity_stops_when_registry_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        windows_app_identity,
        "app_icon_paths",
        lambda: (tmp_path / "app-icon.png", tmp_path / "app-icon.ico"),
    )

    def export_icon(_destination: Path) -> None:
        return None

    def register_identity(_app_user_model_id: str, _icon_path: Path) -> bool:
        return False

    shortcut_calls: list[str] = []

    def ensure_shortcut(app_user_model_id: str, _icon_path: Path) -> bool:
        shortcut_calls.append(app_user_model_id)
        return True

    monkeypatch.setattr(
        windows_app_identity,
        "export_app_icon",
        export_icon,
    )
    monkeypatch.setattr(
        windows_app_identity,
        "register_app_user_model_id",
        register_identity,
    )
    monkeypatch.setattr(
        windows_app_identity,
        "ensure_start_menu_shortcut",
        ensure_shortcut,
    )

    ensured = windows_app_identity.ensure_windows_app_identity(APP_USER_MODEL_ID)

    assert ensured is False
    assert shortcut_calls == []


def test_ensure_start_menu_shortcut_invokes_powershell_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = FakeRun()
    monkeypatch.setattr(
        windows_app_identity,
        "_powershell_executable",
        lambda: "powershell.exe",
    )
    monkeypatch.setattr(
        windows_app_identity,
        "desktop_launcher_path",
        lambda: Path("C:/tools/fcc-desktop.exe"),
    )
    monkeypatch.setattr(windows_app_identity.subprocess, "run", run)

    created = windows_app_identity.ensure_start_menu_shortcut(
        APP_USER_MODEL_ID,
        tmp_path / "app-icon.ico",
    )

    assert created is True
    command = run.commands[0]
    assert command[0] == "powershell.exe"
    assert "-ExecutionPolicy" in command
    assert "Bypass" in command
    assert command[-6:] == [
        "-TargetPath",
        "C:\\tools\\fcc-desktop.exe",
        "-IconPath",
        str(tmp_path / "app-icon.ico"),
        "-AppUserModelId",
        APP_USER_MODEL_ID,
    ]


def test_ensure_start_menu_shortcut_reports_helper_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        windows_app_identity,
        "_powershell_executable",
        lambda: "powershell.exe",
    )
    monkeypatch.setattr(
        windows_app_identity.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=2, stdout="", stderr="")),
    )

    created = windows_app_identity.ensure_start_menu_shortcut(
        APP_USER_MODEL_ID,
        tmp_path / "app-icon.ico",
    )

    assert created is False


def test_ensure_start_menu_shortcut_without_powershell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        windows_app_identity,
        "_powershell_executable",
        lambda: None,
    )

    created = windows_app_identity.ensure_start_menu_shortcut(
        APP_USER_MODEL_ID,
        tmp_path / "app-icon.ico",
    )

    assert created is False


def test_desktop_launcher_path_prefers_the_desktop_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher = tmp_path / "fcc-desktop.exe"
    launcher.write_bytes(b"")
    interpreter = tmp_path / "pythonw.exe"
    interpreter.write_bytes(b"")
    monkeypatch.setattr(
        windows_app_identity.sys,
        "argv",
        [str(tmp_path / "fcc-desktop.exe")],
    )
    monkeypatch.setattr(
        windows_app_identity.sys,
        "executable",
        str(interpreter),
    )

    assert windows_app_identity.desktop_launcher_path() == launcher


def test_desktop_launcher_path_falls_back_to_the_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    interpreter = tmp_path / "pythonw.exe"
    interpreter.write_bytes(b"")
    monkeypatch.setattr(
        windows_app_identity.sys,
        "argv",
        [str(tmp_path / "module.py")],
    )
    monkeypatch.setattr(
        windows_app_identity.sys,
        "executable",
        str(interpreter),
    )

    assert windows_app_identity.desktop_launcher_path() == interpreter


def test_notifier_repairs_the_identity_before_showing_the_first_toast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from free_claude_code.cli import windows_desktop_notifications
    from free_claude_code.cli.desktop_notifications import (
        DesktopNotification,
        NotificationLevel,
    )

    class FakeToastNotifier:
        notification: object | None = None
        setting = 0

        def show(self, notification: object) -> None:
            self.notification = notification

    repaired: list[str] = []

    def ensure_identity(app_user_model_id: str) -> bool:
        repaired.append(app_user_model_id)
        return True

    monkeypatch.setattr(
        windows_desktop_notifications,
        "_set_process_app_user_model_id",
        lambda: None,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "_create_toast_notifier",
        lambda: FakeToastNotifier(),
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "ensure_windows_app_identity",
        ensure_identity,
    )

    def export_icon(_icon_path: Path) -> None:
        return None

    def config_directory() -> Path:
        return tmp_path

    monkeypatch.setattr(
        windows_desktop_notifications,
        "export_app_icon",
        export_icon,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "config_dir_path",
        config_directory,
    )

    class FakeIcon(DesktopIcon):
        def notify(self, message: str, title: str) -> None:
            return None

    notifier = windows_desktop_notifications.WindowsDesktopNotifier(FakeIcon())
    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Server is running.",
            level=NotificationLevel.SUCCESS,
        )
    )

    assert repaired == [APP_USER_MODEL_ID]
    notifier.close()
