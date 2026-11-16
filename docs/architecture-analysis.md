# Architecture Analysis and Improvement Backlog

Status: internal engineering document; baseline analysis with current-state deltas
Scope: `free-claude-code` on branch `custom/main`, re-aligned on 2026-11-16
Audience: maintainers and contributors

This document preserves the static analysis that produced the architecture backlog and
records which findings remain open on `custom/main`. It is the input to
[`implementation-plan.md`](implementation-plan.md), which turns every open finding into an
ordered implementation step.

Related: [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the quality gate that every change in
this backlog must satisfy.

---

## 1. Method

The analysis was performed read-only against the checkout, using:

- static reading of `src/`, `tests/`, `e2e/`, `smoke/`, `scripts/`, `.github/workflows/`;
- file and function size measurements over `src/free_claude_code`;
- dependency-usage cross-checks between `pyproject.toml` and the actual imports;
- inspection of the CI check inventory and of its local mirror (`scripts/ci.sh`, `scripts/ci.ps1`).

Not covered by this pass: live provider traffic, the desktop GUI on Windows/macOS, the
`smoke/` live suite (installer downloads, native binary lifecycle), and runtime profiling.
Those are explicitly listed as gaps in §7.

---

## 2. System Overview

Free Claude Code is a local ASGI application that exposes the Anthropic Messages, OpenAI
Chat Completions, OpenAI Responses, and Gemini GenerateContent wire protocols on one port and
routes each request to a configured upstream provider, translating protocols and tool calls in
both directions.

### 2.1 Layers

| Layer | Package | Responsibility | Rough size |
| --- | --- | --- | --- |
| HTTP surface | `src/free_claude_code/api/` | FastAPI app, auth, request validation, public SSE framing, Admin API | 30 modules |
| Use cases | `src/free_claude_code/application/` | Model routing, primary→fallback→recovery loop, web tools, code sessions | 27 modules |
| Providers | `src/free_claude_code/providers/` | Upstream clients, admission control, retry/cooldown, per-vendor transports | 137 modules |
| Protocol core | `src/free_claude_code/core/` | Wire models, protocol translation, tool-call buffering, failure model | 99 modules |
| Runtime | `src/free_claude_code/runtime/` | Composition root, resource ownership, SQLite persistence, web-tool egress | 31 modules |
| Configuration | `src/free_claude_code/config/` | Validated settings, managed `.env`, provider catalog, Admin model | 29 modules |
| Client integration | `src/free_claude_code/cli/`, `harnesses/` | Server supervisor, launchers, per-client config patching | 60 modules |
| Messaging | `src/free_claude_code/messaging/` | Telegram/Discord front ends, transcript rendering, conversation trees | 55 modules |

The composition root is single and explicit: `runtime/bootstrap.py:44` (`build_asgi_app`).

Dependency direction is enforced by tests, not only by convention:
`tests/contracts/test_import_boundaries.py` asserts import boundaries, acyclicity, and unique
ownership of wire fields across the tree.

### 2.2 Request lifecycle

1. **Entry** — `cli/entrypoints.py:9` → `cli/commands.py:71` (`serve`) → `ServerSupervisor`.
   The host/port socket is reserved before the app is built (`cli/commands.py:303`), and
   uvicorn binds `settings.host` / `settings.port` (`cli/commands.py:332`).
2. **Routing** — `api/routes.py` dispatches per protocol
   (Gemini `:68`, Chat `:137`, Messages `:168`/`:282`, Responses `:243`/`:303`).
   `api/dependencies.py` authenticates (Bearer `:47`, Anthropic `x-api-key` `:73`,
   Gemini `:112`) with a constant-time comparison (`:141`).
3. **Lease** — every generative route acquires a runtime lease so provider configuration stays
   consistent for the whole response (`api/routes.py:175`, `:250`, `:144`, `:108`;
   implementation in `runtime/provider_manager.py:93`).
4. **Model resolution** — `application/routing.py` maps the requested model to an ordered
   list of provider/model candidates (`:131`, `:194`, `:270`).
5. **Execution** — `application/execution.py:159` runs the shared execution loop:
   open candidate → stream → classify failure → retry, correct, fall back, or stop
   (`:470`, `:591`).
6. **Upstream** — provider transports issue the HTTP call. The OpenAI SDK is created with
   `max_retries=0` (`providers/openai_chat/client.py:33`) so that retry policy lives in one
   place (`providers/admission.py`).
7. **Delivery** — provider code emits neutral frames (`core/stream_output.py:11`); the API
   layer renders them in the client's protocol (`api/response_streams.py:330`, `:382`,
   `:403`, `:438`). The first chunk is prefetched (`:237`) so upstream failures that occur
   before the first byte can still become a normal JSON error response.

