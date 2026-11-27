"""pystray adapter for the Windows tray and macOS menu bar."""

import importlib
import sys
import threading
import time
from collections.abc import Callable
from io import BytesIO
from typing import Protocol, cast

from loguru import logger
from PIL import Image
from pystray import Icon, Menu, MenuItem

from modelglot.cli.commands import ServerStatus
from modelglot.cli.desktop import (
    DesktopController,
    launch_desktop,
)
from modelglot.cli.desktop_assets import app_icon_bytes
from modelglot.cli.desktop_notifications import (
    DesktopNotification,
    NotificationLevel,
    create_desktop_notifier,
)
from modelglot.config.paths import config_dir_path
from modelglot.core.version import package_version
from modelglot.updater.check import (
    UpdateCheckResult,
    UpdateStatus,
    check_for_updates,
)
from modelglot.updater.desktop import confirm_update, launch_update


class _MacOSOperationQueue(Protocol):
    def addOperationWithBlock_(self, operation: Callable[[], None]) -> None: ...


class _MacOSOperationQueueFactory(Protocol):
    def mainQueue(self) -> _MacOSOperationQueue: ...


class _AppKit(Protocol):
    NSOperationQueue: _MacOSOperationQueueFactory


def _noop_action(_icon: Icon, _item: MenuItem) -> None:
    return None


