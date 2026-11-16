# Desktop Branded Notifications Analysis

Status: partially implemented
Date: 2026-11-15; aligned with `custom/main` on 2026-11-16
Scope: `free-claude-code` on branch `custom/main`
Audience: maintainers and contributors

This document preserves the original analysis of desktop notification branding and records
which parts are now implemented. The Windows path is implemented; the macOS-specific
`UNUserNotificationCenter` backend and its authorization flow remain unimplemented.

The Windows implementation now uses the shared semantic notifier contract, a WinRT toast
backend with a branded Win32 balloon fallback, a stable application identity, and tray-owned
notification state. macOS still uses the portable `pystray` fallback. The design and open
decisions below therefore apply primarily to the remaining macOS work.

Related: [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the quality gate that any
implementation of this analysis must satisfy.

---

## 1. Executive Summary

FCC owns valid branded artwork for its desktop shell. The packaged PNG is 1024×1024, the
ICO contains frames from 16 through 256 pixels, and the macOS bundle uses the packaged
ICNS. The Windows installer exports the packaged assets to `%USERPROFILE%\.fcc` and assigns
the icon to the desktop and Start-menu shortcuts.

The current Windows implementation no longer sends notifications directly through
`pystray.Icon.notify()`:

- `src/free_claude_code/cli/desktop_notifications.py` defines the semantic
  `DesktopNotifier` contract, notification levels, and the portable fallback;
- `src/free_claude_code/cli/windows_desktop_notifications.py` implements WinRT toasts with
  the branded logo, a Win32 balloon fallback with `hBalloonIcon` and native severity flags,
  and registration of the stable application identity;
- `src/free_claude_code/cli/desktop_tray.py` owns notification state and maps server,
  version, update, and restart outcomes to semantic levels;
- the Windows installer writes the stable application identity to both shortcuts.

macOS still uses the portable `pystray` fallback. It does not yet use
`UNUserNotificationCenter`, does not request notification authorization explicitly, and
does not guarantee bundle-backed notification branding.

The mutable-`MenuItem` issue reported in the original analysis is resolved: the tray reads
dynamic text and enabled state through constructor callables and refreshes its FCC-owned
menu state. The remaining work is the macOS native backend and final platform-specific
acceptance coverage.

---

## 2. Method and Evidence

The analysis combined repository inspection, local execution, inspection of the
installed dependency source, and current vendor documentation.

### 2.1 Repository inspection

The following areas were inspected read-only:

- `src/free_claude_code/cli/desktop_tray.py`;
- `src/free_claude_code/cli/desktop_assets.py`;
- `src/free_claude_code/cli/desktop_entrypoint.py`;
- `src/free_claude_code/cli/macos_app.py`;
- `src/free_claude_code/updater/check.py`;
- `scripts/install.ps1`;
- `pyproject.toml`;
- `tests/cli/test_desktop_tray.py`;
- `tests/cli/test_desktop_assets.py`;
- `tests/cli/test_macos_app.py`;
- `tests/contracts/test_import_boundaries.py`;
- `CONTRIBUTING.md` and the existing analysis/implementation-plan document pairs.

### 2.2 Local verification snapshot

The verification was performed on 2026-11-15 against commit `c6455410` with the existing
uncommitted update-check changes.

| Check | Result |
| --- | --- |
| `uv run pytest tests/cli/test_desktop_tray.py tests/cli/test_update_check.py -q --tb=short` | 50 passed |
| `uv run ty check` | passed; 0 diagnostics |
| `Get-StartApps` | `Free Claude Code` maps to `C:\Users\...\ .local\bin\fcc-desktop.exe` |
| Installed executable version resources | no `FileDescription`, `ProductName`, or `CompanyName` |

The current checkout therefore has a green focused baseline. This does not invalidate the
previously reported 6-failure/9-pass snapshot; it means the mutable-`MenuItem` regression
was corrected in the working tree before this document was finalized.

### 2.3 Relationship to the reported failing baseline

The investigation that initiated this document reported a different local state:

- 6 failed and 9 passed tests;
- 6 `ty` diagnostics;
- assignments to `pystray.MenuItem.enabled` and `pystray.MenuItem.text` failing before
  the notification was reached.

That snapshot is not the current working tree. The current update-check implementation
already constructs the two dynamic items as follows:

- `src/free_claude_code/cli/desktop_tray.py:32` uses a callable for the update action's
  enabled state;
- `src/free_claude_code/cli/desktop_tray.py:37` uses a callable for the status label's
  text;
- `src/free_claude_code/cli/desktop_tray.py:86` and
  `src/free_claude_code/cli/desktop_tray.py:122` mutate FCC-owned state and then ask the
  backend to rebuild the menu.

The remaining implementation work therefore treats the immutable-`MenuItem` finding as a
regression that must be locked down with tests, not as a defect that still reproduces in
the current checkout.

### 2.4 Vendor and dependency sources reviewed

- Win32 notification structure and balloon flags:
  <https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw>
- Desktop toast AUMID registration:
  <https://learn.microsoft.com/en-us/windows/win32/shell/enable-desktop-toast-with-appusermodelid>
- Desktop toast quickstart:
  <https://learn.microsoft.com/en-us/windows/win32/shell/quickstart-sending-desktop-toast>
- Current Windows notification API guidance:
  <https://learn.microsoft.com/en-us/windows/apps/develop/notifications/>
- Apple UserNotifications framework:
  <https://developer.apple.com/documentation/usernotifications>
- Apple notification authorization:
  <https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications>
- Apple local notifications:
  <https://developer.apple.com/documentation/usernotifications/scheduling-a-notification-locally-from-your-app>
- `pystray` 0.19.5 reference:
  <https://pystray.readthedocs.io/en/latest/reference.html>
- `pystray` usage guidance:
  <https://pystray.readthedocs.io/en/latest/usage.html>

---

## 3. Original Baseline and Current Desktop Architecture

Sections 3.1 through 3.6 describe the baseline observed before the Windows notification
adapter was implemented. The current implementation is summarized as follows:

| Area | Current behavior |
| --- | --- |
| Shared contract | `DesktopNotifier`, `DesktopNotification`, and four semantic levels in `cli/desktop_notifications.py` |
| Windows primary path | WinRT toast with the packaged logo and stable application identity |
| Windows fallback path | Branded Win32 balloon, then the portable `pystray` fallback |
| macOS path | Portable `pystray` notification fallback; native UserNotifications not implemented |
| Tray integration | Server, version, update, restart, and shutdown outcomes use semantic levels |
| Dynamic menu state | `pystray.MenuItem` properties remain immutable and are read through callables |

### 3.1 Packaged assets

`src/free_claude_code/cli/desktop_assets.py:6` maps native suffixes to packaged assets:

| Suffix | Packaged file | Consumer |
| --- | --- | --- |
| `.png` | `app-icon.png` | `pystray` tray image and Windows toast image source |
| `.ico` | `app-icon.ico` | Windows shortcut and `HICON` loading |
| `.icns` | `app-icon.icns` | macOS application bundle |

`app_icon_bytes()` reads through `importlib.resources`, so the assets remain available
from an installed wheel. `export_app_icon()` writes the exact packaged bytes to an
installer-owned destination.

The contract tests verify the PNG dimensions, ICO directory header, and ICNS container
header at `tests/cli/test_desktop_assets.py:14`. The ICO test currently proves that it
contains at least eight frames; it does not assert the complete 16–256-pixel frame set.
The remaining implementation work should strengthen that assertion.

### 3.2 Tray and menu

`PystrayDesktopTray` creates a `pystray.Icon` with the branded PNG at
`src/free_claude_code/cli/desktop_tray.py:68`. The same PNG is loaded from package data
by `_create_icon()` at `src/free_claude_code/cli/desktop_tray.py:337`.

The menu currently contains:

- Open Admin;
- Check Server Status;
- Check for Updates;
- a dynamic update-status row;
- Restart Server;
- Quit.

Menu changes are performed by changing FCC-owned state and calling
`Icon.update_menu()`. On macOS, `_refresh_menu()` dispatches the rebuild to the main
queue at `src/free_claude_code/cli/desktop_tray.py:131`, which is required because
`pystray` creates native AppKit menu state. The current implementation uses the semantic
notifier contract and no longer calls `Icon.notify()` directly.

### 3.3 Original notification path

At the original baseline, the only notification calls in the desktop tray were:

- server status at `src/free_claude_code/cli/desktop_tray.py:74`;
- update result at `src/free_claude_code/cli/desktop_tray.py:118`.

Both delegate to `Icon.notify(message, title)`. The API has no parameter for an icon,
severity, identifier, activation data, or platform-specific native payload.

This made the original path text-only. It also coupled business events to `pystray`,
even though `pystray` is intended primarily as a tray/menu library and does not expose
the native notification features required by FCC.

### 3.4 Update-check integration state

The shipped update-check integration introduces a useful semantic boundary in
`src/free_claude_code/updater/check.py`:

- `UpdateStatus.AVAILABLE`;
- `UpdateStatus.UP_TO_DATE`;
- `UpdateStatus.LOCAL_NEWER`;
- `UpdateStatus.FAILED`.

`UpdateCheckResult` also separates the public `message` from diagnostic `detail`. The
tray currently uses the public message and logs the detail for failures. That separation
should be preserved when notifications are introduced.

The update check runs on a daemon worker thread. The worker updates state under an
`RLock`, refreshes the menu, and then emits the notification. Native notifier calls must
therefore be safe from a worker thread and must not block the tray event loop.

### 3.5 Windows installer and application identity

The Windows installer now:

1. exports the packaged ICO to `%USERPROFILE%\.fcc\app-icon.ico` at
   `scripts/install.ps1:1899`;
2. creates desktop and Start-menu shortcuts through
   `Install-FccDesktopShortcuts` at `scripts/install.ps1:2168`;
3. sets the shortcut target to `fcc-desktop.exe`;
4. sets the shortcut icon to the exported ICO;
5. writes the explicit `System.AppUserModel.ID` to the shortcuts at
   `scripts/install.ps1:2115`-`:2116` and `:2215`.

The shortcut is therefore visually branded and has the stable identity required by desktop
toasts. The Windows notifier uses the same AUMID when creating its toast notifier and when
setting the current-process identity.

The executable is produced by `uv` as a GUI-script launcher. Its PE resources are not an
FCC-owned packaging surface and may be replaced during upgrades. The implementation
therefore does not depend on embedding version resources into `fcc-desktop.exe`.

### 3.6 macOS bundle identity

The macOS bundle already establishes the required native identity:

- `BUNDLE_ID` is the stable FCC application bundle identifier declared in
  `src/free_claude_code/cli/macos_app.py:19`;
- `AppIcon.icns` is copied into `Contents/Resources` at
  `src/free_claude_code/cli/macos_app.py:99`;
- `CFBundleIdentifier` and `CFBundleIconFile` are written at
  `src/free_claude_code/cli/macos_app.py:108`;
- the bundle is ad-hoc signed at `src/free_claude_code/cli/macos_app.py:118`.

This is a stronger foundation than the current Windows identity. The notification backend
must, however, verify that the running process is launched from the FCC bundle. A raw
`fcc-desktop` process does not inherit the bundle identifier and cannot be assumed to
produce bundle-branded notifications.

---

## 4. Original Root Causes and Remaining Gaps

### 4.1 Original tray/notification coupling — resolved

At the original baseline, `PystrayDesktopTray` invoked `Icon.notify()` directly. The
current implementation instead depends on the semantic `DesktopNotifier` contract, allowing
the Windows adapter to select a native API and the macOS path to retain its portable
fallback.

### 4.2 Original Windows balloon gap — resolved

The Windows adapter now uses `NOTIFYICONDATAW` to provide:

- `hBalloonIcon` as the customized notification icon;
- `NIIF_USER` to select that customized icon;
- `NIIF_INFO`, `NIIF_WARNING`, and `NIIF_ERROR` for native notification styles;
- `NIIF_LARGE_ICON` for the large icon variant.

This behavior is implemented in `cli/windows_desktop_notifications.py` and is used as the
fallback when the WinRT toast path is unavailable.

### 4.3 Original Windows identity gap — resolved

The installer now writes the explicit FCC AUMID to the Start-menu shortcut, and the Windows
notification backend uses that same identity for `CreateToastNotifier(AUMID)` and
`SetCurrentProcessExplicitAppUserModelID(AUMID)`. The identity is no longer dependent on
the `uv` launcher path.

### 4.4 macOS does not use the native notification framework

The installed `pystray` 0.19.5 Darwin backend does implement `_notify()`. It shells out
to `osascript -e 'display notification ...'`. Therefore, the claim that macOS calls
necessarily terminate with `NotImplementedError` is not correct for the installed
dependency; the source contains a concrete `_notify()` implementation and no
`NotImplementedError` in that backend.

The real limitations of that path are different:

- it is not `UNUserNotificationCenter`;
- it does not use the FCC bundle identity or bundle icon;
- it introduces a subprocess for every notification;
- it inherits AppleScript display-notification behavior rather than FCC-controlled
  notification content;
- it does not provide FCC-controlled authorization-state handling.

Native macOS notifications remain the recommended implementation, but the migration
rationale must be based on branding, identity, and control rather than on an incorrect
`NotImplementedError` claim.

### 4.5 `pystray.MenuItem` is immutable

The installed `pystray` source documents `MenuItem` as immutable. Its `text`, `enabled`,
`visible`, `checked`, and similar attributes are properties calculated from constructor
arguments. Assignment to those properties is not supported.

The correct dynamic pattern is:

```python
MenuItem(
    lambda _item: current_label,
    action,
    enabled=lambda _item: current_enabled,
)
```

The current working tree follows this pattern for the update items. It must be protected
by regression tests because replacing the lambdas with direct assignments recreates the
reported pre-notification failure.

---

## 5. Platform Capability Assessment

| Capability | Windows current path | Windows native option | macOS current path | macOS native option |
| --- | --- | --- | --- | --- |
| Branded notification icon | Yes: WinRT logo or `hBalloonIcon` | Yes | No reliable FCC identity | Yes: bundle identity/icon |
| Stable application identity | Yes: explicit AUMID | Yes | Bundle only when launched from `.app` | Yes: bundle identifier |
| Informative severity | Exact with Win32 balloon; approximate with WinRT toast | Yes | No | Application-level mapping |
| Notification Center history | Yes through WinRT toast | Yes | Via `osascript` | Yes |
| Permission/policy handling | OS-managed plus notifier state | Yes | Implicit | Explicit `UNAuthorizationStatus` |
| Works without `pystray` | Yes for the notifier adapter | Yes | No for the portable fallback | Yes |
| Additional runtime dependency | WinRT projections on Windows | WinRT projections on Windows | Existing `pystray` stack | `pyobjc-framework-UserNotifications` |

### 5.1 Windows WinRT toast

A WinRT desktop toast can provide:

- a stable AUMID bound to the installed Start-menu shortcut;
- the shortcut's branded icon as the application logo;
- an optional local PNG override from `file:///...`;
- Notification Center history;
- Windows-managed sound and Focus Assist behavior.

The implementation uses the AUMID overload of `CreateToastNotifier`. The current
process also sets its explicit AUMID with
`SetCurrentProcessExplicitAppUserModelID` for consistent identity.

Microsoft's 2026 API guidance prefers `AppNotificationManager` for new unpackaged Win32
applications. That API is delivered through the native Windows App SDK and is not a
natural fit for a Python GUI-script launcher. For this project, WinRT
`Windows.UI.Notifications` remains the most practical native toast path; the
implementation includes a Win32 fallback rather than assuming the projection works in
every supported environment.

### 5.2 Windows Win32 balloon fallback

`NOTIFYICONDATAW` remains useful as a fallback because it:

- works without WinRT projection packages;
- supports FCC's exact icon;
- supports native `NIIF_INFO`, `NIIF_WARNING`, and `NIIF_ERROR` styles.

The dedicated adapter owns a small notification-anchor window and uses
`Shell_NotifyIcon(NIM_MODIFY, NIF_INFO)`. It does not depend on `pystray` private
attributes such as `_hwnd` or `_icon_handle`, because those are implementation details
of the installed backend.

The fallback is less modern than a toast and does not provide the same Notification
Center behavior. It should be a compatibility path, not the primary branding mechanism.

### 5.3 macOS UserNotifications

`UNUserNotificationCenter` supports local notifications through:

1. obtaining the shared notification center;
2. checking or requesting authorization;
3. creating `UNMutableNotificationContent`;
4. creating a `UNNotificationRequest`;
5. adding the request to the center.

Apple requires explicit user authorization for alerts, sound, or badge interactions. FCC
does not need badge behavior. It should request only `alert` and, if the product decision
requires it, `sound`.

The permission prompt should occur in context, such as when the user first selects
“Check Server Status” or “Check for Updates”, rather than automatically at application
startup. A denied or disabled notification setting must not break the tray action; the
menu status should still update and the failure should be logged without exposing
sensitive details.

---

## 6. Recommended Design

### 6.1 Separate the tray from notifications — implemented

The desktop CLI layer now owns this semantic notification contract:

```python
class NotificationLevel(Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class DesktopNotifier(Protocol):
    def notify(
        self,
        title: str,
        message: str,
        *,
        level: NotificationLevel = NotificationLevel.INFO,
    ) -> None: ...
```

The exact module layout should preserve import-boundary rules and avoid importing
Windows or macOS frameworks on the other platform.

Recommended responsibilities:

| Component | Responsibility |
| --- | --- |
| `desktop_tray.py` | tray/menu lifecycle and update-check orchestration |
| shared notification module | semantic levels, payloads, platform factory, fallback behavior |
| Windows adapter | AUMID, WinRT toast, Win32 balloon fallback, icon lifetime |
| macOS adapter | authorization, `UNUserNotificationCenter`, bundle identity validation |
| `desktop_assets.py` | packaged asset access and stable exported asset paths |

### 6.2 Keep `pystray` for the tray only — implemented for Windows

The current Windows path satisfies this contract:

- `Icon.notify()` is not called by production code;
- `Icon.HAS_NOTIFICATION` is not used as a platform capability gate;
- the tray receives a notifier through constructor injection;
- a no-op or logging-only notifier is used when native notifications cannot initialize;
- notification failure never prevents a menu refresh or terminates the tray.

This also avoids platform-specific notification behavior leaking into the update-check
business logic.

### 6.3 Preserve the update-check state model

`pystray.MenuItem` must remain immutable. FCC-owned state may change, but the items must
read that state through constructor callables.

The implementation should expose or test the following transitions:

| Event | Update action enabled | Status label |
| --- | --- | --- |
| initial | true | `Update status: not checked` |
| check running | false | `Update status: checking...` |
| check complete | true | result-specific label |

The current state machine already follows these transitions. Tests should assert them
without assigning to `MenuItem` properties.

### 6.4 Map semantic levels explicitly

Recommended application-level mapping:

| Event | Level |
| --- | --- |
| server status | `INFO` |
| update available | `INFO` |
| update already current | `SUCCESS` |
| installed version newer than published | `WARNING` |
| update check failed | `ERROR` |

The adapter owns the native rendering of each level. Not every platform exposes an exact
equivalent for every level. In particular:

- the Win32 fallback can render all four levels exactly;
- a WinRT toast has no direct success/warning/error severity field, so the adapter must
  use an approved textual or sound convention rather than inventing an unsupported API;
- macOS UserNotifications has no stock severity field, so warning/error semantics need an
  explicit, tested presentation convention.

### 6.5 Make Windows branding independent of the launcher executable

The Windows implementation must not rely on `fcc-desktop.exe` containing a branded PE
resource. Instead:

1. export the ICO to the installer-owned `.fcc` directory;
2. export a PNG for a toast logo override if the WinRT rendering requires it;
3. assign the ICO to the Start-menu shortcut;
4. write `System.AppUserModel.ID` to the Start-menu shortcut;
5. call `CreateToastNotifier(AUMID)` with that exact AUMID;
6. call `SetCurrentProcessExplicitAppUserModelID(AUMID)` at desktop startup.

The explicit shortcut identity remains correct if the `uv` tool launcher is replaced.

### 6.6 Make macOS bundle identity a precondition

The macOS native adapter should check `NSBundle.mainBundle().bundleIdentifier()` before
using the bundle-backed notification path. If the application is not running from the
FCC bundle, it should use an explicitly documented fallback or report that native
branding is unavailable. It must not silently claim bundle branding.

### 6.7 Treat authorization and OS policy as normal outcomes

Notification delivery can be denied or suppressed by the user, Focus Assist, quiet
hours, or application-notification policy. These are not exceptional program crashes.

The adapter should:

- expose an availability/authorization state for diagnostics;
- avoid repeated authorization prompts;
- log one clear warning per state transition;
- keep the tray action successful from the user's perspective even if the OS suppresses
  the banner.

---

## 7. Expected User Experience

After implementation:

1. The user launches FCC from the branded shortcut.
2. The tray icon remains branded on Windows and macOS.
3. Selecting “Check Server Status” or “Check for Updates” produces a native notification
   carrying the FCC application identity and icon.
4. Update failures are visibly distinguishable from ordinary status information.
5. On macOS, the first user-initiated notification action may request notification
   permission in context.
6. If notifications are denied or unavailable, the menu still updates and FCC remains
   fully usable.
7. On Windows, `Get-StartApps` identifies Free Claude Code by the explicit AUMID rather
   than only by the `uv` launcher path.
8. Reinstalling or upgrading FCC preserves the same Windows application identity and
   macOS bundle identifier.

---

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| WinRT toast is unavailable because the Start-menu AUMID is missing or stale | No toast is displayed | Make AUMID registration idempotent, verify it during installation, and retain the Win32 balloon fallback |
| WinRT projections are incompatible with a supported Python/runtime combination | Desktop startup or notifications fail | Isolate imports, run a compatibility spike before adoption, and lazy-load the backend with a tested fallback |
| Notification code blocks the tray or update worker | Frozen tray UI | Keep native calls bounded, dispatch off the tray event loop, and add timeout/failure tests |
| macOS authorization is denied | No banner is shown | Treat denial as a normal state, update the menu anyway, and expose the state in diagnostics |
| macOS runs outside the installed bundle | Incorrect or missing application icon | Verify the main bundle identifier and use a documented fallback |
| Direct `MenuItem` assignment is reintroduced | Update UI breaks before notification | Keep constructor callables and add regression tests for all state transitions |
| Notification titles or messages contain XML-sensitive characters | Malformed toast or injection into toast XML | Build XML with WinRT DOM APIs and set text nodes, never by string interpolation |
| Installer changes the launcher path | Windows identity appears to regress | Bind to an explicit AUMID rather than the executable path |
| Native dependencies increase package size or install complexity | Platform packaging regressions | Add platform markers, verify wheel contents, and run separate Windows/macOS packaging tests |
| `pystray` and native backends both attempt to own notification state | Duplicate or conflicting notifications | Remove production calls to `Icon.notify()` after the native adapter is active |
| Severity conventions differ across platforms | Inconsistent user meaning | Keep a semantic level in FCC and document the platform-specific rendering explicitly |

---

## 9. Success Criteria

The analysis is implemented successfully when:

- all branded desktop assets remain valid and packaged;
- the Windows shortcut carries the stable FCC AUMID;
- `Get-StartApps` resolves the registered Free Claude Code identity consistently;
- Windows notifications display the FCC icon through the primary native path;
- the Win32 balloon fallback displays the FCC icon and native severity flags;
- macOS bundle notifications use `UNUserNotificationCenter` and the FCC bundle identity;
- macOS notification authorization is requested only in a user-visible context;
- update and server-status notifications use semantic levels;
- the tray never calls `pystray.Icon.notify()` directly;
- notification failures never terminate the tray or discard menu state;
- `pystray.MenuItem` remains immutable in code and tests;
- the focused tests, `ruff`, `ty`, and the complete local CI sequence pass.

---

## 10. Open Decisions

The Windows decisions from the original analysis are implemented. The remaining maintainer
decisions are:

1. **macOS request timing.** Request authorization on the first user-initiated
   notification action, not at startup.
2. **macOS sound.** Request alert and sound authorization, but keep the initial
   implementation quiet unless audible update results are explicitly desired.
3. **Non-bundle macOS execution.** Retain the existing `pystray`/`osascript` behavior as
   an explicitly non-branded fallback only if tests show it remains reliable; otherwise
   report native notifications as unavailable outside the bundle.
4. **Executable version resources.** Do not modify the `uv` launcher; rely on AUMID,
   shortcut branding, and notification-owned icon data instead.
