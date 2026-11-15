"""Native Windows toast and balloon notifications for the FCC system tray."""

import ctypes
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from loguru import logger

from free_claude_code.cli.desktop_assets import app_icon_bytes
from free_claude_code.cli.desktop_notifications import (
    APP_USER_MODEL_ID,
    DesktopNotification,
    NotificationLevel,
    PystrayDesktopNotifier,
)

_NIM_MODIFY = 0x00000001
_NIF_INFO = 0x00000010
_NIIF_INFO = 0x00000001
_NIIF_WARNING = 0x00000002
_NIIF_ERROR = 0x00000003
_NIIF_USER = 0x00000004
_NIIF_LARGE_ICON = 0x00000020

_LEVEL_FLAGS = {
    NotificationLevel.INFO: _NIIF_INFO,
    NotificationLevel.SUCCESS: _NIIF_INFO,
    NotificationLevel.WARNING: _NIIF_WARNING,
    NotificationLevel.ERROR: _NIIF_ERROR,
}

_LEVEL_TITLES = {
    NotificationLevel.INFO: "",
    NotificationLevel.SUCCESS: "Success — ",
    NotificationLevel.WARNING: "Warning — ",
    NotificationLevel.ERROR: "Error — ",
}


class WindowsDesktopNotifier:
    """Show branded Windows toasts with a native-styled balloon fallback."""

    def __init__(self, icon: Any, *, enable_toast: bool = True) -> None:
        self._icon = icon
        self._fallback = PystrayDesktopNotifier(icon)
        self._lock = threading.Lock()
        self._toast_notifier: Any = None
        self._logo_path: Path | None = None
        self._temporary_directory: TemporaryDirectory[str] | None = None
        if not enable_toast:
            return
        try:
            self._initialize_toast_notifier()
        except Exception:
            logger.warning(
                "Native Windows toasts are unavailable; using branded balloons",
                exc_info=True,
            )

    def notify(self, notification: DesktopNotification) -> None:
        with self._lock:
            if self._toast_notifier is not None:
                try:
                    self._notify_toast(notification)
                    return
                except Exception:
                    logger.warning(
                        "Could not display the native Windows toast; using a balloon",
                        exc_info=True,
                    )
                    self._toast_notifier = None
            self._notify_branded(notification)

    def close(self) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None
        self._logo_path = None

    def _initialize_toast_notifier(self) -> None:
        _set_process_app_user_model_id()
        self._toast_notifier = _create_toast_notifier()
        self._temporary_directory = TemporaryDirectory(
            prefix="fcc-desktop-notifications-"
        )
        self._logo_path = Path(self._temporary_directory.name) / "app-icon.png"
        self._logo_path.write_bytes(app_icon_bytes(".png"))

    def _notify_toast(self, notification: DesktopNotification) -> None:
        if self._logo_path is None:
            raise RuntimeError("The Windows notification logo is unavailable")
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import ToastNotification

        document = XmlDocument()
        toast = document.create_element("toast")
        document.append_child(toast)
        visual = document.create_element("visual")
        toast.append_child(visual)
        binding = document.create_element("binding")
        binding.set_attribute("template", "ToastGeneric")
        visual.append_child(binding)
        title = document.create_element("text")
        title.append_child(
            document.create_text_node(
                f"{_LEVEL_TITLES[notification.level]}{notification.title}"
            )
        )
        binding.append_child(title)
        message = document.create_element("text")
        message.append_child(document.create_text_node(notification.message))
        binding.append_child(message)
        image = document.create_element("image")
        image.set_attribute("placement", "appLogoOverride")
        image.set_attribute("src", self._logo_path.resolve().as_uri())
        binding.append_child(image)
        self._toast_notifier.show(ToastNotification(document))

    def _notify_branded(self, notification: DesktopNotification) -> None:
        send_message = getattr(self._icon, "_message", None)
        balloon_icon = getattr(self._icon, "_icon_handle", None)
        if not callable(send_message) or not balloon_icon:
            self._fallback.notify(notification)
            return
        try:
            send_message(
                _NIM_MODIFY,
                _NIF_INFO,
                szInfo=notification.message,
                szInfoTitle=notification.title,
                dwInfoFlags=(
                    _LEVEL_FLAGS[notification.level] | _NIIF_USER | _NIIF_LARGE_ICON
                ),
                hBalloonIcon=balloon_icon,
            )
        except Exception:
            logger.warning(
                "Could not display the branded Windows balloon; using the tray fallback",
                exc_info=True,
            )
            self._fallback.notify(notification)


def _create_toast_notifier() -> Any:
    from winrt.windows.ui.notifications import ToastNotificationManager

    return ToastNotificationManager.create_toast_notifier(APP_USER_MODEL_ID)


def _set_process_app_user_model_id() -> None:
    set_app_user_model_id = ctypes.WinDLL(
        "shell32", use_last_error=True
    ).SetCurrentProcessExplicitAppUserModelID
    set_app_user_model_id.argtypes = (ctypes.c_wchar_p,)
    set_app_user_model_id.restype = ctypes.c_int32
    result = set_app_user_model_id(APP_USER_MODEL_ID)
    if result != 0:
        raise OSError(
            "Could not set the Windows application identity: "
            f"HRESULT 0x{result & 0xFFFFFFFF:08X}"
        )