class PystrayDesktopTray:
    """Render desktop lifecycle actions through the native status area."""

    def __init__(self, controller: DesktopController) -> None:
        self._controller = controller
        self._update_lock = threading.RLock()
        self._update_check_active = False
        self._update_check_enabled = True
        self._update_status_label = "○ Not checked"
        self._server_status_label = _server_status_text(controller.status)
        self._version_label = f"v{package_version()}"
        self._closed = False
        self._restart_active = False
        self._update_thread: threading.Thread | None = None
        self._restart_thread: threading.Thread | None = None
        self._status_thread: threading.Thread | None = None

        def server_status_text(_item: MenuItem) -> str:
            return self._server_status_label

        def version_text(_item: MenuItem) -> str:
            return self._version_label

        def update_status_text(_item: MenuItem) -> str:
            return self._update_status_label

        def restart_text(_item: MenuItem) -> str:
            return "Restarting Server…" if self._restart_active else "Restart Server"

        def update_check_enabled(_item: MenuItem) -> bool:
            return self._update_check_enabled

        def restart_enabled(_item: MenuItem) -> bool:
            return not self._restart_active

        self._brand_item = MenuItem(
            "ModelGlot",
            _noop_action,
            enabled=False,
        )
        self._server_status_item = MenuItem(
            server_status_text,
            _noop_action,
            enabled=False,
        )
        self._version_item = MenuItem(
            version_text,
            _noop_action,
            enabled=False,
        )
        self._update_check_item = MenuItem(
            "Check for Updates",
            self._check_updates,
            enabled=update_check_enabled,
        )
        self._update_status_item = MenuItem(
            update_status_text,
            _noop_action,
            enabled=False,
        )
        self._restart_item = MenuItem(
            restart_text,
            self._restart_server,
            enabled=restart_enabled,
        )
        self._icon = Icon(
            "modelglot",
            _create_icon(),
            "ModelGlot",
            self._build_menu(),
        )
        self._notifier = create_desktop_notifier(self._icon)

    def _build_menu(self) -> Menu:
        return Menu(
            self._brand_item,
            self._server_status_item,
            self._version_item,
            Menu.SEPARATOR,
            MenuItem("Open Admin", self._open_admin, default=True),
            MenuItem("Refresh Server Status", self._check_status),
            self._update_check_item,
            self._update_status_item,
            Menu.SEPARATOR,
            self._restart_item,
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit),
        )

    def run(self, setup: Callable[[], None]) -> None:
        with self._update_lock:
            self._server_status_label = "◌ Starting…"

        def ready(icon: Icon) -> None:
            icon.visible = True
            setup()
            self._start_status_watcher()

        self._icon.run(setup=ready)

    def stop(self) -> None:
        with self._update_lock:
            if self._closed:
                return
            self._closed = True
        self._icon.stop()
        self._notifier.close()

    def _start_status_watcher(self) -> None:
        with self._update_lock:
            if self._closed or self._status_thread is not None:
                return
            thread = threading.Thread(
                target=self._watch_server_status,
                name="modelglot-server-status",
                daemon=True,
            )
            self._status_thread = thread
        try:
            thread.start()
        except RuntimeError as exc:
            logger.error("Could not start the ModelGlot server status watcher: {}", exc)
            with self._update_lock:
                self._status_thread = None

    def _watch_server_status(self) -> None:
        while True:
            with self._update_lock:
                if self._closed:
                    return
            self._sync_server_status()
            time.sleep(0.25)

    def _sync_server_status(self) -> None:
        with self._update_lock:
            if self._closed or self._restart_active:
                return
        label = _server_status_text(self._controller.status)
        with self._update_lock:
            if self._closed or self._restart_active:
                return
            if self._server_status_label == label:
                return
            self._server_status_label = label
        self._refresh_menu()

    def _open_admin(self, _icon: Icon, _item: MenuItem) -> None:
        self._controller.open_admin()
        self._notify(
            "Opening the ModelGlot Admin UI…",
            level=NotificationLevel.INFO,
        )

    def _check_status(self, _icon: Icon, _item: MenuItem) -> None:
        status = self._controller.status
        self._set_server_status(_server_status_text(status))
        level = {
            ServerStatus.RUNNING: NotificationLevel.SUCCESS,
            ServerStatus.STOPPED: NotificationLevel.WARNING,
        }.get(status, NotificationLevel.INFO)
        self._notify(_server_status_message(status), level=level)

    def _check_updates(self, _icon: Icon, _item: MenuItem) -> None:
        with self._update_lock:
            if self._closed or self._update_check_active:
                return
            self._update_check_active = True
            self._update_check_enabled = False
            self._update_status_label = "◌ Checking…"
        self._refresh_menu()
        thread = threading.Thread(
            target=self._run_update_check,
            name="modelglot-update-check",
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
            logger.error("Could not start the ModelGlot update check: {}", start_error)
            self._update_thread = None
            self._finish_update_check(
                UpdateCheckResult(
                    status=UpdateStatus.FAILED,
                    message="Could not check for ModelGlot updates. Please retry.",
                    detail=str(start_error),
                )
            )

    def _run_update_check(self) -> None:
        try:
            result = check_for_updates()
        except Exception as exc:
            logger.exception("Unexpected ModelGlot update check failure")
            result = UpdateCheckResult(
                status=UpdateStatus.FAILED,
                message="Could not check for ModelGlot updates. Please retry.",
                detail=str(exc),
            )
        self._finish_update_check(result)

    def _finish_update_check(self, result: UpdateCheckResult) -> None:
        offer_update = result.status is UpdateStatus.AVAILABLE
        with self._update_lock:
            self._update_check_active = offer_update
            self._update_check_enabled = not offer_update
            if self._closed:
                return
            self._update_status_label = _update_status_text(result)
        self._refresh_menu()
        if result.status is UpdateStatus.FAILED:
            logger.error(
                "ModelGlot update check failed: {}",
                result.detail or result.message,
            )
        level = {
            UpdateStatus.AVAILABLE: NotificationLevel.INFO,
            UpdateStatus.UP_TO_DATE: NotificationLevel.SUCCESS,
            UpdateStatus.LOCAL_NEWER: NotificationLevel.WARNING,
            UpdateStatus.FAILED: NotificationLevel.ERROR,
        }[result.status]
        self._notify(result.message, level=level)
        if offer_update:
            self._offer_update(result)

    def _offer_update(self, result: UpdateCheckResult) -> None:
        with self._update_lock:
            if self._closed:
                return
        latest = result.latest
        if latest is None:
            logger.error("ModelGlot update result has no release to install")
            self._finish_update_offer()
            self._notify(
                "Could not start the ModelGlot update. Run modelglot-update from a terminal.",
                level=NotificationLevel.ERROR,
            )
            return
        try:
            confirmed = confirm_update(latest)
        except Exception:
            logger.exception("Could not display the ModelGlot update confirmation")
            self._finish_update_offer()
            self._notify(
                "Could not display the update confirmation. Please retry.",
                level=NotificationLevel.ERROR,
            )
            return
        if not confirmed:
            self._finish_update_offer()
            return
        with self._update_lock:
            if self._closed:
                return
            self._update_status_label = f"◌ Installing {latest}…"
        self._refresh_menu()
        try:
            log_path = launch_update(latest, config_dir_path() / "logs")
        except Exception:
            logger.exception("Could not launch the ModelGlot update installer")
            with self._update_lock:
                if not self._closed:
                    self._update_status_label = _update_status_text(result)
            self._finish_update_offer()
            self._notify(
                "Could not start the ModelGlot update. Run modelglot-update from a terminal.",
                level=NotificationLevel.ERROR,
            )
            return
        logger.info("ModelGlot desktop updater started; output: {}", log_path)
        self._notify(
            f"Installing ModelGlot {latest}. ModelGlot will close and reopen when it finishes.",
            level=NotificationLevel.INFO,
        )
        self._controller.quit()

    def _finish_update_offer(self) -> None:
        with self._update_lock:
            self._update_check_active = False
            self._update_check_enabled = True
            if self._closed:
                return
        self._refresh_menu()

    def _notify(
        self,
        message: str,
        *,
        level: NotificationLevel = NotificationLevel.INFO,
    ) -> None:
        with self._update_lock:
            if self._closed:
                return
        try:
            self._notifier.notify(
                DesktopNotification(
                    title="ModelGlot",
                    message=message,
                    level=level,
                )
            )
        except Exception:
            logger.exception("Could not display the ModelGlot desktop notification")

    def _set_server_status(self, label: str) -> None:
        with self._update_lock:
            if self._closed:
                return
            self._server_status_label = label
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        with self._update_lock:
            if self._closed:
                return
        try:
            if sys.platform == "darwin":
                appkit = cast(_AppKit, importlib.import_module("AppKit"))
                appkit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    self._update_menu_on_main_thread
                )
            else:
                self._icon.update_menu()
        except Exception:
            logger.exception("Could not refresh the ModelGlot tray menu")

    def _update_menu_on_main_thread(self) -> None:
        with self._update_lock:
            if self._closed:
                return
        try:
            self._icon.update_menu()
        except Exception:
            logger.exception("Could not refresh the ModelGlot tray menu")

    def _restart_server(self, _icon: Icon, _item: MenuItem) -> None:
        with self._update_lock:
            if self._closed or self._restart_active:
                return
            self._restart_active = True
        self._set_server_status("◌ Restarting…")
        self._notify(
            "Restarting the ModelGlot server…",
            level=NotificationLevel.INFO,
        )
        try:
            self._controller.restart_server()
        except Exception:
            logger.exception("Could not restart the ModelGlot server")
            self._finish_restart(
                "○ Restart failed",
                "Could not restart the ModelGlot server.",
                NotificationLevel.ERROR,
            )
            return
        thread = threading.Thread(
            target=self._wait_for_restart,
            name="modelglot-restart-status",
            daemon=True,
        )
        with self._update_lock:
            self._restart_thread = thread
        try:
            thread.start()
        except RuntimeError as exc:
            logger.error("Could not start the ModelGlot restart watcher: {}", exc)
            self._finish_restart(
                "○ Restart failed",
                "Could not restart the ModelGlot server.",
                NotificationLevel.ERROR,
            )

    def _finish_restart(
        self,
        status_label: str,
        message: str,
        level: NotificationLevel,
    ) -> None:
        with self._update_lock:
            if self._closed:
                return
            self._restart_active = False
            self._server_status_label = status_label
        self._refresh_menu()
        self._notify(message, level=level)

    def _wait_for_restart(self) -> None:
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            with self._update_lock:
                if self._closed:
                    return
            status = self._controller.status
            if status is ServerStatus.RUNNING:
                self._finish_restart(
                    _server_status_text(status),
                    "Server restarted.",
                    NotificationLevel.SUCCESS,
                )
                return
            if status is ServerStatus.STOPPED:
                self._finish_restart(
                    _server_status_text(status),
                    "The ModelGlot server stopped during restart.",
                    NotificationLevel.ERROR,
                )
                return
            time.sleep(0.25)
        self._finish_restart(
            "◌ Restart timed out",
            "The ModelGlot server did not restart in time.",
            NotificationLevel.WARNING,
        )

    def _quit(self, _icon: Icon, _item: MenuItem) -> None:
        self._controller.quit()


