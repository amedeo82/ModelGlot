# Implementation Plan: Architecture Analysis Backlog

Status: proposed
Input: [`architecture-analysis.md`](architecture-analysis.md) (findings F-01 … F-12)
Audience: maintainers and contributors

This plan converts every finding of the architecture analysis into an ordered, reviewable
implementation step. Steps are grouped in waves; waves are sequenced, individual steps inside
a wave are independent and may run in parallel.

---

## 0. Ground Rules

These apply to every step in this plan.

1. **One finding focus per pull request.** Steps below propose one PR each, except where a
   step explicitly states that a single PR must cover several changes to stay coherent.
2. **PR title prefixes are mandatory** for any change touching `assets/`, `scripts/`, `src/`,
   `pyproject.toml`, or `uv.lock`: exactly one of `patch: `, `minor: `, `major: ` followed by
   a description (`CONTRIBUTING.md:15`). Behavioral and packaging changes use `minor: `.
3. **CI/local parity.** Any new local check must be mirrored in `scripts/ci.sh`,
   `scripts/ci.ps1`, and `.github/workflows/tests.yml`, and the parity itself must be covered
   by `tests/scripts/test_ci_scripts.py`.
4. **No suppression shortcuts.** `# type: ignore`, `# ty: ignore`, and
   `from __future__ import annotations` remain banned (`CONTRIBUTING.md:54`).
5. **Tests accompany behavior.** Every step lists the tests it adds. New behavior requires
   focused tests plus edge cases, not only modified existing tests.
6. **Documentation ships with code.** README/CONTRIBUTING updates go in the same PR as the
   code they describe. A standalone documentation PR is reserved for the repository owner
   (`CONTRIBUTING.md:7`): the two documents in `docs/` therefore land bundled with the first
   code PR of Wave 1 (step S1.1), or as an owner-approved documentation PR.
7. **Contract invariants hold.** New modules must respect the import boundaries asserted by
   `tests/contracts/test_import_boundaries.py` and, where a feature is added, declare a test
   owner in the feature manifest (`tests/contracts/test_feature_manifest.py:28`).
8. **No version edits.** Versions are computed and published by the release pipeline
   (`CONTRIBUTING.md:17`); steps never touch version strings.

Effort estimates are rough developer-days for a contributor already familiar with the
codebase.

---

## Wave 0 — Baseline (before any behavior change)

### S0.1 — Measure the current state

**Goal.** Establish objective baselines so later steps can prove improvement.

**Changes.** No source change. Run and record in `docs/implementation-plan.md` (or a
companion table):

- `uv run pytest --cov=src/free_claude_code --cov-report=term-missing --cov-report=xml`
  → total coverage and the per-module table for the uncovered modules listed in F-02;
- `uv run pytest --durations=25` → slowest tests (input for the sharding review);
- `uv run ruff check --statistics` and `uv run ty check` → current warning counts;
- `uv pip list --outdated` / `uv lock --upgrade --dry-run` → dependency drift.

**Acceptance.** The coverage number is recorded and becomes the initial `fail_under` in S1.2.
If the total is already high, S1.2 still proceeds: the point is the *measurement*, not the
number.

**Effort.** 0.5 day.

---

## Wave 1 — Security and measurability (priority: highest)

### S1.1 — Fail-closed server binding and authentication default

**Finding.** F-01 (Critical). **Risk addressed.** Unauthenticated network exposure of the
generation API on default installations.

**Design decision to make first.** Two candidate semantics:

- *Option A (recommended):* `HOST` defaults to `127.0.0.1`; the server refuses to start when
  the effective host is not loopback and `PROXY_AUTH_ENABLED` is false, unless an explicit
  opt-out is set.
- *Option B:* keep `0.0.0.0` but always require authentication when the host is not loopback.

Option A is preferred because it is safe by default and still allows deliberate LAN exposure
through explicit configuration.

**Changes.**

