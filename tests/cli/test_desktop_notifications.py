"""Native desktop notification adapters."""

import sys
from typing import Any

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
def test_windows_notifier_uses_branded_toast(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeToastNotifier:
        notification: Any = None

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