def _update_status_text(result: UpdateCheckResult) -> str:
    installed = result.installed or "unknown"
    if result.status is UpdateStatus.AVAILABLE:
        return f"● Update available: {installed} → {result.latest}"
    if result.status is UpdateStatus.UP_TO_DATE:
        return f"● Up to date: {installed}"
    if result.status is UpdateStatus.LOCAL_NEWER:
        return f"◌ Installed version is newer: {installed}"
    return "○ Update check failed"


def _server_status_text(status: ServerStatus) -> str:
    if status is ServerStatus.RUNNING:
        return "● Running"
    if status is ServerStatus.STARTING:
        return "◌ Starting…"
    if status is ServerStatus.STOPPING:
        return "◌ Stopping…"
    if status is ServerStatus.STOPPED:
        return "○ Stopped"
    return "◌ Unknown"


def _server_status_message(status: ServerStatus) -> str:
    if status is ServerStatus.RUNNING:
        return "ModelGlot server is running."
    if status is ServerStatus.STARTING:
        return "ModelGlot server is starting."
    if status is ServerStatus.STOPPING:
        return "ModelGlot server is stopping."
    if status is ServerStatus.STOPPED:
        return "ModelGlot server is stopped."
    return "ModelGlot server status is unknown."


def _create_icon() -> Image.Image:
    """Load the same branded artwork used by native desktop launchers."""

    with Image.open(BytesIO(app_icon_bytes(".png"))) as image:
        return image.convert("RGBA")


def launch(*, auto_started: bool = False) -> None:
    """Launch the supported native tray adapter."""

    launch_desktop(PystrayDesktopTray, auto_started=auto_started)