- `src/free_claude_code/config/settings.py:734` — change the `host` default to `127.0.0.1`.
- `src/free_claude_code/config/settings.py:737`–`:744` — add a model validator that rejects
  the combination "non-loopback host + authentication disabled" unless
  `FCC_ALLOW_UNAUTHENTICATED_BINDING=1` is present; reject a default token (`freecc`) when
  authentication is enabled unless the operator explicitly accepts it
  (e.g. `FCC_ALLOW_DEFAULT_AUTH_TOKEN=1`).
- `src/free_claude_code/cli/commands.py:332`–`:339` — log the effective exposure at startup:
  bind address, whether authentication is enabled, and a warning when the port is reachable
  from non-loopback interfaces.
- `src/free_claude_code/cli/doctor.py` — extend the diagnostic output with the same three
  facts so `fcc-doctor` can surface an insecure setup.
- `src/free_claude_code/config/paths.py` / `config/loader.py` — no change expected; only
  register the new settings if they are not already covered by the managed-config schema.
- `README.md` — new "Network exposure and authentication" section stating the defaults, the
  refusal behavior, and how to opt out.

**Tests.**

- `tests/config/test_config.py` (extend) or new `tests/config/test_server_binding.py`:
  - default settings expose `127.0.0.1`;
  - `HOST=0.0.0.0` with `PROXY_AUTH_ENABLED=false` raises a configuration error;
  - the same combination succeeds with the explicit opt-out;
  - `HOST=127.0.0.1` with authentication disabled is valid;
  - IPv6 loopback (`::1`) is recognized as loopback;
  - `HOST=192.168.1.10` with authentication enabled and a non-default token is valid;
  - the default token with authentication enabled is rejected unless explicitly accepted.
- `tests/cli/` — doctor output includes the exposure summary.

**Acceptance.**

- A fresh install cannot serve `/v1/messages` from another machine without an explicit,
  documented configuration change.
- The failure is a clear configuration error, not a silent bind.
- `fcc-doctor` reports the effective exposure.
- README documents the contract.

**Risks.** Existing users who rely on LAN exposure will see a startup error. Mitigation: the
error message names the exact environment variables to set, and the change ships as `minor:`
with a release-note entry.

**PR title.** `minor: Bind the proxy to loopback by default and refuse unauthenticated non-loopback exposure`

**Effort.** 1.5 days.

---

### S1.2 — Coverage measurement and ratcheting gate

**Finding.** F-02 (High).

**Changes.**

- `pyproject.toml` — add:
  ```toml
  [tool.coverage.run]
  source = ["src/free_claude_code"]
  branch = true
  omit = [
    "*/admin_static/*",
    "*/sqlite_migrations/*",
    "*/version.py",
  ]

  [tool.coverage.report]
  show_missing = true
  skip_covered = true
  fail_under = <value from S0.1>
  exclude_also = [
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "\\.\\.\\.",
  ]
  ```
- `scripts/ci.sh` — add a `coverage` check id after `pytest`:
  `uv run pytest --cov=src/free_claude_code --cov-report=term-missing --cov-report=xml`.
  Update `CHECK_ORDER` (`:4`), the usage text (`:18`–`:26`), `valid_check_id` (`:73`),
  and `run_check` (`:173`–`:188`).
- `scripts/ci.ps1` — mirror the same check id and command; update the id list (`:19`–`:20`),
  usage text, and dispatch table (`:195`).
- `.github/workflows/tests.yml` — add a `coverage` job on Linux (single run, not sharded:
  coverage needs a whole-suite measurement) that uploads `coverage.xml` as an artifact and
  fails when the total drops below `fail_under`.
- `tests/scripts/test_ci_scripts.py` — update the assertions that pin `CHECK_ORDER`
  (`:65`), the PowerShell id list (`:117`, `:227`), and add a case asserting the new
  `coverage` command in both scripts.
- `docs/implementation-plan.md` — record the baseline and the ratchet schedule.

