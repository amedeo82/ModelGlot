"""Native tray update-check behavior."""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

from modelglot.cli.commands import ServerStatus
from modelglot.cli.desktop_notifications import DesktopIcon, DesktopNotifier
from modelglot.updater.check import UpdateCheckResult, UpdateStatus

if TYPE_CHECKING:
    from modelglot.cli import desktop_tray
else:
    desktop_tray = pytest.importorskip("modelglot.cli.desktop_tray")


class FakeIcon(DesktopIcon):
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.notification_details: list[desktop_tray.DesktopNotification] = []
        self.update_count = 0
        self.stopped = False
        self.visible = False
        self.notify_error: Exception | None = None

    def run(self, setup: Callable[[FakeIcon], None] | None = None) -> None:
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


class FakeController:
    def __init__(self, status: ServerStatus) -> None:
        self.status = status
        self.open_admin = Mock()
        self.restart_server = Mock()
        self.quit = Mock()


type TrayFixture = tuple[desktop_tray.PystrayDesktopTray, FakeIcon]


@pytest.fixture
def tray(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[desktop_tray.PystrayDesktopTray, FakeIcon]:
    icon = FakeIcon()

    class RecordingNotifier(DesktopNotifier):
        def notify(self, notification: desktop_tray.DesktopNotification) -> None:
            icon.notification_details.append(notification)
            if icon.notify_error is not None:
                raise icon.notify_error
            icon.notifications.append((notification.message, notification.title))

        def close(self) -> None:
            return None

    def create_icon() -> object:
        return object()

    def create_icon_instance(*_args: object, **_kwargs: object) -> FakeIcon:
        return icon

    def create_notifier(_icon: DesktopIcon) -> DesktopNotifier:
        return RecordingNotifier()

    def decline_update(_latest: str) -> bool:
        return False

    monkeypatch.setattr(desktop_tray, "_create_icon", create_icon)
    monkeypatch.setattr(desktop_tray, "Icon", create_icon_instance)
    monkeypatch.setattr(
        desktop_tray,
        "create_desktop_notifier",
        create_notifier,
    )
    monkeypatch.setattr(desktop_tray, "confirm_update", decline_update)
    monkeypatch.setattr(desktop_tray, "launch_update", Mock())
    controller = FakeController(ServerStatus.RUNNING)
    instance = desktop_tray.PystrayDesktopTray(
        cast(desktop_tray.DesktopController, controller)
    )
    return instance, icon


def _wait_for_update(tray: desktop_tray.PystrayDesktopTray) -> None:
    thread = tray._update_thread
    assert thread is not None
    thread.join(2)
    assert not thread.is_alive()


def test_server_status_uses_native_success_style(tray: TrayFixture) -> None:
    instance, icon = tray
    instance._controller = cast(
        desktop_tray.DesktopController,
        FakeController(ServerStatus.RUNNING),
    )

    instance._check_status(instance._icon, instance._server_status_item)

    assert icon.notification_details[0].level is desktop_tray.NotificationLevel.SUCCESS
    assert instance._server_status_item.text == "● Running"
    assert not instance._server_status_item.enabled


def test_stopped_server_uses_native_warning_style(tray: TrayFixture) -> None:
    instance, icon = tray
    instance._controller = cast(
        desktop_tray.DesktopController,
        FakeController(ServerStatus.STOPPED),
    )

    instance._check_status(instance._icon, instance._server_status_item)

    assert icon.notification_details[0].level is desktop_tray.NotificationLevel.WARNING


def test_open_admin_menu_action_opens_admin(tray: TrayFixture) -> None:
    instance, icon = tray
    menu = instance._build_menu()
    admin_action = next(item for item in menu if item.text == "Open Admin")

    admin_action(icon)

    cast(Mock, instance._controller.open_admin).assert_called_once_with()
    assert icon.notifications == [("Opening the ModelGlot Admin UI…", "ModelGlot")]


def test_quit_menu_action_stops_desktop(tray: TrayFixture) -> None:
    instance, icon = tray
    menu = instance._build_menu()
    quit_action = next(item for item in menu if item.text == "Quit")

    quit_action(icon)

    cast(Mock, instance._controller.quit).assert_called_once_with()


def test_status_menu_action_updates_visible_status_row(tray: TrayFixture) -> None:
    instance, icon = tray
    menu = instance._build_menu()
    status_action = next(item for item in menu if item.text == "Refresh Server Status")

    status_action(icon)

    assert instance._server_status_item.text == "● Running"
    assert not instance._server_status_item.enabled
    assert icon.notifications == [("ModelGlot server is running.", "ModelGlot")]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ServerStatus.RUNNING, "● Running"),
        (ServerStatus.STARTING, "◌ Starting…"),
        (ServerStatus.STOPPING, "◌ Stopping…"),
        (ServerStatus.STOPPED, "○ Stopped"),
    ],
)
def test_server_status_text_reflects_each_lifecycle_state(
    status: ServerStatus,
    expected: str,
) -> None:
    assert desktop_tray._server_status_text(status) == expected


