"""Native tray update-check behavior."""

import threading
import time
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
        self.visible = False
        self.notify_error: Exception | None = None

    def run(self, setup=None) -> None:
        if setup is not None:
            setup(self)

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
    monkeypatch.setattr(desktop_tray, "confirm_update", lambda _latest: False)
    monkeypatch.setattr(desktop_tray, "launch_update", Mock())
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


def test_server_status_uses_native_success_style(tray):
    instance, icon = tray
    instance._controller = cast(
        Any,
        SimpleNamespace(status=ServerStatus.RUNNING),
    )

    instance._check_status(None, None)

    assert icon.notification_details[0].level is desktop_tray.NotificationLevel.SUCCESS
    assert instance._server_status_item.text == "● Running"
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
    assert icon.notifications == [
        ("Opening the Free Claude Code Admin UI…", "Free Claude Code")
    ]


def test_quit_menu_action_stops_desktop(tray):
    instance, icon = tray
    menu = instance._build_menu()
    quit_action = next(item for item in menu if item.text == "Quit")

    quit_action(icon)

    instance._controller.quit.assert_called_once_with()


def test_status_menu_action_updates_visible_status_row(tray):
    instance, icon = tray
    menu = instance._build_menu()
    status_action = next(item for item in menu if item.text == "Refresh Server Status")

    status_action(icon)

    assert instance._server_status_item.text == "● Running"
    assert instance._server_status_item.enabled is False
    assert icon.notifications == [("FCC server is running.", "Free Claude Code")]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ServerStatus.RUNNING, "● Running"),
        (ServerStatus.STARTING, "◌ Starting…"),
        (ServerStatus.STOPPING, "◌ Stopping…"),
        (ServerStatus.STOPPED, "○ Stopped"),
    ],
)
def test_server_status_text_reflects_each_lifecycle_state(status, expected):
    assert desktop_tray._server_status_text(status) == expected


def test_status_sync_updates_visible_status_row_when_state_changes(tray):
    instance, icon = tray
    controller = cast(
        Any,
        SimpleNamespace(status=ServerStatus.STOPPED),
    )
    instance._controller = controller

    instance._sync_server_status()
    assert instance._server_status_item.text == "○ Stopped"

    controller.status = ServerStatus.RUNNING
    instance._sync_server_status()

    assert instance._server_status_item.text == "● Running"
    assert icon.update_count == 2


def test_run_starts_status_watcher_and_reports_live_server_state(tray):
    instance, icon = tray
    instance._controller = cast(
        Any,
        SimpleNamespace(status=ServerStatus.RUNNING),
    )

    instance.run(lambda: None)

    deadline = time.monotonic() + 2
    while (
        instance._server_status_item.text != "● Running" and time.monotonic() < deadline
    ):
        time.sleep(0.01)

    assert instance._server_status_item.text == "● Running"
    assert icon.visible is True
    assert instance._status_thread is not None

    instance.stop()
    instance._status_thread.join(2)
    assert not instance._status_thread.is_alive()


def test_restart_menu_action_updates_visible_status_row(tray):
    instance, icon = tray
    menu = instance._build_menu()
    restart_action = next(item for item in menu if item.text == "Restart Server")

    restart_action(icon)
    assert instance._restart_thread is not None
    instance._restart_thread.join(2)

    assert instance._server_status_item.text == "● Running"
    assert instance._controller.restart_server.call_count == 1
    assert icon.notifications == [
        ("Restarting the FCC server…", "Free Claude Code"),
        ("Server restarted.", "Free Claude Code"),
    ]


def test_concurrent_restart_clicks_start_only_one_restart(tray):
    instance, _icon = tray
    entered = threading.Event()
    release = threading.Event()

    def restart() -> None:
        entered.set()
        release.wait(2)

    instance._controller = cast(
        Any,
        SimpleNamespace(
            status=ServerStatus.RUNNING,
            restart_server=Mock(side_effect=restart),
        ),
    )
    first = threading.Thread(target=instance._restart_server, args=(None, None))

    first.start()
    assert entered.wait(1)
    instance._restart_server(None, None)

    assert instance._restart_item.text == "Restarting Server…"
    assert instance._restart_item.enabled is False
    release.set()
    first.join(2)
    assert instance._restart_thread is not None
    instance._restart_thread.join(2)
    assert instance._controller.restart_server.call_count == 1


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
        assert instance._update_status_item.text == "◌ Checking…"
        assert instance._update_check_item.enabled is False
    finally:
        release.set()
    _wait_for_update(instance)

    assert instance._update_status_item.text == "● Up to date: 1.10.0"
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

    assert instance._update_status_item.text == "● Up to date: 1.10.0"
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
                message="FCC update available: 1.9.0 to 1.10.0.",
            ),
            "● Update available: 1.9.0 → 1.10.0",
            desktop_tray.NotificationLevel.INFO,
        ),
        (
            UpdateCheckResult(
                status=UpdateStatus.UP_TO_DATE,
                installed="1.10.0",
                latest="1.10.0",
                message="FCC 1.10.0 is already up to date.",
            ),
            "● Up to date: 1.10.0",
            desktop_tray.NotificationLevel.SUCCESS,
        ),
        (
            UpdateCheckResult(
                status=UpdateStatus.LOCAL_NEWER,
                installed="1.11.0",
                latest="1.10.0",
                message="FCC 1.11.0 is newer than the published version 1.10.0.",
            ),
            "◌ Installed version is newer: 1.11.0",
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
    assert icon.update_count == (3 if result.status is UpdateStatus.AVAILABLE else 2)


def test_available_update_prompts_and_declining_preserves_retry(tray, monkeypatch):
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="FCC update available: 1.9.0 to 1.10.0.",
    )
    confirm = Mock(return_value=False)
    launch = Mock()
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", confirm)
    monkeypatch.setattr(desktop_tray, "launch_update", launch)

    instance._check_updates(None, None)
    _wait_for_update(instance)

    confirm.assert_called_once_with("1.10.0")
    launch.assert_not_called()
    instance._controller.quit.assert_not_called()
    assert instance._update_check_item.enabled is True
    assert instance._update_status_item.text == "● Update available: 1.9.0 → 1.10.0"
    assert icon.notifications == [(result.message, "Free Claude Code")]


