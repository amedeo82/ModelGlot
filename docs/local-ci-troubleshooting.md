# Local CI and Playwright troubleshooting

Status: active runbook
Scope: local CI failures, especially Windows Playwright startup timeouts
Audience: contributors, maintainers, and coding agents

Use this guide before repeating a full diagnosis when a local test run fails. It records the known Windows parallel-startup failure, a fast triage procedure, and the point at which deeper investigation is required.

## Fast triage

Start from the failure text rather than rerunning the complete CI sequence:

| Symptom | First check | Likely interpretation |
|---|---|---|
| `Admin browser-test server did not start` | Run the failing E2E test with `-n 0` | Known local parallel-startup contention when it passes serially |
| `Admin browser-test server did not stop within 30s` | Check whether the preceding errors are startup timeouts | Teardown consequence of a server that never started |
| Several unrelated E2E tests fail during setup at the same time | Inspect the worker count and run with `-n 4` | Resource contention during parallel Admin server startup |
| One Playwright locator assertion fails | Rerun that test alone with `-n 0` | Treat as a potential UI timing flake until reproduced consistently |
| A focused non-browser test fails | Rerun that exact test | Do not apply the Playwright startup workaround to ordinary pytest failures |

On Windows, begin with:

```powershell
uv run --locked pytest e2e -n 4 -v --tb=short
```

If the failure remains, isolate the affected file or test:

```powershell
uv run --locked pytest e2e/test_admin_models.py -n 0 -v --tb=short
uv run --locked pytest "e2e/test_admin_models.py::test_name" -n 0 -v --tb=short
```

After a failed xdist run, prefer an explicit file or node ID over `--lf`; an interrupted xdist session may not have recorded every failure in pytest's last-failure cache.

## Known Windows parallel-startup failure

### Symptoms

The local CI-equivalent Playwright command can fail on Windows with a group of unrelated setup errors:

```text
TimeoutError: Admin browser-test server did not start
```

Typical evidence includes:

- pytest creates many workers, commonly `14/14 workers` on the affected workstation;
- numerous E2E tests fail during setup while unrelated tests pass;
- the failures cluster around the same startup window;
- the captured server log shows `Starting ModelGlot...`, followed by provider discovery or import work;
- rerunning the failed tests with `-n 0` passes;
- the complete E2E suite passes serially.

This pattern is an environment and parallelism failure, not evidence that every reported test has a separate regression. The test names are usually incidental because each test independently requests the function-scoped Admin server fixture.

### Mechanism

`pyproject.toml` enables pytest-xdist globally:

```toml
addopts = "-p e2e.thread_diagnostics -n auto --dist=worksteal"
```

The Windows four-worker cap in `tests/conftest.py` applies to the `tests/` subtree. It does not apply to the separate `e2e/` tree, so `pytest e2e` uses `-n auto` and may create one worker per logical CPU.

Every E2E test that needs the Admin UI starts an isolated Uvicorn server in a thread. The fixture waits only five seconds for `server.started`. Under high Windows worker concurrency, importing provider modules, loading the application, and performing provider discovery can exceed that startup budget. The fixture then reports `Admin browser-test server did not start`, even though the application can start normally with less contention.

The separate Playwright assertion timeout is ten seconds. It controls browser assertions and does not extend the five-second Admin server startup deadline.

The fixture teardown also has its own bounded shutdown budget. A teardown interruption after a startup timeout is not an independent root cause.

### Historical confirmation

On 2026-11-27, two local Windows runs failed with the same startup pattern while different unrelated E2E tests were reported as failed. The affected tests passed when rerun serially, and the complete suite passed with:

```powershell
uv run --locked pytest e2e -n 0 -v --tb=short
```

The result was `338 passed, 1 skipped`. These counts are historical evidence, not expected counts for later versions of the suite.

## Decision procedure

Use this sequence to avoid repeating the investigation:

1. Confirm that the errors are setup errors and contain `Admin browser-test server did not start`.
2. Confirm that pytest created the automatic worker pool rather than a deliberately constrained one.
3. Rerun the failing file or node with `-n 0`.
4. If it passes, run the E2E suite with `-n 4` to verify behavior under controlled parallelism.
5. If both pass, record the automatic-worker failure as local resource contention and continue with the non-Playwright checks.
6. If the test still fails serially, treat it as a real regression or fixture defect and inspect that test's assertion and captured logs.
7. If only a specific test fails repeatedly, investigate it independently rather than changing the global timeout.

Do not increase the server startup deadline merely to hide this known contention pattern. A timeout change requires evidence that the server cannot start within a reasonable budget under controlled parallelism.

## Local commands

The CI-equivalent local Playwright check is:

```powershell
.\scripts\ci.ps1 -Only playwright
```

It installs Chromium and runs the E2E suite with automatic xdist workers. For diagnosis, prefer an explicit worker count:

```powershell
uv run --locked pytest e2e -n 4 -v --tb=short
uv run --locked pytest e2e -n 0 -v --tb=short
```

The complete local CI sequence remains:

```powershell
.\scripts\ci.ps1
```

If only its Playwright stage fails with the known pattern, retain the passing output from the other stages and report both results explicitly.

## CI shard replay

GitHub Actions splits the Playwright suite into platform-specific shards. To replay a Windows shard, use the same split and group arguments shown in `.github/workflows/tests.yml`:

```powershell
uv run --locked pytest e2e -c pyproject.toml -v --tb=short `
  -o thread_dump_timeout=10 --durations=20 `
  --tracing=retain-on-failure --screenshot=only-on-failure `
  --full-page-screenshot --output=test-results `
  --splits 3 --group 1 --splitting-algorithm=least_duration
```

Change the group number to replay another shard. Add `-n 4` when the goal is a resource-controlled local run rather than an exact reproduction of the hosted runner.

## Artifacts and cleanup

Failed Playwright tests retain screenshots and traces under `test-results/`. Some local failure paths can also leave a generated `untracked/` directory at the repository root. Neither location is source code.

Before reviewing or committing the final diff:

```powershell
git status --short
```

Remove generated local artifacts after confirming that no test process is still using them. Do not stage `test-results/` or `untracked/` files.

## Escalation criteria

Investigate the implementation rather than classifying the failure as contention when any of these conditions apply:

- the failing test also fails with `-n 0`;
- the same focused test fails repeatedly in isolation;
- the failure is an assertion or application error rather than a fixture startup timeout;
- the change modifies the E2E fixture, runtime startup, provider imports, or shutdown behavior;
- a hosted CI shard fails with the same test consistently;
- the error occurs with one worker and does not mention the server startup deadline.

When the underlying mechanism changes, update this runbook in the same change so later contributors and agents can reuse the diagnosis instead of rediscovering it.