**Tests.** The script-parity tests above; a coverage smoke assertion that
`uv run pytest --cov ... --cov-report=xml` produces `coverage.xml`.

**Acceptance.**

- `pytest-cov` is actually exercised on every CI run and locally.
- A deliberate uncovered branch lowers the total and fails the gate.
- The `fail_under` value is raised in a follow-up commit each time the total improves
  (ratchet: never lower the threshold).

**Follow-up (inside the same wave).** Add direct unit tests for the modules identified as
uncovered in F-02, in this priority order: `messaging/trees/transaction.py`,
`messaging/safe_diagnostics.py`, `api/admin_security.py`, `api/admin_cache.py`,
`providers/endpoint.py`, `providers/openai_client.py`, `messaging/cli_event_constants.py`.
Suggested new files: `tests/messaging/test_tree_transaction.py`,
`tests/messaging/test_safe_diagnostics.py`, `tests/api/test_admin_security.py`,
`tests/providers/test_endpoint.py`.

**Risks.** Coverage can slow the suite: mitigate by measuring only `src/` with `branch = true`
and excluding static assets and migrations; keep the coverage job on one OS to avoid
tripling runtime.

**PR title.** `patch: Measure and gate test coverage in CI and local check scripts`

**Effort.** 1.5 days (0.5 gate + 1.0 targeted tests).

---

### S1.3 — Dependency and static analysis gates

**Finding.** F-03 (High).

**Changes.**

- `.github/workflows/tests.yml` — new job `security`:
  - dependency vulnerability scan: `uvx pip-audit` (or `uvx osv-scanner`) against
    `uv.lock`, failing the PR on high/critical findings;
  - static analysis: `uvx bandit -r src/free_claude_code -c pyproject.toml` with a
    configuration that matches the project's intentional patterns (FastAPI `Depends`,
    binding to `0.0.0.0` after S1.1, subprocess usage in the CLI layer);
  - optional: GitHub CodeQL for Python on the same workflow.
- `.github/dependabot.yml` — new file: weekly `pip`/uv ecosystem updates for
  `uv.lock`, plus `github-actions` updates.
- `.github/workflows/post-merge.yml` — generate an SBOM during publish and attach it to the
  GitHub Release (e.g. `uvx cyclonedx-py` or an equivalent pinned tool).
- `pyproject.toml` — optional `[tool.bandit]` configuration for the accepted exceptions.

**Tests.** The workflow itself is the test: run it once on a branch that intentionally
introduces a known-vulnerable pin to confirm it fails, then revert.

**Acceptance.** A PR that introduces a known-vulnerable dependency fails the `security` job;
the scan runs on every PR; the SBOM is attached to releases.

**Risks.** Third-party scanners can be noisy; pin their versions with `uvx <tool>@<version>`
and configure an explicit allowlist with a comment explaining each entry.

**PR title.** `patch: Add dependency vulnerability scanning, SAST, and release SBOM`

**Effort.** 1 day.

---

### S1.4 — Relax the Python floor to a compatible range

**Finding.** F-04 (High).

**Changes.**

- `pyproject.toml:12` — `requires-python = ">=3.14,<3.15"`.
- `uv.lock` — regenerate (`uv lock`) so `requires-python` matches;
  `tests/contracts/test_uv_policy.py:88`–`:92` asserts this equality and must stay green.
- `scripts/install.sh:1773` and `scripts/install.ps1:2090` — verify the parsing of
  `requires-python` still selects a valid interpreter; add a regression test if the parsing
  assumes an exact pin.
- `.github/workflows/tests.yml` — keep the pinned interpreter for the primary matrix and add
  a secondary job on the latest 3.14.x to catch regressions early.
- `README.md:11` — badge text unchanged (`3.14`), no change required; verify.

**Tests.** Extend `tests/contracts/test_uv_policy.py` with a case asserting the declared
range is not an exact patch pin and that the lock mirrors it.

