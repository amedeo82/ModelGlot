"""Native confirmation and detached stable-release updates for FCC Desktop."""

import base64
import ctypes
import importlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

_RELEASE_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_WINDOWS_IDYES = 6
_WINDOWS_YES_NO_QUESTION = 0x4 | 0x20 | 0x10000 | 0x40000
_PARENT_EXIT_TIMEOUT_SECONDS = 120


class _WindowsFunction(Protocol):
    argtypes: tuple[object, ...]
    restype: type[object]

    def __call__(self, *arguments: object) -> int: ...


class _MacOSApplication(Protocol):
    def activateIgnoringOtherApps_(self, activate: bool) -> None: ...


class _MacOSApplicationFactory(Protocol):
    def sharedApplication(self) -> _MacOSApplication: ...


class _MacOSAlert(Protocol):
    def setMessageText_(self, message: str) -> None: ...

    def setInformativeText_(self, message: str) -> None: ...

    def addButtonWithTitle_(self, title: str) -> None: ...

    def runModal(self) -> int: ...


class _MacOSAlertAllocator(Protocol):
    def init(self) -> _MacOSAlert: ...


class _MacOSAlertFactory(Protocol):
    def alloc(self) -> _MacOSAlertAllocator: ...


class _MacOSOperationQueue(Protocol):
    def addOperationWithBlock_(self, operation: Callable[[], None]) -> None: ...


class _MacOSOperationQueueFactory(Protocol):
    def mainQueue(self) -> _MacOSOperationQueue: ...


class _AppKit(Protocol):
    NSApplication: _MacOSApplicationFactory
    NSAlert: _MacOSAlertFactory
    NSAlertFirstButtonReturn: int
    NSOperationQueue: _MacOSOperationQueueFactory


def confirm_update(latest: str) -> bool:
    """Ask whether to install a validated release using a native modal dialog."""

    _validate_release(latest)
    message = (
        f"FCC {latest} is available. Install it now?\n\n"
        "FCC will close during the update and reopen when it finishes."
    )
    if sys.platform == "win32":
        return _windows_confirmation(message)
    if sys.platform == "darwin":
        return _macos_confirmation(message)
    raise RuntimeError("Desktop updates are supported only on Windows and macOS.")


def launch_update(latest: str, log_directory: Path) -> Path:
    """Launch a detached updater and return its output log path.

    The native helper waits for this desktop process to exit, delegates to the
    installed fcc-update command with the detected release pinned, and reopens
    FCC after either success or failure.
    """

    _validate_release(latest)
    update_command, desktop_command = _installed_commands()
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / (
        f"desktop-update-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}.log"
    )
    parent_pid = os.getpid()
    if sys.platform == "win32":
        command = _windows_update_command(
            latest, parent_pid, update_command, desktop_command
        )
        creationflags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        start_new_session = False
    elif sys.platform == "darwin":
        script = _macos_update_script(
            latest, parent_pid, update_command, desktop_command
        )
        command = _macos_helper_command(script)
        creationflags = 0
        start_new_session = True
    else:
        raise RuntimeError("Desktop updates are supported only on Windows and macOS.")

    try:
        with log_path.open("w", encoding="utf-8") as output:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
    except Exception:
        if sys.platform == "darwin":
            Path(command[1]).unlink(missing_ok=True)
        raise
    return log_path


def _validate_release(latest: str) -> None:
    if _RELEASE_PATTERN.fullmatch(latest) is None:
        raise ValueError("The update version must be a canonical stable release.")


def _installed_commands() -> tuple[str, str]:
    executable = Path(sys.argv[0]).expanduser()
    if not executable.is_file():
        discovered = shutil.which(sys.argv[0])
        if discovered is None:
            raise FileNotFoundError(
                "Could not locate the installed fcc-desktop command."
            )
        executable = Path(discovered)
    desktop = str(executable.absolute())
    update_name = "fcc-update.cmd" if sys.platform == "win32" else "fcc-update"
    candidates = (
        executable.with_name(update_name),
        Path(sys.executable).with_name(update_name),
    )
    update = next(
        (str(candidate.absolute()) for candidate in candidates if candidate.is_file()),
        shutil.which("fcc-update"),
    )
    if update is None:
        raise FileNotFoundError("Could not locate the installed fcc-update command.")
    return update, desktop


def _windows_confirmation(message: str) -> bool:
    user32: ctypes.CDLL = ctypes.WinDLL("user32", use_last_error=True)
    message_box = cast(_WindowsFunction, user32.MessageBoxW)
    message_box.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    )
    message_box.restype = ctypes.c_int
    response = message_box(
        None,
        message,
        "Free Claude Code update",
        _WINDOWS_YES_NO_QUESTION,
    )
    return response == _WINDOWS_IDYES


