"""Native tray update-check behavior."""

import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import pytest

from free_claude_code.cli.commands import ServerStatus
from free_claude_code.updater.check import UpdateCheckResult, UpdateStatus

if TYPE_CHECKING:
    from free_claude_code.cli import desktop_tray
else:
    desktop_tray = pytest.importorskip("free_claude_code.cli.desktop_tray")


class FakeIcon:
    def __init__(self, *_args, **_kwargs) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.notification_details: list[desktop_tray.DesktopNotification] = []
        self.update_count = 0
        self.stopped = False
        self.notify_error: Exception | None = None

    def update_menu(self) -> None:
        self.update_count += 1

    def notify(self, message: str, title: str) -> None:
        if self.notify_error is not None:
            raise self.notify_error
        self.notifications.append((message, title))

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def tray(monkeypatch: pytest.MonkeyPatch):
    icon = FakeIcon()

    class RecordingNotifier:
        def notify(self, notification: desktop_tray.DesktopNotification) -> None:
            icon.notification_details.append(notification)
            if icon.notify_error is not None:
                raise icon.notify_error
            icon.notifications.append((notification.message, notification.title))

        def close(self) -> None:
            return None

    monkeypatch.setattr(desktop_tray, "_create_icon", lambda: object())
    monkeypatch.setattr(desktop_tray, "Icon", lambda *_args, **_kwargs: icon)
    monkeypatch.setattr(
        desktop_tray,
        "create_desktop_notifier",
        lambda _icon: RecordingNotifier(),
    )
    controller = cast(
        desktop_tray.DesktopController,
        SimpleNamespace(
            status=ServerStatus.RUNNING,
            open_admin=Mock(),
            restart_server=Mock(),
            quit=Mock(),
        ),
    )
    instance = desktop_tray.PystrayDesktopTray(controller)
    return instance, icon


def _wait_for_update(tray: desktop_tray.PystrayDesktopTray) -> None:
    thread = tray._update_thread
    assert thread is not None
    thread.join(2)
    assert not thread.is_alive()


def test_check_version_remains_available(tray, monkeypatch):
    instance, icon = tray
    monkeypatch.setattr(
        desktop_tray,
        "version_text",
        lambda: "Free Claude Code 1.2.3",
    )
    monkeypatch.setattr(desktop_tray, "package_version", lambda: "1.2.3")

    instance._check_version(None, None)

    assert icon.notifications == [("Free Claude Code 1.2.3", "Free Claude Code")]
    assert instance._version_item.text == "Installed version: 1.2.3"
    assert instance._version_item.enabled is False


def test_server_status_uses_native_success_style(tray):
    instance, icon = tray
    instance._controller = cast(
        Any,
        SimpleNamespace(status=ServerStatus.RUNNING),
    )

    instance._check_status(None, None)

    assert icon.notification_details[0].level is desktop_tray.NotificationLevel.SUCCESS
    assert instance._server_status_item.text == "Server status: Running"
    assert instance._server_status_item.enabled is False


def test_stopped_server_uses_native_warning_style(tray):
    instance, icon = tray
    instance._controller = cast(
        Any,
        SimpleNamespace(status=ServerStatus.STOPPED),
    )

    instance._check_status(None, None)

    assert icon.notification_details[0].level is desktop_tray.NotificationLevel.WARNING


def test_open_admin_menu_action_opens_admin(tray):
    instance, icon = tray
    menu = instance._build_menu()
    admin_action = next(item for item in menu if item.text == "Open Admin")

    admin_action(icon)

    instance._controller.open_admin.assert_called_once_with()


def test_quit_menu_action_stops_desktop(tray):
    instance, icon = tray
    menu = instance._build_menu()
    quit_action = next(item for item in menu if item.text == "Quit")

    quit_action(icon)

    instance._controller.quit.assert_called_once_with()


def test_status_menu_action_updates_visible_status_row(tray):
    instance, icon = tray
    menu = instance._build_menu()
    status_action = next(item for item in menu if item.text == "Check Server Status")

    status_action(icon)

    assert instance._server_status_item.text == "Server status: Running"
    assert instance._server_status_item.enabled is False
    assert icon.notifications == [("Server is Running.", "Free Claude Code")]


