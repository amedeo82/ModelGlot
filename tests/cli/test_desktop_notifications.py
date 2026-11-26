"""Native desktop notification adapters."""

import sys
from pathlib import Path
from typing import Protocol, cast, override

import pytest

from free_claude_code.cli import windows_desktop_notifications
from free_claude_code.cli.desktop_notifications import (
    APP_USER_MODEL_ID,
    DesktopNotification,
    NotificationLevel,
    PystrayDesktopNotifier,
    notification_title,
)
from free_claude_code.cli.windows_desktop_notifications import (
    WindowsDesktopNotifier,
)


class ToastContent(Protocol):
    def get_xml(self) -> str: ...


class ToastNotification(Protocol):
    @property
    def content(self) -> ToastContent: ...


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

    def notify(self, message: str, title: str) -> None:
        self.notifications.append((message, title))

    def _message(self, code: int, flags: int, **values: object) -> None:
        self.messages.append((code, flags, values))


def test_pystray_notifier_uses_icon_notification_api() -> None:
    icon = FakePystrayIcon()
    notifier = PystrayDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
            message="Server is running.",
            level=NotificationLevel.SUCCESS,
        )
    )

    assert icon.notifications == [("Server is running.", "ModelGlot — Success")]


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (NotificationLevel.INFO, "ModelGlot"),
        (NotificationLevel.SUCCESS, "ModelGlot — Success"),
        (NotificationLevel.WARNING, "ModelGlot — Warning"),
        (NotificationLevel.ERROR, "ModelGlot — Error"),
    ],
)
def test_notification_title_uses_consistent_brand_and_severity(
    level: NotificationLevel, expected: str
) -> None:
    notification = DesktopNotification(
        title="ModelGlot",
        message="Server is running.",
        level=level,
    )

    assert notification_title(notification) == expected


def test_user_facing_notifications_do_not_expose_upstream_repository() -> None:
    icon = FakePystrayIcon()
    notifier = PystrayDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
            message="ModelGlot update available.",
            level=NotificationLevel.INFO,
        )
    )

    rendered = " ".join(value for pair in icon.notifications for value in pair)
    assert "alishahryar1" not in rendered.lower()
    assert "github.com" not in rendered.lower()
    assert APP_USER_MODEL_ID == "io.github.amedeo82.modelglot"


def test_windows_notifier_sets_branded_icon_and_native_style() -> None:
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon, enable_toast=False)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
            message="Update available.",
            level=NotificationLevel.WARNING,
        )
    )

    code, flags, values = icon.messages[0]
    assert code == 1
    assert flags == 0x10
    assert values["szInfo"] == "Update available."
    assert values["szInfoTitle"] == "ModelGlot — Warning"
    assert values["hBalloonIcon"] == 123
    assert values["dwInfoFlags"] == 0x02 | 0x04 | 0x20


def test_windows_notifier_maps_success_to_information_style() -> None:
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon, enable_toast=False)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
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
            title="ModelGlot",
            message="Fallback.",
            level=NotificationLevel.INFO,
        )
    )

    assert icon.notifications == [("Fallback.", "ModelGlot")]


def test_windows_notifier_falls_back_when_native_balloon_fails() -> None:
    class FailingWindowsIcon(FakeWindowsIcon):
        @override
        def notify(self, message: str, title: str) -> None:
            self.notifications.append((message, title))

        @override
        def _message(self, code: int, flags: int, **values: object) -> None:
            raise RuntimeError("shell unavailable")

    icon = FailingWindowsIcon()
    notifier = WindowsDesktopNotifier(icon, enable_toast=False)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
            message="Fallback.",
            level=NotificationLevel.ERROR,
        )
    )

    assert icon.notifications == [("Fallback.", "ModelGlot — Error")]


@pytest.mark.skipif(
    sys.platform != "win32", reason="WinRT is available only on Windows"
)
def test_windows_notifier_uses_branded_toast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeToastNotifier:
        notification: ToastNotification | None = None
        setting = 0

        def show(self, notification: object) -> None:
            self.notification = cast(ToastNotification, notification)

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

    def ensure_identity(_app_user_model_id: str) -> bool:
        return True

    def export_icon(_icon_path: Path) -> None:
        return None

    def config_directory() -> Path:
        return tmp_path

    monkeypatch.setattr(
        windows_desktop_notifications,
        "ensure_windows_app_identity",
        ensure_identity,
    )
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
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
            message="Server is running.",
            level=NotificationLevel.SUCCESS,
        )
    )

    assert icon.messages == []
    assert toast_notifier.notification is not None
    document = toast_notifier.notification.content.get_xml()
    assert "ModelGlot — Success" in document
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

        def show(self, _notification: object) -> None:
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

    def ensure_identity(_app_user_model_id: str) -> bool:
        return True

    def export_icon(_icon_path: Path) -> None:
        return None

    def config_directory() -> Path:
        return tmp_path

    monkeypatch.setattr(
        windows_desktop_notifications,
        "ensure_windows_app_identity",
        ensure_identity,
    )
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
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
            message="Fallback.",
            level=NotificationLevel.INFO,
        )
    )

    assert len(icon.messages) == 1
    assert icon.messages[0][2]["szInfo"] == "Fallback."
    notifier.close()


@pytest.mark.skipif(
    sys.platform != "win32", reason="WinRT is available only on Windows"
)
def test_windows_notifier_keeps_native_toasts_when_setting_lookup_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class UnresolvedToastNotifier:
        notification: ToastNotification | None = None

        @property
        def setting(self) -> object:
            raise OSError("Element not found")

        def show(self, notification: object) -> None:
            self.notification = cast(ToastNotification, notification)

    toast_notifier = UnresolvedToastNotifier()
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

    def ensure_identity(_app_user_model_id: str) -> bool:
        return True

    def export_icon(_icon_path: Path) -> None:
        return None

    def config_directory() -> Path:
        return tmp_path

    monkeypatch.setattr(
        windows_desktop_notifications,
        "ensure_windows_app_identity",
        ensure_identity,
    )
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
    icon = FakeWindowsIcon()
    notifier = WindowsDesktopNotifier(icon)

    notifier.notify(
        DesktopNotification(
            title="ModelGlot",
            message="Server is running.",
            level=NotificationLevel.SUCCESS,
        )
    )

    assert icon.messages == []
    assert toast_notifier.notification is not None
    notifier.close()