**Acceptance.** `pip install free-claude-code` succeeds on 3.14.x other than 3.14.10;
`uv lock --check` passes; installers still resolve an interpreter.

**Risks.** Low. Widening the range may surface interpreter differences; the extra CI job
contains that risk.

**PR title.** `minor: Support the full Python 3.14 patch range`

**Effort.** 0.5 day.

---

### S1.5 — Security documentation and environment reference

**Finding.** F-01, F-11.

**Changes.**

- New `SECURITY.md` at the repository root: supported versions, exposure model
  (loopback default, authentication, Admin isolation), how to report a vulnerability, and
  the non-supported usage of the proxy as an internet-facing service.
- `README.md` — complete environment-variable reference table (name, default, effect,
  sensitive or not), generated from the `Settings` model where practical, plus the
  "Network exposure and authentication" section introduced in S1.1.
- `docs/architecture-analysis.md` and `docs/implementation-plan.md` land with this step or
  with S1.1, per Ground Rule 6.

**Acceptance.** A user can answer "is my proxy reachable from the network?" by reading the
README alone.

**Effort.** 1 day.

---

## Wave 2 — Structural debt reduction (priority: medium)

### S2.1 — Characterization tests before refactoring

**Goal.** Enable safe refactoring of the largest modules.

**Changes.** New test files, no production change:

- `tests/providers/test_openai_chat_transport_contract.py` — covers stream creation
  (`providers/openai_chat/transport.py:634`), retry corrections (`:826`), and per-protocol
  routing (`:890`–`:1000`).
- `tests/providers/test_admission_contract.py` — covers backoff bounds, `Retry-After`
  parsing, half-open probe election, and credential isolation
  (`providers/admission.py:485`, `:605`, `:1119`).
- `tests/core/test_history_replay_contract.py` — covers reasoning replay and history
  negotiation (`core/history_replay.py`).
- `tests/application/test_code_sessions_contract.py` — covers the session lifecycle
  (`application/code_sessions/service.py`).

**Acceptance.** The new tests fail if a behavior in the corresponding module changes
(deliberately mutating a constant in a scratch branch is the recommended verification).

**Effort.** 2 days.

---

### S2.2 — Split `providers/openai_chat/transport.py`

**Finding.** F-05. Target: 1 585 lines → modules under 600 lines each.

**Proposed layout.**

- `providers/openai_chat/transport/__init__.py` — public surface re-exports.
- `providers/openai_chat/transport/request.py` — request building and body policy.
- `providers/openai_chat/transport/stream.py` — stream creation and lifecycle.
- `providers/openai_chat/transport/retry.py` — retry corrections (`:826`–`:888`).
- `providers/openai_chat/transport/output.py` — the Chat presenter (`:182`–`:430`).
- `providers/openai_chat/transport/protocols.py` — the per-protocol branches (`:890`–`:1000`).

**Constraints.** No public import path may change; the existing tests import from the
package, so keep `providers.openai_chat.transport` importable as before. `core/` must not
import provider internals (`CONTRIBUTING.md:60`).

**Acceptance.** All tests green, module sizes reduced, no new `except Exception`, and the
import-boundary contract test still passes.

**PR title.** `patch: Split the OpenAI Chat transport into focused modules`

**Effort.** 3 days.

---

### S2.3 — Split `providers/admission.py`

**Finding.** F-05. Target: 1 149 lines → four modules.

- `providers/admission/controller.py` — `ProviderAdmissionController` orchestration.
- `providers/admission/episode.py` — recovery episode state and half-open probe election.
- `providers/admission/backoff.py` — backoff computation and `Retry-After` parsing.
- `providers/admission/state.py` — `ProviderExecutionState`, `ProviderFailureDecision`.

**Acceptance.** Behavior identical; the admission contract tests from S2.1 pass unchanged.

**Effort.** 2 days.

---

### S2.4 — Split `application/code_sessions/service.py` and `core/history_replay.py`

