"""Semantic desktop notifications shared by the native tray adapters."""

import importlib
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable

APP_USER_MODEL_ID = "io.github.amedeo82.free-claude-code"


class NotificationLevel(StrEnum):
    """User-facing severity of a desktop notification."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DesktopNotification:
    """Native notification content independent of its platform backend."""

    title: str
    message: str
    level: NotificationLevel = NotificationLevel.INFO


class DesktopIcon(Protocol):
    """Icon operations shared by the portable notification fallback."""

    def notify(self, message: str, title: str) -> None: ...


@runtime_checkable
class WindowsBalloonIcon(Protocol):
    """Native pystray operations used for Windows shell balloons."""

    _icon_handle: int

    def _message(
        self,
        code: int,
        flags: int,
        **values: object,
    ) -> None: ...


class DesktopNotifier(Protocol):
    """Display notifications without exposing platform-specific APIs."""

    def notify(self, notification: DesktopNotification) -> None: ...

    def close(self) -> None: ...


class _WindowsDesktopNotifier(Protocol):
    def notify(self, notification: DesktopNotification) -> None: ...

    def close(self) -> None: ...


class _WindowsDesktopNotifierFactory(Protocol):
    def __call__(self, icon: DesktopIcon) -> _WindowsDesktopNotifier: ...


class _WindowsDesktopNotificationsModule(Protocol):
    WindowsDesktopNotifier: _WindowsDesktopNotifierFactory


def notification_title(notification: DesktopNotification) -> str:
    """Return one consistent, branded title for every notification backend."""

    suffix = {
        NotificationLevel.INFO: "",
        NotificationLevel.SUCCESS: "Success",
        NotificationLevel.WARNING: "Warning",
        NotificationLevel.ERROR: "Error",
    }[notification.level]
    if not suffix:
        return notification.title
    return f"{notification.title} — {suffix}"


class PystrayDesktopNotifier:
    """Portable notification fallback backed by the tray icon."""

    def __init__(self, icon: DesktopIcon) -> None:
        self._icon = icon

    def notify(self, notification: DesktopNotification) -> None:
        self._icon.notify(notification.message, notification_title(notification))

    def close(self) -> None:
        return None


def create_desktop_notifier(icon: DesktopIcon) -> DesktopNotifier:
    """Create the best native notifier available on the current platform."""

    if sys.platform == "win32":
        module = cast(
            _WindowsDesktopNotificationsModule,
            importlib.import_module(
                "free_claude_code.cli.windows_desktop_notifications"
            ),
        )
        return module.WindowsDesktopNotifier(icon)
    return PystrayDesktopNotifier(icon)
