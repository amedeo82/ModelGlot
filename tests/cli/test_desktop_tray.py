"""Native tray menu contracts."""

from typing import Any, cast

import pytest


def _tray_module() -> Any:
    pytest.importorskip("pystray")
    pytest.importorskip("PIL")
    from free_claude_code.cli import desktop_tray

    return desktop_tray


class FakeIcon:
    """Record the notifications a tray action emits."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, message: str, title: str) -> None:
        self.notifications.append((message, title))


def test_tray_menu_exposes_version_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tray_module()
    monkeypatch.setattr(module, "version_text", lambda: "Free Claude Code 1.2.3")
    tray = module.PystrayDesktopTray.__new__(module.PystrayDesktopTray)
    tray._controller = cast(Any, object())

    labels = [item.text for item in tray._build_menu()]

    assert "Check Version" in labels


def test_check_version_notifies_installed_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _tray_module()
    monkeypatch.setattr(module, "version_text", lambda: "Free Claude Code 1.2.3")
    tray = module.PystrayDesktopTray.__new__(module.PystrayDesktopTray)
    icon = FakeIcon()
    tray._icon = cast(Any, icon)

    tray._check_version(cast(Any, None), cast(Any, None))

    assert icon.notifications == [("Free Claude Code 1.2.3", "Free Claude Code")]