def test_status_sync_updates_visible_status_row_when_state_changes(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    monkeypatch.setattr(desktop_tray.sys, "platform", "linux")
    controller = FakeController(ServerStatus.STOPPED)
    instance._controller = cast(desktop_tray.DesktopController, controller)

    instance._sync_server_status()
    assert instance._server_status_item.text == "○ Stopped"

    controller.status = ServerStatus.RUNNING
    instance._sync_server_status()

    assert instance._server_status_item.text == "● Running"
    assert icon.update_count == 2


def test_run_starts_status_watcher_and_reports_live_server_state(
    tray: TrayFixture,
) -> None:
    instance, icon = tray
    instance._controller = cast(
        desktop_tray.DesktopController,
        FakeController(ServerStatus.RUNNING),
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


def test_restart_menu_action_updates_visible_status_row(tray: TrayFixture) -> None:
    instance, icon = tray
    menu = instance._build_menu()
    restart_action = next(item for item in menu if item.text == "Restart Server")

    restart_action(icon)
    assert instance._restart_thread is not None
    instance._restart_thread.join(2)

    assert instance._server_status_item.text == "● Running"
    assert cast(Mock, instance._controller.restart_server).call_count == 1
    assert icon.notifications == [
        ("Restarting the ModelGlot server…", "ModelGlot"),
        ("Server restarted.", "ModelGlot"),
    ]


def test_concurrent_restart_clicks_start_only_one_restart(
    tray: TrayFixture,
) -> None:
    instance, _icon = tray
    entered = threading.Event()
    release = threading.Event()

    def restart() -> None:
        entered.set()
        release.wait(2)

    controller = FakeController(ServerStatus.RUNNING)
    controller.restart_server = Mock(side_effect=restart)
    instance._controller = cast(desktop_tray.DesktopController, controller)
    first = threading.Thread(
        target=instance._restart_server,
        args=(instance._icon, instance._server_status_item),
    )

    first.start()
    assert entered.wait(1)
    instance._restart_server(instance._icon, instance._server_status_item)

    assert instance._restart_item.text == "Restarting Server…"
    assert not instance._restart_item.enabled
    release.set()
    first.join(2)
    assert instance._restart_thread is not None
    instance._restart_thread.join(2)
    assert cast(Mock, instance._controller.restart_server).call_count == 1


def test_update_check_exposes_checking_state(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            message="ModelGlot 1.10.0 is already up to date.",
        )

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    try:
        instance._check_updates(instance._icon, instance._server_status_item)
        assert started.wait(1)
        assert instance._update_status_item.text == "◌ Checking…"
        assert not instance._update_check_item.enabled
    finally:
        release.set()
    _wait_for_update(instance)

    assert instance._update_status_item.text == "● Up to date: 1.10.0"
    assert instance._update_check_item.enabled is True


def test_notification_failure_does_not_break_update_result(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    icon.notify_error = RuntimeError("notification unavailable")
    result = UpdateCheckResult(
        status=UpdateStatus.UP_TO_DATE,
        installed="1.10.0",
        latest="1.10.0",
        message="ModelGlot 1.10.0 is already up to date.",
    )
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    assert instance._update_status_item.text == "● Up to date: 1.10.0"
    assert instance._update_check_item.enabled is True


def test_stop_during_update_check_suppresses_late_notification(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            message="ModelGlot 1.10.0 is already up to date.",
        )

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    try:
        instance._check_updates(instance._icon, instance._server_status_item)
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
                message="ModelGlot update available: 1.9.0 to 1.10.0.",
            ),
            "● Update available: 1.9.0 → 1.10.0",
            desktop_tray.NotificationLevel.INFO,
        ),
        (
            UpdateCheckResult(
                status=UpdateStatus.UP_TO_DATE,
                installed="1.10.0",
                latest="1.10.0",
                message="ModelGlot 1.10.0 is already up to date.",
            ),
            "● Up to date: 1.10.0",
            desktop_tray.NotificationLevel.SUCCESS,
        ),
        (
            UpdateCheckResult(
                status=UpdateStatus.LOCAL_NEWER,
                installed="1.11.0",
                latest="1.10.0",
                message="ModelGlot 1.11.0 is newer than the published version 1.10.0.",
            ),
            "◌ Installed version is newer: 1.11.0",
            desktop_tray.NotificationLevel.WARNING,
        ),
    ],
)
def test_update_check_publishes_result_in_menu_and_notification(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
    result: UpdateCheckResult,
    expected_status: str,
    expected_level: desktop_tray.NotificationLevel,
) -> None:
    instance, icon = tray
    # On macOS menu refreshes are dispatched to the AppKit main queue, which does
    # not run during this test; that path is covered by the dispatch test below.
    monkeypatch.setattr(desktop_tray.sys, "platform", "linux")
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    assert instance._update_status_item.text == expected_status
    assert not instance._update_status_item.enabled
    assert instance._update_check_item.enabled is True
    assert icon.notifications == [(result.message, "ModelGlot")]
    assert icon.notification_details[0].level is expected_level
    assert icon.update_count == (3 if result.status is UpdateStatus.AVAILABLE else 2)