def test_accepted_update_launches_detected_release_and_restarts_desktop(
    tray, monkeypatch, tmp_path
):
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="FCC update available: 1.9.0 to 1.10.0.",
    )
    launch = Mock(return_value=tmp_path / "desktop-update.log")
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", lambda _latest: True)
    monkeypatch.setattr(desktop_tray, "launch_update", launch)

    instance._check_updates(None, None)
    _wait_for_update(instance)

    launch.assert_called_once_with("1.10.0")
    instance._controller.quit.assert_called_once_with()
    assert instance._update_check_item.enabled is False
    assert instance._update_status_item.text == "◌ Installing 1.10.0…"
    assert icon.notifications == [
        (result.message, "Free Claude Code"),
        (
            "Installing FCC 1.10.0. FCC will close and reopen when it finishes.",
            "Free Claude Code",
        ),
    ]


def test_stop_during_update_confirmation_does_not_launch_installer(tray, monkeypatch):
    instance, icon = tray
    entered = threading.Event()
    release = threading.Event()
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="FCC update available: 1.9.0 to 1.10.0.",
    )
    launch = Mock()

    def confirm(_latest: str) -> bool:
        entered.set()
        assert release.wait(2)
        return True

    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", confirm)
    monkeypatch.setattr(desktop_tray, "launch_update", launch)

    instance._check_updates(None, None)
    assert entered.wait(1)
    instance.stop()
    release.set()
    _wait_for_update(instance)

    launch.assert_not_called()
    instance._controller.quit.assert_not_called()
    assert icon.notifications == [(result.message, "Free Claude Code")]


def test_stop_before_result_notification_suppresses_notification_and_confirmation(
    tray, monkeypatch
):
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="FCC update available: 1.9.0 to 1.10.0.",
    )
    confirm = Mock()
    monkeypatch.setattr(desktop_tray, "confirm_update", confirm)
    monkeypatch.setattr(instance, "_refresh_menu", Mock(side_effect=instance.stop))

    instance._finish_update_check(result)

    confirm.assert_not_called()
    assert icon.notifications == []


def test_update_launch_failure_keeps_desktop_running_and_offers_retry(
    tray, monkeypatch
):
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="FCC update available: 1.9.0 to 1.10.0.",
    )
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", lambda _latest: True)
    monkeypatch.setattr(
        desktop_tray,
        "launch_update",
        Mock(side_effect=FileNotFoundError("fcc-update unavailable")),
    )

    instance._check_updates(None, None)
    _wait_for_update(instance)

    instance._controller.quit.assert_not_called()
    assert instance._update_check_item.enabled is True
    assert instance._update_status_item.text == "● Update available: 1.9.0 → 1.10.0"
    assert icon.notifications[-1] == (
        "Could not start the FCC update. Run fcc-update from a terminal.",
        "Free Claude Code",
    )
    assert icon.notification_details[-1].level is desktop_tray.NotificationLevel.ERROR


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

    assert instance._update_status_item.text == "○ Update check failed"
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
    assert instance._update_status_item.text == "● Up to date: 1.10.0"
    assert instance._update_check_item.enabled is True


def test_unexpected_update_check_error_does_not_escape_worker(tray, monkeypatch):
    instance, icon = tray

    def fail() -> UpdateCheckResult:
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(desktop_tray, "check_for_updates", fail)

    instance._check_updates(None, None)
    _wait_for_update(instance)

    assert instance._update_status_item.text == "○ Update check failed"
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

    assert instance._update_status_item.text == "○ Update check failed"
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


def test_tray_menu_exposes_compact_branded_status_and_actions(tray):
    instance, _icon = tray

    labels = [item.text for item in instance._build_menu()]

    assert labels == [
        "Free Claude Code",
        "● Running",
        instance._version_item.text,
        "- - - -",
        "Open Admin",
        "Refresh Server Status",
        "Check for Updates",
        "○ Not checked",
        "- - - -",
        "Restart Server",
        "- - - -",
        "Quit",
    ]
    assert instance._brand_item.enabled is False
    assert instance._server_status_item.enabled is False
    assert instance._version_item.enabled is False
    assert instance._update_check_item.enabled is True
    assert instance._update_status_item.enabled is False
    assert instance._restart_item.enabled is True


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