**Finding.** F-05.

- `application/code_sessions/service.py` (1 194 lines, 66 functions) →
  `service.py` (orchestration), `lifecycle.py`, `permissions.py`, `events.py`.
- `core/history_replay.py` (1 325 lines) → `history_replay/__init__.py`,
  `replay.py`, `negotiation.py`, `opaque.py`.

**Acceptance.** Module sizes under 600 lines; contract tests from S2.1 unchanged.

**Effort.** 3 days.

---

### S2.5 — Unify the HTTP transport error taxonomy

**Finding.** F-06.

**Design.** Introduce a small adapter layer, e.g. `providers/transport/`, that wraps the
HTTP client used by the provider and exposes one exception vocabulary:

- `TransportTimeout`, `TransportNetworkError`, `TransportProtocolError`,
  `TransportStatusError` — mapped from `httpx`, `httpx2`, `aiohttp`, and `requests`.

**Changes.**

- New `providers/transport/errors.py`, `providers/transport/base.py`.
- `providers/failure_policy.py:12`–`:13`, `:276`–`:278` — classify on the new vocabulary.
- `providers/runtime/discovery.py:62`–`:94` — same.
- `providers/openai_client.py`, `providers/openai_chat/client.py`,
  `providers/github_copilot/provider.py` — wrap their clients with the adapter.
- Migration order (one PR per provider family, each independently revertible):
  1. OpenAI Chat/Responses and custom providers (largest usage);
  2. Anthropic Messages transport and passthrough;
  3. Vertex, Gemini, Copilot, Codex, remaining vendor clients.

**Acceptance.** No provider module imports two different HTTP client libraries for the same
concern; `providers/failure_policy.py` no longer needs to know the concrete client library;
the failure-policy test suite (`tests/providers/test_failure_policy.py`) is extended with
one case per transport error type.

**Risks.** Retry classification changes are the dangerous part: the mapping must preserve the
current retryable/non-retryable matrix exactly, verified by the existing policy tests before
any provider migration.

**Effort.** 5 days (1 design + 4 migration).

---

### S2.6 — Ban broad exception handling in the failure-sensitive paths

**Finding.** F-07.

**Changes.**

- `pyproject.toml` — enable ruff's `BLE` rule set; where a broad catch is genuinely needed,
  require an explicit `# noqa: BLE001` plus a reason, and keep the existing
  "no suppressions" ban limited to type-checker suppressions so this does not conflict.
- Migrate the hotspots: `application/code_sessions/service.py` (13),
  `providers/github_copilot/sdk.py` (11), `messaging/workflow.py` (7),
  `providers/openai_chat/transport.py` (3), `runtime/provider_manager.py` (4).
  Each broad catch becomes either a typed `ExecutionFailure` (`core/failures.py:23`) or a
  narrow exception tuple.
- `providers/transport` (from S2.5) becomes the canonical place for transport error mapping,
  removing many of the generic catches.

**Acceptance.** `ruff check` fails on a newly introduced broad catch; the migrated modules
contain no unqualified `except Exception`; failure classification tests cover the new
typed failures.

**Effort.** 3 days.

---

### S2.7 — Declarative vendor profiles

**Finding.** F-08.

**Changes.**

- Convert `providers/openai_chat/profiles.py` (874 lines) into declarative profile objects
  (dataclass or typed dict) describing per-vendor capabilities, extra body fields, reasoning
  quirks, and token limits, plus a registry.
- The transport reads a profile instead of branching on vendor names; the existing vendor
  branches are removed only after the profile-driven path reproduces their behavior.
- `core/openai_responses/tool_adaptation.py` (759 lines) follows the same treatment for
  tool adaptation rules.
- Add a contract test asserting that every registered profile declares the mandatory fields
  and that the set of supported vendors matches the provider catalog
  (`config/provider_catalog.py:146`).

**Acceptance.** Adding a vendor no longer requires editing the shared transport; the
contract test fails for an incomplete profile.