### 2.3 Protocol translation

| From → To | Implementation |
| --- | --- |
| Messages → Chat | `core/anthropic/conversion.py:453` (tool-call reorder ledger `:313`) |
| Chat → Messages | `core/chat_completions/request.py:352` |
| Chat → Responses | `core/chat_completions/request.py:493` |
| Responses → Chat | `core/openai_responses/chat_request.py:364` |
| Responses → Messages | `core/openai_responses/messages_request.py` |
| Gemini → Chat/Messages/Responses | `core/gemini/request.py:427` |
| Native Messages stream → Chat/Responses/Gemini | `core/chat_completions/messages_stream.py`, `core/openai_responses/messages_stream.py`, `core/gemini/messages_stream.py` |
| Chat source → public protocols | `providers/openai_chat/stream_output.py:342`, `:442` |

Tool calls are buffered until complete and valid: `core/tool_call_buffer.py:67`
(bounded to 16 MiB / 65 536 records), `core/anthropic/tool_calls.py:22`,
`core/chat_completions/tool_calls.py`.

### 2.4 Failure, retry, and recovery

- Retry classification: `providers/failure_policy.py:198` (HTTP), `:255` (policy),
  `:362` (error mapping). Auth, bad request, and context-window overflow are not retryable.
- Admission controller: `providers/admission.py:485`, up to 10 attempts (`:36`), exponential
  backoff 2 s → 60 s with jitter (`:37`–`:39`), `Retry-After` parsing (`:1119`).
- Coordinated recovery episode with a single half-open probe leader: `providers/admission.py:605`.
- A retry is only allowed while nothing has been delivered to the client:
  `providers/stream_recovery.py:12`. After delivery the recovery decision becomes
  `RESTART` / `CONTINUE` / `HANDOFF` / `STOP` (`core/stream_recovery.py:99`).
- Model/provider fallback is configured through `MODEL_FALLBACKS`
  (`config/model_refs.py:31`) and consumed by `application/execution.py:486`.

### 2.5 Observability today

- Structured JSON logging via Loguru (`config/logging_config.py:68`), with explicit privacy
  switches for raw payloads, raw SSE events, messaging content, and error tracebacks
  (`config/settings.py:658`–`:683`).
- Correlation identifiers and request lifecycle middleware (`api/request_ids.py`,
  `api/request_lifetime.py`).
- Health, root, models, and stop endpoints (`api/routes.py:374`–`:458`).
- Structured trace events exist (`core/trace.py`), but there are **no metrics and no
  tracing export**: no `/metrics` route, no latency/TTFT/token counters, no OpenTelemetry.

---

## 3. Strengths to Preserve

These are quality assets; the backlog below must not regress them.

1. **Architecture is tested, not just documented.** `tests/contracts/` (404 collected tests) asserts
   import boundaries, graph acyclicity, wire-field ownership, and that every feature in the
   manifest has a declared test owner (`tests/contracts/test_feature_manifest.py:28`).
2. **CI is unusually disciplined.** Multi-OS pytest sharding balanced by measured durations
   (`scripts/ci_timings.py`), Playwright shards with retained traces, SHA-pinned actions,
   `UV_MALWARE_CHECK=1`, `permissions: contents: read`, and a dedicated job that bans
   `# type: ignore`, `# ty: ignore`, and `from __future__ import annotations`.
   The local mirror `scripts/ci.sh` / `scripts/ci.ps1` is itself covered by
   `tests/scripts/test_ci_scripts.py`.
3. **Warning hygiene.** `filterwarnings = ["error"]` (`pyproject.toml:149`) with only two
   narrowly scoped exemptions.
4. **Security work already present.** SSRF guard with DNS pinning
   (`runtime/web_tools/egress.py:30`), loopback-only Admin with host/origin validation
   (`api/admin_security.py:58`), constant-time token comparison (`api/dependencies.py:141`),
   `0600`/`0700` permissions for credentials, config, and SQLite
   (`config/env_migrations.py:338`, `runtime/sqlite_database.py:237`).
5. **Streaming correctness.** Bounded tool-call buffering, delivery tracking
   (`core/stream_delivery.py:11`), and a first-chunk prefetch that preserves error semantics.
6. **No leftover markers.** Zero `TODO`/`FIXME`/`HACK`/`XXX` occurrences in `src/`.

---

## 4. Findings

Severity scale: **Critical** (exploitable or data-loss risk in default configuration),
**High** (missing verification or blocks correct distribution), **Medium** (structural
maintenance cost or partial blind spots), **Low** (hygiene and documentation).