def test_restart_menu_action_updates_visible_status_row(tray):
    instance, icon = tray
    menu = instance._build_menu()
    restart_action = next(item for item in menu if item.text == "Restart Server")

    restart_action(icon)
    assert instance._restart_thread is not None
    instance._restart_thread.join(2)

    assert instance._server_status_item.text == "Server status: Running"
    assert instance._controller.restart_server.call_count == 1
    assert icon.notifications == [("Server restarted.", "Free Claude Code")]


def test_update_check_exposes_checking_state(tray, monkeypatch):
    instance, _icon = tray
    started = threading.Event()
    release = threading.Event()

    def check() -> UpdateCheckResult:
        started.set()
        assert release.wait(2)
        return UpdateCheckResult(
            status=UpdateStatus.UP_TO_DATE,
            installed="1.10.0",
            latest="1.10.0",
            message="FCC 1.10.0 is already up to date.",
        )

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    try:
        instance._check_updates(None, None)
        assert started.wait(1)
        assert instance._update_status_item.text == "Update status: checking..."
        assert instance._update_check_item.enabled is False
    finally:
        release.set()
    _wait_for_update(instance)

    assert instance._update_status_item.text == "Up to date: 1.10.0"
    assert instance._update_check_item.enabled is True


def test_notification_failure_does_not_break_update_result(tray, monkeypatch):
    instance, icon = tray
    icon.notify_error = RuntimeError("notification unavailable")
    result = UpdateCheckResult(
        status=UpdateStatus.UP_TO_DATE,
        installed="1.10.0",
        latest="1.10.0",
        message="FCC 1.10.0 is already up to date.",
    )
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)

    instance._check_updates(None, None)
    _wait_for_update(instance)

    assert instance._update_status_item.text == "Up to date: 1.10.0"
    assert instance._update_check_item.enabled is True


def test_stop_during_update_check_suppresses_late_notification(tray, monkeypatch):
    instance, icon = tray
    started = threading.Event()
    release = threading.Event()

    def check() -> UpdateCheckResult:
        started.set()
        assert release.wait(2)
        return UpdateCheckResult(
            status=UpdateStatus.UP_TO_DATE,
            installed="1.10.0",
            latest="1.10.0",
            message="FCC 1.10.0 is already up to date.",
        )

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    try:
        instance._check_updates(None, None)
        assert started.wait(1)
        instance.stop()
    finally:
        release.set()
    _wait_for_update(instance)

    assert icon.stopped is True
    assert icon.notifications == []


@pytest.mark.parametrize(
    ("result", "expected_status", "expected_level"),
    [
        (
            UpdateCheckResult(
                status=UpdateStatus.AVAILABLE,
                installed="1.9.0",
                latest="1.10.0",
                message="FCC update available: 1.9.0 -> 1.10.0.",
            ),
            "Update available: 1.9.0 -> 1.10.0",
            desktop_tray.NotificationLevel.INFO,
        ),
        (
            UpdateCheckResult(
                status=UpdateStatus.UP_TO_DATE,
                installed="1.10.0",
                latest="1.10.0",
                message="FCC 1.10.0 is already up to date.",
            ),
            "Up to date: 1.10.0",
            desktop_tray.NotificationLevel.SUCCESS,
        ),
        (
            UpdateCheckResult(
                status=UpdateStatus.LOCAL_NEWER,
                installed="1.11.0",
                latest="1.10.0",
                message="FCC 1.11.0 is newer than the published version 1.10.0.",
            ),
            "Installed version is newer: 1.11.0",
            desktop_tray.NotificationLevel.WARNING,
        ),
    ],
)
def test_update_check_publishes_result_in_menu_and_notification(
    tray, monkeypatch, result, expected_status, expected_level
):
    instance, icon = tray
    # On macOS menu refreshes are dispatched to the AppKit main queue, which does
    # not run during this test; that path is covered by the dispatch test below.
    monkeypatch.setattr(desktop_tray.sys, "platform", "linux")
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)

    instance._check_updates(None, None)
    _wait_for_update(instance)

    assert instance._update_status_item.text == expected_status
    assert instance._update_status_item.enabled is False
    assert instance._update_check_item.enabled is True
    assert icon.notifications == [(result.message, "Free Claude Code")]
    assert icon.notification_details[0].level is expected_level
    assert icon.update_count == 2


