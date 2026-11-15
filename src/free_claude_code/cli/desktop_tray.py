"""pystray adapter for the Windows tray and macOS menu bar."""

import importlib
import sys
import threading
from collections.abc import Callable
from io import BytesIO

from loguru import logger
from PIL import Image
from pystray import Icon, Menu, MenuItem

from free_claude_code.cli.commands import ServerStatus
from free_claude_code.cli.desktop import (
    DesktopController,
    launch_desktop,
    version_text,
)
from free_claude_code.cli.desktop_assets import app_icon_bytes
from free_claude_code.cli.desktop_notifications import (
    DesktopNotification,
    NotificationLevel,
    create_desktop_notifier,
)
from free_claude_code.updater.check import (
    UpdateCheckResult,
    UpdateStatus,
    check_for_updates,
)


class PystrayDesktopTray:
    """Render desktop lifecycle actions through the native status area."""

    def __init__(self, controller: DesktopController) -> None:
        self._controller = controller
        self._update_lock = threading.RLock()
        self._update_check_active = False
        self._update_check_enabled = True
        self._update_status_label = "Update status: not checked"
        self._closed = False
        self._update_thread: threading.Thread | None = None
        self._update_check_item = MenuItem(
            "Check for Updates",
            self._check_updates,
            enabled=lambda _item: self._update_check_enabled,
        )
        self._update_status_item = MenuItem(
            lambda _item: self._update_status_label,
            lambda _icon, _item: None,
            enabled=False,
        )
        self._icon = Icon(
            "free-claude-code",
            _create_icon(),
            "Free Claude Code",
            self._build_menu(),
        )
        self._notifier = create_desktop_notifier(self._icon)

    def _build_menu(self) -> Menu:
        return Menu(
            MenuItem("Open Admin", self._open_admin, default=True),
            MenuItem("Check Server Status", self._check_status),
            MenuItem("Check Version", self._check_version),
            MenuItem("Test System Notification", self._test_notification),
            self._update_check_item,
            self._update_status_item,
            Menu.SEPARATOR,
            MenuItem("Restart Server", self._restart_server),
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit),
        )

    def run(self, setup: Callable[[], None]) -> None:
        def ready(icon: Icon) -> None:
            icon.visible = True
            setup()

        self._icon.run(setup=ready)

    def stop(self) -> None:
        with self._update_lock:
            if self._closed:
                return
            self._closed = True
        self._icon.stop()
        self._notifier.close()

    def _open_admin(self, _icon: Icon, _item: MenuItem) -> None:
        self._controller.open_admin()

    def _check_status(self, _icon: Icon, _item: MenuItem) -> None:
        status = self._controller.status
        level = {
            ServerStatus.RUNNING: NotificationLevel.SUCCESS,
            ServerStatus.STOPPED: NotificationLevel.WARNING,
        }.get(status, NotificationLevel.INFO)
        self._notify(f"Server is {status}.", level=level)

    def _check_version(self, _icon: Icon, _item: MenuItem) -> None:
        self._notify(version_text())

    def _test_notification(self, _icon: Icon, _item: MenuItem) -> None:
        self._notify(
            "System notifications are ready.",
            level=NotificationLevel.SUCCESS,
        )

    def _check_updates(self, _icon: Icon, _item: MenuItem) -> None:
        with self._update_lock:
            if self._closed or self._update_check_active:
                return
            self._update_check_active = True
            self._update_check_enabled = False
            self._update_status_label = "Update status: checking..."
        self._refresh_menu()
        thread = threading.Thread(
            target=self._run_update_check,
            name="fcc-update-check",
            daemon=True,
        )
        start_error: RuntimeError | None = None
        with self._update_lock:
            if self._closed:
                self._update_check_active = False
                self._update_check_enabled = True
                return
            self._update_thread = thread
            try:
                thread.start()
            except RuntimeError as exc:
                start_error = exc
        if start_error is not None:
            logger.error("Could not start the FCC update check: {}", start_error)
            self._update_thread = None
            self._finish_update_check(
                UpdateCheckResult(
                    status=UpdateStatus.FAILED,
                    message="Could not check for FCC updates. Please retry.",
                    detail=str(start_error),
                )
            )

    def _run_update_check(self) -> None:
        try:
            result = check_for_updates()
        except Exception as exc:
            logger.exception("Unexpected FCC update check failure")
            result = UpdateCheckResult(
                status=UpdateStatus.FAILED,
                message="Could not check for FCC updates. Please retry.",
                detail=str(exc),
            )
        self._finish_update_check(result)

    def _finish_update_check(self, result: UpdateCheckResult) -> None:
        with self._update_lock:
            self._update_check_active = False
            self._update_check_enabled = True
            if self._closed:
                return
            self._update_status_label = _update_status_text(result)
        self._refresh_menu()
        if result.status is UpdateStatus.FAILED:
            logger.error(
                "FCC update check failed: {}",
                result.detail or result.message,
            )
        level = {
            UpdateStatus.AVAILABLE: NotificationLevel.INFO,
            UpdateStatus.UP_TO_DATE: NotificationLevel.SUCCESS,
            UpdateStatus.LOCAL_NEWER: NotificationLevel.WARNING,
            UpdateStatus.FAILED: NotificationLevel.ERROR,
        }[result.status]
        self._notify(result.message, level=level)

    def _notify(
        self,
        message: str,
        *,
        level: NotificationLevel = NotificationLevel.INFO,
    ) -> None:
        try:
            self._notifier.notify(
                DesktopNotification(
                    title="Free Claude Code",
                    message=message,
                    level=level,
                )
            )
        except Exception:
            logger.exception("Could not display the FCC desktop notification")

    def _refresh_menu(self) -> None:
        with self._update_lock:
            if self._closed:
                return
        try:
            if sys.platform == "darwin":
                appkit = importlib.import_module("AppKit")
                appkit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    self._update_menu_on_main_thread
                )
            else:
                self._icon.update_menu()
        except Exception:
            logger.exception("Could not refresh the FCC tray menu")

    def _update_menu_on_main_thread(self) -> None:
        with self._update_lock:
            if self._closed:
                return
        try:
            self._icon.update_menu()
        except Exception:
            logger.exception("Could not refresh the FCC tray menu")

    def _restart_server(self, _icon: Icon, _item: MenuItem) -> None:
        self._controller.restart_server()

    def _quit(self, _icon: Icon, _item: MenuItem) -> None:
        self._controller.quit()


def _update_status_text(result: UpdateCheckResult) -> str:
    installed = result.installed or "unknown"
    if result.status is UpdateStatus.AVAILABLE:
        return f"Update available: {installed} -> {result.latest}"
    if result.status is UpdateStatus.UP_TO_DATE:
        return f"Up to date: {installed}"
    if result.status is UpdateStatus.LOCAL_NEWER:
        return f"Installed version is newer: {installed}"
    return "Update status: check failed"


def _create_icon() -> Image.Image:
    """Load the same branded artwork used by native desktop launchers."""

    with Image.open(BytesIO(app_icon_bytes(".png"))) as image:
        return image.convert("RGBA")


def launch(*, auto_started: bool = False) -> None:
    """Launch the supported native tray adapter."""

    launch_desktop(PystrayDesktopTray, auto_started=auto_started)