### F-01 — Critical — Default configuration exposes an unauthenticated proxy on all interfaces

`config/settings.py:750` sets `host` default `"0.0.0.0"`; `config/settings.py:753` sets
`proxy_auth_enabled` default `False`; `config/settings.py:758` sets the token default to the
well-known value `"freecc"`. The binding is applied at `cli/commands.py:332` and the socket is
reserved at `cli/commands.py:303`.

Result: on a default installation, every generative endpoint — `POST /v1/messages`
(`api/routes.py:282`), `POST /v1/responses` (`api/routes.py:303`),
`POST /v1/chat/completions` (`api/routes.py:137`), Gemini generate/stream
(`api/routes.py:68`) — is reachable from the whole local network without authentication, and
the configured upstream API keys are spendable through it. The Admin UI is correctly
loopback-only (`api/admin_security.py:58`), which shows the boundary was considered for the
admin surface but not for the generation surface.

The README documents how to *enable* authentication (README, “Configure NVIDIA NIM” section)
but never states the default exposure.

### F-02 — High — Test coverage is never measured

`pytest-cov` is a declared dev dependency (`pyproject.toml:104`) but no invocation of
`--cov` exists, there is no `[tool.coverage]` section, and no CI job uploads or gates a
coverage report. The repository collects 11 656 pytest tests, 516 Playwright E2E tests, and
971 smoke tests, yet a regression that removes coverage from a module is invisible.

Modules with no direct test import (reached only through their consumers) include:
`api/admin_cache.py`, `api/admin_security.py`, `api/classifier_projection.py`,
`api/stream_frames.py`, `messaging/safe_diagnostics.py`, `messaging/ui_updates.py`,
`messaging/cli_event_constants.py`, `messaging/trees/transaction.py`,
`providers/endpoint.py`, `providers/openai_client.py`.

`messaging/trees/transaction.py` (commit/rollback of persistent state) and
`messaging/safe_diagnostics.py` (sanitization before logging) are the two where a silent
coverage gap could cause data-integrity issues or secret leakage.

### F-03 — High — No security-focused static analysis or dependency vulnerability gate

`.github/workflows/tests.yml` runs Ruff lint/format checks and `ty` type checking, and
`.github/dependabot.yml` schedules dependency updates. These checks are valuable but are not
security-focused analysis. The remaining supply-chain protection is uv's malware check
(`:10`–`:18`). There is no `pip-audit`/OSV scan, no dependency review, and no SBOM for
published artifacts (`.github/workflows/post-merge.yml:80` publishes without one).

The runtime dependency set is large (44 direct dependencies), which raises the practical
value of automated vulnerability scanning and security-focused static analysis.

### F-04 — High — `requires-python` pins an exact patch release

`pyproject.toml:12` declares `requires-python = "==3.14.10"`. A user on 3.14.9 or on a future
3.14.x cannot install the published package even though the code is compatible.
`tests/contracts/test_uv_policy.py:88` asserts that `uv.lock` mirrors the requirement, so the
lock file must be regenerated in lockstep. `scripts/install.sh:1861` and
`scripts/install.ps1:2369` parse `requires-python` and therefore also need verification after
the change.

### F-05 — Medium — Four files exceed 1 100 lines in the generation path

| File | Lines | Top-level functions |
| --- | --- | --- |
| `providers/openai_chat/transport.py` | 1 367 | — |
| `core/history_replay.py` | 1 325 | — |
| `application/code_sessions/service.py` | 1 194 | — |
| `providers/admission.py` | 1 157 | — |

`runtime/provider_manager.py` is the next largest file at 995 lines and remains below the
1 100-line threshold.

These files hold most of the request-critical logic: stream creation and retry corrections
(`openai_chat/transport.py:634`, `:826`), admission and cooldown
(`providers/admission.py:485`), and reasoning replay (`core/history_replay.py`). The size
inflates merge conflicts, review cost, and the probability of context-sensitive defects.

### F-06 — Medium — Four HTTP client stacks with duplicated error taxonomies

`pyproject.toml` declares `httpx` (`:18`), `httpx2` (`:19`), `aiohttp` (`:28`), and
`requests` (`:33`), plus the OpenAI SDK (`:26`) which embeds its own transport. Consequence:
the same logical failure ("timeout", "network error", "protocol error") is expressed in
several exception hierarchies, and every consumer must handle all of them. Examples:
`providers/failure_policy.py:12`–`:13` and `:276`–`:278`;
`providers/runtime/discovery.py:7`–`:8` and `:62`–`:94`;
`providers/openai_client.py:3`–`:4`; `providers/github_copilot/provider.py:9`–`:10`.

### F-07 — Medium — Broad exception handling without a typed mapping