def test_available_update_prompts_and_declining_preserves_retry(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="ModelGlot update available: 1.9.0 to 1.10.0.",
    )
    confirm = Mock(return_value=False)
    launch = Mock()
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", confirm)
    monkeypatch.setattr(desktop_tray, "launch_update", launch)

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    confirm.assert_called_once_with("1.10.0")
    launch.assert_not_called()
    cast(Mock, instance._controller.quit).assert_not_called()
    assert instance._update_check_item.enabled is True
    assert instance._update_status_item.text == "● Update available: 1.9.0 → 1.10.0"
    assert icon.notifications == [(result.message, "ModelGlot")]


def test_accepted_update_launches_detected_release_and_restarts_desktop(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="ModelGlot update available: 1.9.0 to 1.10.0.",
    )
    launch = Mock(return_value=tmp_path / "desktop-update.log")

    def accept_update(_latest: str) -> bool:
        return True

    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", accept_update)
    monkeypatch.setattr(desktop_tray, "launch_update", launch)
    monkeypatch.setattr(
        desktop_tray, "config_dir_path", lambda: tmp_path / ".modelglot"
    )

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    launch.assert_called_once_with("1.10.0", tmp_path / ".modelglot" / "logs")
    cast(Mock, instance._controller.quit).assert_called_once_with()
    assert not instance._update_check_item.enabled
    assert instance._update_status_item.text == "◌ Installing 1.10.0…"
    assert icon.notifications == [
        (result.message, "ModelGlot"),
        (
            "Installing ModelGlot 1.10.0. ModelGlot will close and reopen when it finishes.",
            "ModelGlot",
        ),
    ]


def test_stop_during_update_confirmation_does_not_launch_installer(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    entered = threading.Event()
    release = threading.Event()
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="ModelGlot update available: 1.9.0 to 1.10.0.",
    )
    launch = Mock()

    def confirm(_latest: str) -> bool:
        entered.set()
        assert release.wait(2)
        return True

    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", confirm)
    monkeypatch.setattr(desktop_tray, "launch_update", launch)

    instance._check_updates(instance._icon, instance._server_status_item)
    assert entered.wait(1)
    instance.stop()
    release.set()
    _wait_for_update(instance)

    launch.assert_not_called()
    cast(Mock, instance._controller.quit).assert_not_called()
    assert icon.notifications == [(result.message, "ModelGlot")]


def test_stop_before_result_notification_suppresses_notification_and_confirmation(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="ModelGlot update available: 1.9.0 to 1.10.0.",
    )
    confirm = Mock()
    monkeypatch.setattr(desktop_tray, "confirm_update", confirm)
    monkeypatch.setattr(instance, "_refresh_menu", Mock(side_effect=instance.stop))

    instance._finish_update_check(result)

    confirm.assert_not_called()
    assert icon.notifications == []


def test_update_launch_failure_keeps_desktop_running_and_offers_retry(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed="1.9.0",
        latest="1.10.0",
        message="ModelGlot update available: 1.9.0 to 1.10.0.",
    )

    def accept_update(_latest: str) -> bool:
        return True

    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)
    monkeypatch.setattr(desktop_tray, "confirm_update", accept_update)
    monkeypatch.setattr(
        desktop_tray,
        "launch_update",
        Mock(side_effect=FileNotFoundError("modelglot-update unavailable")),
    )

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    cast(Mock, instance._controller.quit).assert_not_called()
    assert instance._update_check_item.enabled is True
    assert instance._update_status_item.text == "● Update available: 1.9.0 → 1.10.0"
    assert icon.notifications[-1] == (
        "Could not start the ModelGlot update. Run modelglot-update from a terminal.",
        "ModelGlot",
    )
    assert icon.notification_details[-1].level is desktop_tray.NotificationLevel.ERROR