**Effort.** 4 days.

---

## Wave 3 — Operability and documentation (priority: medium/low)

### S3.1 — Metrics endpoint

**Finding.** F-09.

**Changes.**

- New `api/metrics_routes.py` exposing `GET /metrics` in Prometheus text format, restricted
  to loopback callers using the existing helper in `api/admin_security.py:58`.
- New `runtime/metrics.py` (or `core/metrics.py`) with a small counter/histogram registry:
  requests by protocol and provider, retries by reason, fallbacks, failure kinds
  (`core/failures.py:9`), time to first token, total latency, tokens in/out.
- Instrument the execution loop (`application/execution.py:159`–`:655`) and the stream
  presenters (`api/response_streams.py`).
- `api/routes.py` — register the route; `api/app.py` — no change if the router is included
  the same way as the Admin router.

**Tests.** `tests/api/test_metrics_routes.py`: counters increment on a stubbed request, the
endpoint rejects non-loopback callers, the output is valid Prometheus exposition format.

**Acceptance.** A request through the proxy is attributable to provider, model, protocol,
attempts, and latency buckets.

**Effort.** 3 days.

---

### S3.2 — Optional distributed tracing

**Finding.** F-09.

**Changes.**

- New optional extra `telemetry = ["opentelemetry-api", "opentelemetry-sdk",
  "opentelemetry-exporter-otlp-proto-http"]` in `pyproject.toml`.
- `core/trace.py` becomes the span factory; the request correlation id
  (`api/request_ids.py`) is used as the trace/span id so logs and traces join.
- Tracing is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is configured; no behavior change when
  the extra is not installed.

**Acceptance.** With the extra installed and an endpoint configured, one span per request with
provider and model attributes; without it, zero overhead beyond the existing loguru context.

**Effort.** 2 days.

---

### S3.3 — Nightly execution of the live suites

**Finding.** F-10.

**Changes.**

- New workflow `.github/workflows/nightly.yml`: on a schedule and on manual dispatch, run
  `smoke/` on Linux and macOS and the macOS desktop build/test.
- Mark the job `continue-on-error: false` but publish a summary that distinguishes
  "environment failure" (network, missing binary, rate limit) from "code failure" by
  parsing the failure category; the nightly job does not block PR merges.
- `smoke/README.md` — document the nightly schedule and how to reproduce locally.

**Acceptance.** A scheduled run covers the smoke suite and the macOS desktop lifecycle every
night; the result is visible in the Actions tab without affecting PR status.

**Effort.** 2 days.

---

### S3.4 — User-facing diagnostics guide and env reference

**Finding.** F-11.

**Changes.**

- `README.md` — "Diagnosing failures" section mapping the error messages and failure kinds
  emitted by `providers/failure_policy.py:91`–`:130` and `core/failures.py:9` to concrete
  user actions (missing key, model not found, quota exhausted, context window exceeded,
  provider cooldown).
- `fcc-doctor` output extended with the same mapping (shared with S1.1 to avoid duplication).

**Effort.** 1 day.

---

### S3.5 — Dependency hygiene

**Finding.** F-12.

**Changes.**

- `pyproject.toml:38` — move `grpcio-tools` to `[dependency-groups].dev` (it has no runtime
  usage).
- Replace `tomlkit` (1 file) and `json5` (2 files) usage with `tomllib` / `json` where the
  used features allow it; otherwise document why they remain.
- Reassess `sqlalchemy` usage in `runtime/sqlite_database.py`: keep it if the pooling and
  migration behavior is required, otherwise reduce to `sqlite3`.

**Acceptance.** The runtime dependency list shrinks, `uv lock` regenerates, all tests pass, and
the install footprint decreases measurably (record the before/after install size).

**Effort.** 1 day.

---

## Traceability Matrix