def test_failed_update_check_uses_generic_user_feedback(tray, monkeypatch):
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.FAILED,
        installed="1.9.0",
        message="Could not check for FCC updates. Please retry.",
        detail="Could not check for FCC updates: timeout. Please retry.",
    )
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)

    instance._check_updates(None, None)
    _wait_for_update(instance)

    assert instance._update_status_item.text == "Update status: check failed"
    assert icon.notifications == [
        ("Could not check for FCC updates. Please retry.", "Free Claude Code")
    ]


def test_failed_update_check_can_be_retried(tray, monkeypatch):
    instance, _icon = tray
    results = [
        UpdateCheckResult(
            status=UpdateStatus.FAILED,
            message="Could not check for FCC updates. Please retry.",
        ),
        UpdateCheckResult(
            status=UpdateStatus.UP_TO_DATE,
            installed="1.10.0",
            latest="1.10.0",
            message="FCC 1.10.0 is already up to date.",
        ),
    ]
    calls = 0

    def check() -> UpdateCheckResult:
        nonlocal calls
        result = results[calls]
        calls += 1
        return result

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    instance._check_updates(None, None)
    _wait_for_update(instance)
    instance._check_updates(None, None)
    _wait_for_update(instance)

    assert calls == 2
    assert instance._update_status_item.text == "Up to date: 1.10.0"
    assert instance._update_check_item.enabled is True


def test_unexpected_update_check_error_does_not_escape_worker(tray, monkeypatch):
    instance, icon = tray

    def fail() -> UpdateCheckResult:
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(desktop_tray, "check_for_updates", fail)

    instance._check_updates(None, None)
    _wait_for_update(instance)

    assert instance._update_status_item.text == "Update status: check failed"
    assert instance._update_check_item.enabled is True
    assert icon.notifications == [
        ("Could not check for FCC updates. Please retry.", "Free Claude Code")
    ]


def test_update_worker_start_failure_is_reported(tray, monkeypatch):
    instance, icon = tray

    class FailingThread:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("worker unavailable")

    monkeypatch.setattr(desktop_tray.threading, "Thread", FailingThread)

    instance._check_updates(None, None)

    assert instance._update_status_item.text == "Update status: check failed"
    assert instance._update_check_item.enabled is True
    assert icon.notifications == [
        ("Could not check for FCC updates. Please retry.", "Free Claude Code")
    ]


def test_concurrent_update_clicks_start_only_one_check(tray, monkeypatch):
    instance, _icon = tray
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def check() -> UpdateCheckResult:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return UpdateCheckResult(
            status=UpdateStatus.UP_TO_DATE,
            installed="1.10.0",
            latest="1.10.0",
            message="FCC 1.10.0 is already up to date.",
        )

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    try:
        instance._check_updates(None, None)
        assert started.wait(1)
        instance._check_updates(None, None)
    finally:
        release.set()
    _wait_for_update(instance)

    assert calls == 1


def test_tray_menu_exposes_visible_status_and_update_check(tray):
    instance, _icon = tray

    labels = [item.text for item in instance._build_menu()]

    assert "Check Server Status" in labels
    assert "Server status: unknown" in labels
    assert "Check Version" in labels
    assert sum(label.startswith("Installed version: ") for label in labels) == 1
    assert "Check for Updates" in labels
    assert "Update status: not checked" in labels
    assert "Test System Notification" not in labels
    assert instance._server_status_item.enabled is False
    assert instance._version_item.enabled is False
    assert instance._update_check_item.enabled is True
    assert instance._update_status_item.enabled is False


def test_macos_menu_refresh_is_dispatched_on_main_queue(tray, monkeypatch):
    instance, icon = tray
    scheduled: list = []

    class FakeQueue:
        def addOperationWithBlock_(self, operation) -> None:
            scheduled.append(operation)

    appkit = SimpleNamespace(
        NSOperationQueue=SimpleNamespace(mainQueue=lambda: FakeQueue())
    )
    monkeypatch.setattr(desktop_tray.sys, "platform", "darwin")
    monkeypatch.setattr(
        desktop_tray.importlib,
        "import_module",
        lambda name: appkit,
    )

    instance._refresh_menu()

    assert icon.update_count == 0
    assert len(scheduled) == 1
    scheduled[0]()
    assert icon.update_count == 1
