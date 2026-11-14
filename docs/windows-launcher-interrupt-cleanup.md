# Windows Launcher Interrupt Cleanup

Status: resolved
Scope: `free-claude-code` at commit `efdfdbe1`
Audience: maintainers and contributors

This document records the Windows `Ctrl+C` cleanup bug affecting native client launchers, its root
cause, and the behavior now guaranteed by the launcher.

## Symptom

On Windows, exiting an interactive client with `Ctrl+C` could print a nested traceback:

```text
KeyboardInterrupt
During handling of the above exception, another exception occurred:
...
subprocess.run(["taskkill", "/PID", ..., "/T", "/F"])
...
KeyboardInterrupt
```

The nested exception interrupted `taskkill` while the launcher was already handling the first
`KeyboardInterrupt`. The local FCC proxy remained running, as intended by the launcher contract,
but the client cleanup was no longer guaranteed to finish.

## Reproduction

1. Start a native client on Windows, for example `uv run fcc-claude`.
2. At the Claude Code prompt, press `Ctrl+C` and then press it again when Claude Code displays
   `Press Ctrl-C again to exit`.
3. Observe the nested `KeyboardInterrupt` traceback on Windows.

The second press is relevant because Claude Code intentionally requires two presses to exit from an
idle prompt. Windows delivers console control events to the launcher and the client process, so the
launcher can receive the same interrupt that Claude Code is handling.

## Root Cause

`run_client_process` waited synchronously for the native client. The first `Ctrl+C` raised
`KeyboardInterrupt` from `Popen.wait()`. Its cleanup handler then started the Windows `taskkill`
process through `subprocess.run()`.

A second `Ctrl+C` interrupted `subprocess.run()` while it waited for `taskkill`. The Windows cleanup
helper caught `Exception`, but `KeyboardInterrupt` inherits directly from `BaseException` and was
therefore not caught. The second interrupt escaped the cleanup handler and replaced the normal
interruption path with a nested traceback. The original handler also re-raised the first
`KeyboardInterrupt`, so even a single interrupt produced an unclean launcher exit.

## Resolution

The launcher now treats `Ctrl+C` as a normal interrupted exit:

- the first interrupt is converted to exit code `130` without printing a Python traceback;
- additional interrupts are deferred while the client process tree is terminated and reaped;
- cleanup uses bounded waits and falls back to terminating the direct child process;
- the Windows `taskkill` helper absorbs an interrupt instead of allowing it to escape its
  best-effort contract;
- the client PID is still unregistered in all exit paths.

The FCC proxy server is unaffected and continues running after the native client exits.

## Regression Coverage

Focused tests cover:

- a first interrupt during `Popen.wait()`;
- a second interrupt during cleanup;
- restoration of the original `SIGINT` handler after cleanup;
- a `KeyboardInterrupt` raised by the Windows `taskkill` helper.

The affected tests live in `tests/cli/test_launcher_resources.py` and
`tests/cli/test_process_registry.py`.
