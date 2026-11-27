"""Native Windows toast and balloon notifications for the ModelGlot system tray."""

import ctypes
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from loguru import logger

from modelglot.cli.desktop_assets import export_app_icon
from modelglot.cli.desktop_notifications import (
    APP_USER_MODEL_ID,
    DesktopIcon,
    DesktopNotification,
    NotificationLevel,
    PystrayDesktopNotifier,
    WindowsBalloonIcon,
    notification_title,
)
from modelglot.cli.windows_app_identity import ensure_windows_app_identity
from modelglot.config.paths import config_dir_path

if TYPE_CHECKING:
    from winrt.windows.ui.notifications import ToastNotifier

_IDENTITY_REPAIR_TIMEOUT_SECONDS = 30.0

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


class WindowsDesktopNotifier:
    """Show branded Windows toasts with a native-styled balloon fallback."""

    def __init__(
        self,
        icon: DesktopIcon | WindowsBalloonIcon,
        *,
        enable_toast: bool = True,
    ) -> None:
        self._icon = icon
        self._fallback = PystrayDesktopNotifier(cast(DesktopIcon, icon))
        self._lock = threading.Lock()
        self._toast_notifier: ToastNotifier | None = None
        self._logo_path: Path | None = None
        self._identity_thread: threading.Thread | None = None
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
                    self._wait_for_identity()
                    if not self._toast_enabled():
                        logger.warning(
                            "Windows notifications are disabled for ModelGlot; using a balloon"
                        )
                        self._toast_notifier = None
                    else:
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
        self._logo_path = None

    def _initialize_toast_notifier(self) -> None:
        _set_process_app_user_model_id()
        self._logo_path = config_dir_path() / "app-icon.png"
        export_app_icon(self._logo_path)
        self._toast_notifier = _create_toast_notifier()
        self._start_identity_repair()

    def _start_identity_repair(self) -> None:
        thread = threading.Thread(
            target=self._repair_identity,
            name="modelglot-app-identity",
            daemon=True,
        )
        self._identity_thread = thread
        thread.start()

    def _repair_identity(self) -> None:
        try:
            if not ensure_windows_app_identity(APP_USER_MODEL_ID):
                logger.warning(
                    "Could not complete the Windows app identity; "
                    "native toasts may not be displayed"
                )
        except Exception:
            logger.warning(
                "Could not complete the Windows app identity",
                exc_info=True,
            )

    def _wait_for_identity(self) -> None:
        thread = self._identity_thread
        if thread is None:
            return
        thread.join(_IDENTITY_REPAIR_TIMEOUT_SECONDS)

    def _toast_enabled(self) -> bool:
        try:
            from winrt.windows.ui.notifications import NotificationSetting
        except ImportError:
            return False
        notifier = self._toast_notifier
        if notifier is None:
            return False
        try:
            setting = notifier.setting
        except AttributeError, OSError, RuntimeError:
            return True
        return setting == NotificationSetting.ENABLED

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
        title.append_child(document.create_text_node(notification_title(notification)))
        binding.append_child(title)
        message = document.create_element("text")
        message.append_child(document.create_text_node(notification.message))
        binding.append_child(message)
        image = document.create_element("image")
        image.set_attribute("placement", "appLogoOverride")
        image.set_attribute("src", self._logo_path.resolve().as_uri())
        binding.append_child(image)
        notifier = self._toast_notifier
        if notifier is None:
            raise RuntimeError("The Windows toast notifier is unavailable")
        notifier.show(ToastNotification(document))

    def _notify_branded(self, notification: DesktopNotification) -> None:
        if not isinstance(self._icon, WindowsBalloonIcon):
            self._fallback.notify(notification)
            return
        send_message = self._icon._message
        balloon_icon = self._icon._icon_handle
        if not balloon_icon:
            self._fallback.notify(notification)
            return
        try:
            send_message(
                _NIM_MODIFY,
                _NIF_INFO,
                szInfo=notification.message,
                szInfoTitle=notification_title(notification),
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


def _create_toast_notifier() -> ToastNotifier:
    from winrt.windows.ui.notifications import ToastNotificationManager

    return ToastNotificationManager.create_toast_notifier(APP_USER_MODEL_ID)


class _WindowsFunction(Protocol):
    argtypes: tuple[object, ...]
    restype: type[object]

    def __call__(self, *arguments: object) -> int: ...


def _set_process_app_user_model_id() -> None:
    set_app_user_model_id = cast(
        _WindowsFunction,
        ctypes.WinDLL(
            "shell32", use_last_error=True
        ).SetCurrentProcessExplicitAppUserModelID,
    )
    set_app_user_model_id.argtypes = (ctypes.c_wchar_p,)
    set_app_user_model_id.restype = ctypes.c_int32
    result = set_app_user_model_id(APP_USER_MODEL_ID)
    if result != 0:
        raise OSError(
            "Could not set the Windows application identity: "
            f"HRESULT 0x{result & 0xFFFFFFFF:08X}"
        )