def test_failed_update_check_uses_generic_user_feedback(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    result = UpdateCheckResult(
        status=UpdateStatus.FAILED,
        installed="1.9.0",
        message="Could not check for ModelGlot updates. Please retry.",
        detail="Could not check for ModelGlot updates: timeout. Please retry.",
    )
    monkeypatch.setattr(desktop_tray, "check_for_updates", lambda: result)

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    assert instance._update_status_item.text == "○ Update check failed"
    assert icon.notifications == [
        ("Could not check for ModelGlot updates. Please retry.", "ModelGlot")
    ]


def test_failed_update_check_can_be_retried(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _icon = tray
    results = [
        UpdateCheckResult(
            status=UpdateStatus.FAILED,
            message="Could not check for ModelGlot updates. Please retry.",
        ),
        UpdateCheckResult(
            status=UpdateStatus.UP_TO_DATE,
            installed="1.10.0",
            latest="1.10.0",
            message="ModelGlot 1.10.0 is already up to date.",
        ),
    ]
    calls = 0

    def check() -> UpdateCheckResult:
        nonlocal calls
        result = results[calls]
        calls += 1
        return result

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)
    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    assert calls == 2
    assert instance._update_status_item.text == "● Up to date: 1.10.0"
    assert instance._update_check_item.enabled is True


def test_unexpected_update_check_error_does_not_escape_worker(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray

    def fail() -> UpdateCheckResult:
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(desktop_tray, "check_for_updates", fail)

    instance._check_updates(instance._icon, instance._server_status_item)
    _wait_for_update(instance)

    assert instance._update_status_item.text == "○ Update check failed"
    assert instance._update_check_item.enabled is True
    assert icon.notifications == [
        ("Could not check for ModelGlot updates. Please retry.", "ModelGlot")
    ]


def test_update_worker_start_failure_is_reported(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray

    class FailingThread:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("worker unavailable")

    monkeypatch.setattr(desktop_tray.threading, "Thread", FailingThread)

    instance._check_updates(instance._icon, instance._server_status_item)

    assert instance._update_status_item.text == "○ Update check failed"
    assert instance._update_check_item.enabled is True
    assert icon.notifications == [
        ("Could not check for ModelGlot updates. Please retry.", "ModelGlot")
    ]


def test_concurrent_update_clicks_start_only_one_check(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            message="ModelGlot 1.10.0 is already up to date.",
        )

    monkeypatch.setattr(desktop_tray, "check_for_updates", check)

    try:
        instance._check_updates(instance._icon, instance._server_status_item)
        assert started.wait(1)
        instance._check_updates(instance._icon, instance._server_status_item)
    finally:
        release.set()
    _wait_for_update(instance)

    assert calls == 1


def test_tray_menu_exposes_compact_branded_status_and_actions(
    tray: TrayFixture,
) -> None:
    instance, _icon = tray

    labels = [item.text for item in instance._build_menu()]

    assert labels == [
        "ModelGlot",
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
    assert not instance._brand_item.enabled
    assert not instance._server_status_item.enabled
    assert not instance._version_item.enabled
    assert instance._update_check_item.enabled is True
    assert not instance._update_status_item.enabled
    assert instance._restart_item.enabled is True


def test_macos_menu_refresh_is_dispatched_on_main_queue(
    tray: TrayFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, icon = tray
    scheduled: list[Callable[[], None]] = []

    class FakeQueue:
        def addOperationWithBlock_(self, operation: Callable[[], None]) -> None:
            scheduled.append(operation)

    appkit = SimpleNamespace(
        NSOperationQueue=SimpleNamespace(mainQueue=lambda: FakeQueue())
    )
    monkeypatch.setattr(desktop_tray.sys, "platform", "darwin")

    def import_module(_name: str) -> object:
        return appkit

    monkeypatch.setattr(
        desktop_tray.importlib,
        "import_module",
        import_module,
    )

    instance._refresh_menu()

    assert icon.update_count == 0
    assert len(scheduled) == 1
    scheduled[0]()
    assert icon.update_count == 1
