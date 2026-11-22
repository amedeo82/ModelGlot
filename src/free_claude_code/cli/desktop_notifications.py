"""Semantic desktop notifications shared by the native tray adapters."""

import importlib
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, cast

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


class DesktopNotifier(Protocol):
    """Display notifications without exposing platform-specific APIs."""

    def notify(self, notification: DesktopNotification) -> None: ...

    def close(self) -> None: ...


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

    def __init__(self, icon: Any) -> None:
        self._icon = icon

    def notify(self, notification: DesktopNotification) -> None:
        self._icon.notify(notification.message, notification_title(notification))

    def close(self) -> None:
        return None


def create_desktop_notifier(icon: Any) -> DesktopNotifier:
    """Create the best native notifier available on the current platform."""

    if sys.platform == "win32":
        windows_notifications = importlib.import_module(
            "free_claude_code.cli.windows_desktop_notifications"
        )
        notifier_type = cast(Any, windows_notifications).WindowsDesktopNotifier
        return notifier_type(icon)
    return PystrayDesktopNotifier(icon)