| Finding | Severity | Steps | Wave |
| --- | --- | --- | --- |
| F-01 Unauthenticated default exposure | Critical | S1.1, S1.5 | 1 |
| F-02 Coverage never measured | High | S0.1, S1.2 | 0–1 |
| F-03 No SAST/dependency gate | High | S1.3 | 1 |
| F-04 Exact Python patch pin | High | S1.4 | 1 |
| F-05 Oversized core modules | Medium | S2.1, S2.2, S2.3, S2.4 | 2 |
| F-06 Four HTTP stacks | Medium | S2.5 | 2 |
| F-07 Broad exception handling | Medium | S2.6 | 2 |
| F-08 Imperative vendor profiles | Medium | S2.7 | 2 |
| F-09 No metrics or tracing | Medium | S3.1, S3.2 | 3 |
| F-10 Live suites absent from CI | Medium | S3.3 | 3 |
| F-11 Documentation gaps | Low | S1.5, S3.4 | 1, 3 |
| F-12 Dependency hygiene | Low | S3.5 | 3 |

Every finding maps to at least one step; no finding is dropped.

---

## Definition of Done (per step)

A step is complete when:

1. the full local check sequence passes: `./scripts/ci.sh` (Windows: `.\scripts\ci.ps1`);
2. CI is green on the pull request, including the new jobs introduced by the step;
3. focused tests exist for the new behavior and the listed edge cases;
4. documentation shipped in the same pull request;
5. the pull-request title carries the correct release prefix;
6. `tests/contracts/` remains green, including import boundaries and the feature manifest;
7. the step's outcome is recorded in this document (measured numbers where the step defines
   a metric).

---

## Key Performance Indicators

| Indicator | Baseline | Target |
| --- | --- | --- |
| Measured line coverage | unknown (S0.1) | measured, with a rising `fail_under` |
| Non-loopback exposure without auth on a default install | possible | impossible |
| Modules over 600 lines in the generation path | 5 | 0 |
| Distinct HTTP client stacks used by providers | 4 | 1 |
| Unqualified `except Exception` in provider and application layers | ~70 files | 0 in touched modules, BLE enabled |
| Security gates on pull requests | 0 | dependency scan + SAST |
| Live suites executed by automation | 0 | nightly |
| Metrics available for provider/model attribution | none | `/metrics` (loopback-only) |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| S1.1 breaks users relying on LAN exposure | Medium | Medium | Explicit, actionable error; documented opt-out; `minor:` release note |
| Coverage gate flakes because of environment-dependent tests | Low | Medium | Exclude the known environment-dependent modules from the gate; `tmp_path_retention_policy = "failed"` already preserves diagnostics |
| S2.5 changes retry classification | Medium | High | Migrate one provider family per PR; keep the existing policy tests green before each migration |
| S2.2–S2.4 refactors introduce subtle regressions | Medium | High | Characterization tests first (S2.1); no public import path changes; migrate behind the existing contract tests |
| SAST/dependency scanners produce noise | Medium | Low | Pin tool versions; explicit allowlist with per-entry rationale |
| Nightly job failures become noise | Medium | Low | Separate scheduled workflow; failure classification in the summary |
| Upstream `httpx2` API churn | Low | Medium | Adapter layer (S2.5) isolates the dependency behind one module |

---

## Sequencing Notes

- **S0.1 must precede S1.2** — the coverage threshold is a measured value, not a guess.
- **S1.1 should merge first among Wave 1 items** — it is the only Critical finding and the
  change alters observable behavior.
- **S1.2 and S1.3 are independent** and can proceed in parallel by different contributors.
- **S2.1 gates S2.2, S2.3, and S2.4** — do not start the splits before the characterization
  tests land.
- **S2.5 and S2.6 interact** — S2.6 removes broad catches that S2.5 would otherwise need to
  preserve; land S2.5 first, then S2.6 against the adapter vocabulary.
- **S3.1 benefits from S2.5** — the metrics taxonomy should use the unified transport error
  vocabulary rather than the current duplicated one.
