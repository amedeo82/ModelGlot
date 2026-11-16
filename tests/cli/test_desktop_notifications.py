"""Native desktop notification adapters."""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from free_claude_code.cli import windows_desktop_notifications
from free_claude_code.cli.desktop_notifications import (
    DesktopNotification,
    NotificationLevel,
    PystrayDesktopNotifier,
)
from free_claude_code.cli.windows_desktop_notifications import (
    WindowsDesktopNotifier,
)


class FakePystrayIcon:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, message: str, title: str) -> None:
        self.notifications.append((message, title))


class FakeWindowsIcon:
    def __init__(self) -> None:
        self._icon_handle = 123
        self.messages: list[tuple[int, int, dict[str, object]]] = []
        self.notifications: list[tuple[str, str]] = []

    def _message(self, code: int, flags: int, **values: object) -> None:
        self.messages.append((code, flags, values))


def test_pystray_notifier_uses_icon_notification_api() -> None:
    icon = FakePystrayIcon()
    notifier = PystrayDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Server is running.",
            level=NotificationLevel.SUCCESS,
        )
    )

    assert icon.notifications == [("Server is running.", "Free Claude Code")]


def test_windows_notifier_sets_branded_icon_and_native_style() -> None:
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon, enable_toast=False)

    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Update available.",
            level=NotificationLevel.WARNING,
        )
    )

    code, flags, values = icon.messages[0]
    assert code == 1
    assert flags == 0x10
    assert values["szInfo"] == "Update available."
    assert values["szInfoTitle"] == "Free Claude Code"
    assert values["hBalloonIcon"] == 123
    assert values["dwInfoFlags"] == 0x02 | 0x04 | 0x20


def test_windows_notifier_maps_success_to_information_style() -> None:
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon, enable_toast=False)

    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Up to date.",
            level=NotificationLevel.SUCCESS,
        )
    )

    assert icon.messages[0][2]["dwInfoFlags"] == 0x01 | 0x04 | 0x20


def test_windows_notifier_falls_back_without_native_handles() -> None:
    class PlainIcon(FakePystrayIcon):
        pass

    icon = PlainIcon()
    notifier = WindowsDesktopNotifier(icon, enable_toast=False)

    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Fallback.",
            level=NotificationLevel.INFO,
        )
    )

    assert icon.notifications == [("Fallback.", "Free Claude Code")]


def test_windows_notifier_falls_back_when_native_balloon_fails() -> None:
    class FailingWindowsIcon(FakeWindowsIcon):
        def notify(self, message: str, title: str) -> None:
            self.notifications.append((message, title))

        def _message(self, code: int, flags: int, **values: object) -> None:
            raise RuntimeError("shell unavailable")

    icon = FailingWindowsIcon()
    notifier = WindowsDesktopNotifier(icon, enable_toast=False)

    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Fallback.",
            level=NotificationLevel.ERROR,
        )
    )

    assert icon.notifications == [("Fallback.", "Free Claude Code")]


@pytest.mark.skipif(
    sys.platform != "win32", reason="WinRT is available only on Windows"
)
def test_windows_notifier_uses_branded_toast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeToastNotifier:
        notification: Any = None
        setting = 0

        def show(self, notification) -> None:
            self.notification = notification

    toast_notifier = FakeToastNotifier()
    monkeypatch.setattr(
        windows_desktop_notifications,
        "_set_process_app_user_model_id",
        lambda: None,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "_create_toast_notifier",
        lambda: toast_notifier,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "_register_app_user_model_id",
        lambda _icon_path: None,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "export_app_icon",
        lambda _icon_path: None,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "config_dir_path",
        lambda: tmp_path,
    )
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Server is running.",
            level=NotificationLevel.SUCCESS,
        )
    )

    assert icon.messages == []
    assert toast_notifier.notification is not None
    document = toast_notifier.notification.content.get_xml()
    assert "Success — Free Claude Code" in document
    assert "Server is running." in document
    assert 'placement="appLogoOverride"' in document
    assert "file:///" in document
    notifier.close()


@pytest.mark.skipif(
    sys.platform != "win32", reason="WinRT is available only on Windows"
)
def test_windows_notifier_falls_back_when_toast_is_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class DisabledToastNotifier:
        setting = 1

        def show(self, _notification) -> None:
            raise AssertionError("Disabled toasts must not be shown")

    monkeypatch.setattr(
        windows_desktop_notifications,
        "_set_process_app_user_model_id",
        lambda: None,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "_create_toast_notifier",
        lambda: DisabledToastNotifier(),
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "_register_app_user_model_id",
        lambda _icon_path: None,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "export_app_icon",
        lambda _icon_path: None,
    )
    monkeypatch.setattr(
        windows_desktop_notifications,
        "config_dir_path",
        lambda: tmp_path,
    )
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="Free Claude Code",
            message="Fallback.",
            level=NotificationLevel.INFO,
        )
    )

    assert len(icon.messages) == 1
    assert icon.messages[0][2]["szInfo"] == "Fallback."
    notifier.close()


def test_windows_notifier_registers_app_user_model_id(
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

    windows_desktop_notifications._register_app_user_model_id(
        Path("C:/Users/test/.fcc/app-icon.png")
    )

    create_key.assert_called_once_with(
        1,
        r"Software\Classes\AppUserModelId\io.github.alishahryar1.free-claude-code",
        0,
        2,
    )
    values = {call.args[1]: call.args[4] for call in set_value.call_args_list}
    assert values == {
        "DisplayName": "Free Claude Code",
        "IconUri": str(Path("C:/Users/test/.fcc/app-icon.png")),
        "IconBackgroundColor": "FF000000",
    }