def _macos_confirmation(message: str) -> bool:
    appkit = cast(_AppKit, importlib.import_module("AppKit"))
    finished = threading.Event()
    result: list[bool] = []
    errors: list[BaseException] = []

    def show_dialog() -> None:
        try:
            appkit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            alert = appkit.NSAlert.alloc().init()
            alert.setMessageText_("Free Claude Code update")
            alert.setInformativeText_(message)
            alert.addButtonWithTitle_("Install")
            alert.addButtonWithTitle_("Cancel")
            first_button = (
                appkit.NSAlertFirstButtonReturn
                if hasattr(appkit, "NSAlertFirstButtonReturn")
                else 1000
            )
            result.append(alert.runModal() == first_button)
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    appkit.NSOperationQueue.mainQueue().addOperationWithBlock_(show_dialog)
    finished.wait()
    if errors:
        raise errors[0]
    return bool(result and result[0])


def _windows_update_command(
    latest: str,
    parent_pid: int,
    update_command: str,
    desktop_command: str,
) -> list[str]:
    update = _powershell_quote(update_command)
    desktop = _powershell_quote(desktop_command)
    script = f"""
$ErrorActionPreference = 'Stop'
$parentPid = {parent_pid}
$deadline = [DateTime]::UtcNow.AddSeconds({_PARENT_EXIT_TIMEOUT_SECONDS})
$updateStatus = 0
while (Get-Process -Id $parentPid -ErrorAction SilentlyContinue) {{
    if ([DateTime]::UtcNow -ge $deadline) {{
        Write-Error 'FCC did not close in time for the update.'
        $updateStatus = 1
        break
    }}
    Start-Sleep -Milliseconds 250
}}
if ($updateStatus -eq 0) {{
    try {{
        $env:FCC_INSTALL_VERSION = '{latest}'
        $env:FCC_INSTALL_REF = ''
        & {update}
        $updateStatus = $LASTEXITCODE
    }} catch {{
        Write-Error $_
        $updateStatus = 1
    }}
}}
try {{
    Start-Process -FilePath {desktop}
}} catch {{
    Write-Error $_
    if ($updateStatus -eq 0) {{ $updateStatus = 1 }}
}}
if ($updateStatus -ne 0) {{
    Add-Type -AssemblyName System.Windows.Forms
    [void] [System.Windows.Forms.MessageBox]::Show(
        'The FCC update could not be installed. FCC will reopen. Run fcc-update from a terminal for details.',
        'Free Claude Code update',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
}}
exit $updateStatus
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    powershell = shutil.which("powershell.exe") or "powershell.exe"
    return [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
        encoded,
    ]


def _macos_update_script(
    latest: str,
    parent_pid: int,
    update_command: str,
    desktop_command: str,
) -> str:
    app = shlex.quote(str(Path.home() / "Applications/Free Claude Code.app"))
    update = shlex.quote(update_command)
    desktop = shlex.quote(desktop_command)
    error_script = shlex.quote(
        'display dialog "The FCC update could not be completed and FCC could not '
        "reopen automatically. Open Free Claude Code from Applications or run "
        'fcc-update from Terminal for details." buttons {"OK"} '
        'default button "OK" with icon stop with title "Free Claude Code update"'
    )
    return f"""trap 'rm -f "$0"' EXIT
parent_pid={parent_pid}
deadline=$(( $(date +%s) + {_PARENT_EXIT_TIMEOUT_SECONDS} ))
update_status=0
while kill -0 "$parent_pid" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        printf '%s\n' 'FCC did not close in time for the update.' >&2
        update_status=1
        break
    fi
    sleep 0.25
done
if [ "$update_status" -eq 0 ]; then
    FCC_INSTALL_VERSION={shlex.quote(latest)} FCC_INSTALL_REF='' {update}
    update_status=$?
fi
if ! /usr/bin/open {app} >/dev/null 2>&1; then
    /usr/bin/nohup {desktop} >/dev/null 2>&1 &
    fallback_pid=$!
    sleep 0.25
    if ! kill -0 "$fallback_pid" 2>/dev/null; then
        printf '%s\n' 'FCC could not be reopened automatically.' >&2
        update_status=1
    fi
fi
if [ "$update_status" -ne 0 ]; then
    /usr/bin/osascript -e {error_script} >/dev/null 2>&1 || true
fi
exit "$update_status"
"""


def _macos_helper_command(script: str) -> list[str]:
    descriptor, name = tempfile.mkstemp(prefix="fcc-desktop-update-", suffix=".sh")
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(script)
    os.chmod(name, 0o700)
    return ["/bin/sh", name]


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