Roughly 70 source files contain `except Exception`. Concentrations:
`application/code_sessions/service.py` (13 occurrences), `providers/github_copilot/sdk.py` (11),
`messaging/workflow.py` (7), `providers/openai_chat/transport.py` (3),
`runtime/provider_manager.py` (4). The project already has a protocol-neutral failure model
(`core/failures.py:9`–`:41`, `FailureKind` / `ExecutionFailure`) but it is not consistently
used where it matters most, which weakens failure classification, retry decisions, and log
quality.

### F-08 — Medium — Vendor-specific behavior is imperative inside the shared transport

`providers/openai_chat/profiles.py` (874 lines) encodes per-vendor differences as branches
inside the common path, and `core/openai_responses/tool_adaptation.py` (759 lines) does the
same for Responses. Every new vendor therefore adds conditionals to the hot path and requires
manual verification against the shared retry, reasoning, and tool-call machinery.

### F-09 — Medium — No metrics or tracing export

Only logs are emitted. There is no way to answer, in production: which provider served a
request, how many retries/fallbacks occurred, the time-to-first-token, the token spend per
model, or the distribution of failure kinds. With ~20 providers, multi-attempt retries, and
model fallback, per-request attribution is currently only possible by reading logs.

### F-10 — Medium — The fragile suites never run in CI

`pyproject.toml:156` sets `testpaths = ["tests"]`, so `smoke/` (971 live tests: real
installer downloads, SHA-256 checksum verification, native binary lifecycle) is excluded from
the default run. The macOS desktop build/test is only reachable with `--only macos-desktop`
(`scripts/ci.sh:181`–`:185`, `scripts/ci.ps1:196`). Both are the least deterministic parts of
the project and remain a manual responsibility of the maintainer, executed only before a
release.

### F-11 — Low — Documentation gaps around the security model

There is no `SECURITY.md`, no threat model, and no complete reference of the environment
contract. The README never states the default bind address or the default authentication
state, and there is no user-facing mapping from failure messages to remediation steps.

### F-12 — Low — Dependency hygiene

`grpcio-tools` is declared (`pyproject.toml:38`) but has zero occurrences in `src/`, `tests/`,
`scripts/`, `smoke/`, and `e2e/`. `tomlkit` is used in one file and `json5` in two, both
replaceable by the standard library (`tomllib`, `json`). `sqlalchemy` is used in two places
(`runtime/sqlite_database.py`). These inflate install size and attack surface.

---

## 5. What Is Already Solid

For completeness, the following areas were examined and produced no actionable finding:

- SSRF protection for `web_fetch`, including DNS pinning and private-range rejection
  (`runtime/web_tools/egress.py`);
- Admin authentication and origin checks (`api/admin_security.py`);
- constant-time token comparison and per-protocol auth schemes (`api/dependencies.py`);
- file permissions for secrets, config, SQLite, and harness resources (`0600`/`0700`);
- shutdown and cleanup paths (`runtime/lifecycle.py`, `api/response_streams.py:59`–`:191`);
- retry/backoff correctness and `Retry-After` handling (`providers/admission.py`);
- tool-call buffering bounds and ordering (`core/tool_call_buffer.py`);
- test isolation and determinism (`tests/conftest.py:31`–`:55`).

---

## 6. Measurement Snapshot

| Metric | Value |
| --- | --- |
| Python modules under `src/` | 471 |
| Pytest tests collected under `tests/` | 11 656 |
| Playwright E2E tests collected | 516 |
| Smoke tests collected (excluded from CI) | 971 |
| Contract tests collected | 404 |
| `TODO`/`FIXME` in `src/` | 0 |
| Measured line coverage | not measured |
| Files > 1 100 lines | 4 |
| Files containing `except Exception` | ~70 |
| Concurrent HTTP client stacks | 4 |
| CI operating systems | Linux, Windows, macOS |

---

## 7. Known Gaps in This Analysis

- Runtime behavior under real provider load was not exercised; retry storms, backpressure,
  and concurrency behavior under many parallel clients are unverified.
- The `smoke/` suite, the desktop GUI, and the macOS launcher were not executed.
- No dependency CVE scan was run locally; F-03 is based on the absence of a CI gate, not on
  the presence of known vulnerabilities.
- Log volume and cost were not measured, so the observability recommendations
  (F-09) are qualitative.
- The `messages/`, `api/admin_static/`, and `smoke/` front-end code was reviewed at the
  structural level only, not line by line.

---

## 8. Relationship to the Implementation Plan

Every finding maps to at least one numbered step in
[`implementation-plan.md`](implementation-plan.md). The mapping is maintained there as a
traceability matrix so that no finding is silently dropped.
