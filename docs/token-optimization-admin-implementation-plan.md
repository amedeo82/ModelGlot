# Implementation Plan: Token Optimization and Usage in the Admin Dashboard

Status: implemented through S4.2 on 2026-11-19; optional S4.3 cost estimation deliberately disabled
Input: [`token-optimization-admin-analysis.md`](token-optimization-admin-analysis.md)
Scope: revalidated at commit `4946962c` on 2026-11-17
Audience: maintainers and contributors

This plan adds a read-only **Token optimization** Admin view in four delivery waves:
external-tool summaries, ModelGlot usage normalization, durable aggregates, and optional trends
and export. RTK and Headroom retain ownership of their savings ledgers. ModelGlot owns provider
request usage, model attribution, and known model context limits. The implementation must
not turn these different measurements into an exact combined total or a billing claim.

Each step is one pull request except where a step explicitly requires several changes to
land together for contract coherence. Steps within a wave are ordered; later waves require
the previous wave's acceptance criteria.

---

## 0. Ground Rules

1. **Read-only product surface.** The new view performs no configuration mutation and has
   no Apply action. RTK and Headroom installation, hooks, filters, and compression policy
   are outside this plan.
2. **Keep provenance visible.** Every optimization card names its source command and uses
   `basis: tool_reported`. Provider usage uses `basis: provider_reported`; estimates are
   labeled separately and never mixed into provider-reported totals.
3. **No additive-savings claim.** Do not display an exact combined RTK/Headroom total. Their
   inputs may overlap and their accounting units differ. Do not assign RTK savings to a
   model because RTK runs before model selection.
4. **No billing claim.** Use “tool-reported tokens saved,” “provider-reported usage,” and
   “context utilization.” Do not use “tokens billed,” “invoice,” or “money saved.” Any later
   cost display is optional, off by default, and explicitly approximate.
5. **Unknown remains unknown.** Missing usage fields are `null`, not zero. A legitimate zero
   report remains zero. Omit context percentages when no trustworthy positive limit exists.
6. **Minimal metadata only.** Never persist prompts, completions, tool arguments, raw command
   output, credentials, or external ledger paths. Admin JSON must not expose local paths.
7. **Existing boundaries hold.** New modules respect `tests/contracts/test_import_boundaries.py`.
   `api` owns HTTP translation; `application` owns typed models and pure parsing; `runtime`
   owns subprocesses, SQLite, clocks, and composition; `providers` does not import Admin code.
8. **Generation remains authoritative.** Usage instrumentation is best-effort and must not
   change provider selection, fallback, retry, streaming, status codes, or response payloads.
   A telemetry failure is logged without request content and does not fail generation.
9. **Admin security is unchanged.** Every new page, asset, and API uses
   `require_loopback_admin` and the existing `Cache-Control: no-store` behavior. No public
   metrics endpoint is introduced.
10. **Tests accompany behavior.** Add focused unit, API, migration, and browser coverage in
    the same step. A feature added to `smoke/features.py` must name its test owner.
11. **Repository delivery rules apply.** Source changes use a `minor: ` pull request title.
    No version strings change. New local checks must be mirrored in `scripts/ci.sh`,
    `scripts/ci.ps1`, `.github/workflows/tests.yml`, and `tests/scripts/test_ci_scripts.py`.
12. **Documentation delivery.** These two documents land with the first Wave 1 code pull
    request, or separately only as an owner-approved documentation pull request.

Effort values are rough developer-days for a contributor familiar with the repository.

---

## 1. Fixed Design Decisions

| Decision | Selected behavior |
| --- | --- |
| View name | **Token optimization**; avoids implying network-bandwidth optimization |
| Initial scope | RTK and Headroom aggregate summaries plus explicit unavailable/empty states |
| External source | Documented JSON CLI commands only; no private ledger reads or upstream imports |
| External command execution | Direct argument vector resolved with `shutil.which`; never a shell |
| External failures | Separate `not_installed`, `timeout`, `invalid_output`, and `error` states |
| Refresh | On view activation/manual refresh; short TTL and single-flight to avoid process storms |
| External and ModelGlot data | Separate endpoints and cards so either can load or fail independently |
| Usage record | Canonical nullable token fields with explicit gateway/provider model identities |
| Retry accounting | Persist attempts for diagnosis only if needed; user-facing totals count one final logical request |
| Persistence | Existing ModelGlot SQLite database and migration registry; no second database |
| Context utilization | Show only when both occupancy and a confirmed positive model limit are available |
| Cost | Deferred to Wave 4 and excluded from the default response |
| Export | CSV of the same filtered aggregate rows; no raw request content or hidden metadata |

### 1.1 Canonical token semantics

Normalize inclusive provider totals without double counting cache or reasoning tokens:

- `input_tokens`: uncached/non-cache-creation input tokens when the provider partitions them;
- `cache_read_tokens`: cached input reads, when reported;
- `cache_creation_tokens`: cache writes, when reported;
- `input_total_tokens`: inclusive input total, computed only from a valid partition or copied
  from a provider total whose inclusion rules are known;
- `output_tokens`: inclusive output total, including reasoning when the provider includes it;
- `reasoning_tokens`: the reported reasoning subset of output, never added again to output;
- `total_tokens`: provider total when reported; otherwise a derived value only when every
  required component is known;
- `estimated_input_tokens`: ModelGlot's pre-flight estimate, stored separately and excluded from
  provider-reported sums.

Use `core/anthropic/usage.py::anthropic_input_usage_fields` for inclusive input partitions.
OpenAI-compatible cache fields come from `prompt_tokens_details` /
`input_tokens_details`, and reasoning from `completion_tokens_details` /
`output_tokens_details`. Gemini maps `promptTokenCount`, `cachedContentTokenCount`,
`candidatesTokenCount`, `thoughtsTokenCount`, and `totalTokenCount`; candidates plus thoughts
must not be added twice when `candidatesTokenCount` is already inclusive. Invalid, negative,
boolean, or internally inconsistent counts become unknown and emit a sanitized debug log.

---

## 2. Target Contracts

### 2.1 External optimization endpoint

Add `GET /admin/api/token-optimization`. Its response is versioned and contains no local path,
stderr, command history, prompt, or environment data:

```json
{
  "schema_version": 1,
  "generated_at": "2026-11-17T12:00:00Z",
  "optimizations": {
    "rtk": {
      "state": "available",
      "version": "0.44.2",
      "source": "rtk gain --format json",
      "basis": "tool_reported",
      "total_commands": 29,
      "tokens_before": 19009,
      "tokens_after": 10289,
      "tokens_saved": 8720,
      "savings_percent": 45.87
    },
    "headroom": {
      "state": "available",
      "version": "0.40.0",
      "source": "headroom savings --json",
      "basis": "tool_reported",
      "tokens_saved": 0,
      "tokens_before": 0,
      "calls": 0,
      "savings_percent": 0.0,
      "model_attribution": "unknown"
    }
  },
  "notices": []
}
```

Allowed states are `available`, `not_installed`, `timeout`, `invalid_output`, and `error`.
Unavailable entries expose a stable, human-safe `message`; detailed exceptions stay in logs.
A successful Headroom report with all-zero counters is `available`, not `not_installed`.
Optional fields are omitted or `null` consistently; tests freeze the selected convention.

Collection commands are fixed:

- RTK summary: `rtk gain --format json`, with `RTK_TELEMETRY_DISABLED=1`;
- RTK version: `rtk --version` only when needed and covered by the same timeout policy;
- Headroom summary: `headroom savings --json`;
- Headroom version: `headroom --version` only when needed and covered by the same policy.

Do not invoke `rtk gain --history` or return Headroom's top-level `path` field. Initially parse
only the observed summary fields. Unknown additional JSON fields are ignored. Missing known
fields remain unknown unless their absence makes the report unusable.

### 2.2 Durable usage endpoint

Add `GET /admin/api/usage?from=<RFC3339>&to=<RFC3339>&group_by=model` in Wave 3. Support only
allow-listed groupings (`model`, `provider`, `day`) and a bounded interval. The response has
independent sections for request/token aggregates and context utilization. It returns HTTP
200 with empty rows for no data, HTTP 400 for invalid filters, and does not proxy collector
exceptions as raw messages.

Each aggregate row includes provider id, gateway model, provider model, request count,
successful/failed/cancelled counts, nullable token sums, sums with explicit `reported` or
`estimated` basis, and duration aggregates. Context rows include `context_used_tokens`,
`context_window_tokens`, `utilization_percent`, `limit_source`, and `sampled_at`. A context
row without a reliable limit has no percentage.

### 2.3 Runtime and module ownership

- New `application/token_optimization.py`: immutable report models, parser validation, and
  JSON-safe serialization helpers; no subprocess, filesystem, SQLite, or API imports.
- New `runtime/token_optimization.py`: executable discovery, bounded subprocess execution,
  timeout/error translation, TTL cache, and concurrent-request coalescing.
- `api/ports.py::AdminRuntimePort`: add async read methods for optimization and usage reports.
- `runtime/application.py::ApplicationRuntime`: implement those methods through injected
  runtime services; do not place subprocess or SQL code in `api/admin_routes.py`.
- New `runtime/usage_events_sqlite.py`: persistence and aggregate queries through
  `SQLiteDatabase.run(..., write=...)`; never open a separate connection to the same database.
- New `application/usage_events.py`: canonical usage and filter/aggregate models shared by
  request instrumentation and storage adapters.
- Provider instrumentation publishes canonical records through a narrow runtime-owned sink;
  provider modules must not import SQLite or Admin modules.

---

## Wave 0 — Baseline and Contract Fixtures

### S0.1 — Freeze external JSON fixtures and current Admin behavior

**Goal.** Make external-tool coupling and the no-regression baseline reviewable before source
changes.

**Changes.**

- Add sanitized RTK 0.44.2 and Headroom 0.40.0 fixtures under
  `tests/application/fixtures/token_optimization/`, including populated, zero, missing-field,
  extra-field, and malformed examples. Remove usernames, paths, project names, commands, and
  any other local data.
- Record the baseline in the pull request description: `/admin`, direct Admin routes, versioned
  assets, loopback rejection, `no-store`, Apply visibility on configuration views, and the
  current `AdminRuntimePort` fake implementations used by tests.
- Do not run external tools in unit or CI tests; all process results are injected fixtures.

**Tests.**

- Fixture validation test proves every JSON fixture parses and contains no `path`, `command`,
  `prompt`, `authorization`, or `api_key` keys.
- Existing `tests/api/test_admin.py` and `e2e/test_admin_assets.py` remain green unchanged.

**Acceptance.** External semantics are represented without a network or local-tool dependency,
and baseline Admin behavior is explicit.

**Effort.** 0.5 day.

### S0.2 — Declare feature ownership and documentation links

**Goal.** Establish test ownership and ensure the analysis/plan pair is discoverable.

**Changes.**

- Add a `token_optimization_admin` feature entry to `smoke/features.py` with focused unit,
  runtime, API, and browser tests as they are introduced.
- Bundle `docs/token-optimization-admin-analysis.md` and this plan with S1.1, or obtain the
  repository owner's approval for this documentation-only pull request.
- Add no CI commands unless a genuinely new check is required; reuse existing test jobs.

**Tests.** `tests/contracts/test_feature_manifest.py` and existing smoke inventory tests.

**Acceptance.** Every new feature test file has a declared owner and no undocumented CI/local
divergence is introduced.

**Effort.** 0.25 day.

---

## Wave 1 — External RTK and Headroom Summary

### S1.1 — Typed parsers and bounded external collector

**Goal.** Produce a safe, typed external summary without touching the request path.

**Changes.**

- New `application/token_optimization.py`: define state enums, immutable RTK/Headroom report
  models, strict non-negative integer/finite-number validation, and pure JSON parsers. Strip
  all unneeded Headroom fields, especially `path`; never return raw stderr.
- New `runtime/token_optimization.py`: implement `ExternalTokenOptimizationCollector` with
  injected executable resolver, subprocess runner, clock, timeout, and cache TTL. Resolve via
  `shutil.which`, invoke an argument list with `shell=False`, capture stdout/stderr separately,
  enforce output-size and time bounds, and parse JSON only after exit code zero.
- Run RTK with a copied environment plus `RTK_TELEMETRY_DISABLED=1`. Do not pass user input,
  config secrets, working-directory paths, or shell interpolation.
- Use `asyncio.to_thread` or the repository's existing owned-worker helper so subprocess waits
  do not block the event loop. Coalesce concurrent refreshes and cache both success and failure
  for a short TTL; manual refresh must not create unbounded concurrent processes.
- Map resolver absence, timeout, non-zero exit, oversized output, invalid JSON, and invalid
  schema to the stable states in section 2.1. Log sanitized diagnostics only.

**Tests.**

- New `tests/application/test_token_optimization.py`: observed RTK/Headroom fixtures; zero vs
  missing values; negative, boolean, non-finite, wrong-type, and extra fields; private-field
  stripping; stable serialization.
- New `tests/runtime/test_token_optimization_collector.py`: executable absent, direct argv, no shell,
  telemetry override, non-zero exit, malformed/oversized stdout, timeout, cache TTL,
  single-flight, cancellation, and one tool failing while the other remains available.

**Acceptance.** No test launches a real external executable. Collector latency is bounded,
Admin callers cannot inject arguments, and no private path or raw process error reaches a
report model.

**Effort.** 2 days.

### S1.2 — Runtime port and loopback-only Admin API

**Goal.** Expose the collector through the existing Admin layering and security boundary.

**Changes.**

- `api/ports.py::AdminRuntimePort`: add `token_optimization() -> JsonObject` with the same
  async style as neighboring methods.
- `runtime/application.py`: compose/inject the collector in `runtime/bootstrap.py` and expose
  `ApplicationRuntime.token_optimization()`. Keep process ownership out of the API route.
- `api/admin_routes.py`: add `GET /admin/api/token-optimization`, call
  `require_loopback_admin`, and return the runtime payload. Do not catch and echo raw errors.
- Extend test runtime fakes/stubs with the new port method. Keep existing endpoints unchanged.

**Tests.**

- `tests/api/test_admin.py`: local 200 and exact response contract; remote 403; `no-store`;
  collector states propagate; unexpected collector failure has a sanitized response; runtime
  port fakes satisfy the protocol.
- `tests/contracts/test_import_boundaries.py`: extend only if the new module layout requires
  an explicit boundary assertion; do not weaken existing rules.

**Acceptance.** The endpoint is loopback-only and versioned, one tool failure does not suppress
the other tool's result, and neither SQL nor subprocess code appears in `api`.

**Effort.** 1 day.

### S1.3 — Read-only Token optimization Admin view

**Goal.** Display external summaries with clear provenance and complete UI states.

**Changes.**

- `api/admin_static/admin.js`: add `token_optimization` to `VIEW_GROUPS`, wire `setActiveView`
  to lazy-load/refresh only this view's endpoint, preserve back/forward behavior, and hide the
  global Apply bar. Avoid an automatic high-frequency polling loop.
- `api/admin_static/index.html`: add a semantic section with RTK and Headroom cards, refresh
  control, loading/error/empty regions, and methodology text. Add direct route
  `/admin/token_optimization` in `api/admin_routes.py` using `admin_page_response`.
- Prefer new `token_optimization.js` and `token_optimization.css` assets for view-specific
  behavior/styling. Register both in `_ADMIN_ASSET_FILENAMES` and load versioned URLs. Reuse
  existing design tokens and responsive table/card patterns.
- Render numbers with `textContent`, never `innerHTML` for external data. Show source command,
  tool-reported basis, last refresh, and a visible non-additivity notice. Do not show a combined
  savings card, model attribution for RTK, cost, or local paths.

**Tests.**

- `tests/api/test_admin.py`: direct route, versioned assets and media types, remote asset/page
  rejection, and `no-store` for new resources.
- New `e2e/test_token_optimization_admin.py`: navigation, reload, back/forward, Apply hidden,
  loading, both populated, zero Headroom, one/both unavailable, timeout, malformed data,
  manual refresh, responsive layout, and no combined total/path leakage.
- Existing `e2e/test_admin_assets.py` navigation and independence suites remain green.

**Acceptance.** The rest of Admin remains usable while collection is slow or failed. Every
state is understandable without implying that a zero report proves inactivity.

**Effort.** 1.5 days.

### S1.4 — Wave 1 documentation and release gate

**Goal.** Make operational semantics and limitations explicit before enabling the view.

**Changes.**

- README: document the new local-only view, supported external JSON commands, optional-tool
  behavior, and the distinction between token optimization and provider billing.
- Mark S0.x and S1.x complete in this plan only in the pull request that satisfies their
  acceptance criteria. Leave later waves proposed.
- Run focused tests, then the full `scripts/ci.ps1` gate on Windows and `scripts/ci.sh` in CI.

**Acceptance.** Full quality gates pass; the feature works when neither tool is installed and
when only one is installed; no configuration or provider behavior changed.

**Effort.** 0.5 day.

---

## Wave 2 — Canonical ModelGlot Usage Instrumentation

### S2.1 — Canonical usage model and protocol normalization

**Goal.** Normalize provider usage once, preserving unknowns and cache/reasoning semantics.

**Changes.**

- New `application/usage_events.py`: define canonical usage models and validation listed in
  section 1.1, with no provider transport or runtime dependencies.
- Add pure normalization functions for Anthropic Messages, OpenAI Chat Completions, OpenAI
  Responses, and Gemini. Reuse `anthropic_input_usage_fields`; preserve DeepSeek's validated
  cache partition behavior rather than bypassing it.
- Instrument the existing final-usage owners, including
  `providers/continuation.py::SourceRecoveryState.observe` and the Chat/Gemini terminal usage
  paths, through a narrow observer interface. Do not infer usage from DEBUG trace text.
- Ensure every emitted observation includes request/execution/attempt identity and protocol.
  Model/provider attribution is completed in S2.2.

**Tests.**

- New `tests/application/test_usage_events.py`: all protocol fixtures, inclusive/exclusive
  cache totals, reasoning subsets, null vs zero, malformed/inconsistent counts, Gemini
  candidates/thoughts handling, and idempotent final-event selection.
- Focused provider tests: final usage emits once; partial/streaming updates do not create
  duplicate final observations; no-usage responses remain unknown; existing wire output is
  byte-identical.

**Acceptance.** All four protocols produce the same canonical shape; cache and reasoning are
never double counted; no provider response or retry decision changes.

**Effort.** 2 days.

### S2.2 — Provider/model attribution and final-request accounting

**Goal.** Join usage to routing and outcome metadata without counting retries as extra client
requests.

**Changes.**

- Use `providers/attempt_loop/loop.py::run_attempts` / `AttemptPlan` for provider id,
  `gateway_model`, `provider_model`, execution id, and attempt ordinal; the existing
  `provider.request.sent` trace already demonstrates the required identity.
- Extend `ProviderExecution` only with observability metadata needed to correlate terminal
  usage. Do not expose mutable request content through the observer.
- Extend `core/request_outcomes.py::RequestOutcome` with a bounded, request-local usage
  accumulator populated through a new recording function. `record_request_route` remains the
  source of final route identity where fallback updates it.
- `api/request_outcomes.py::RequestOutcomeMiddleware` finalizes exactly one logical request
  record with result, status, duration, sanitized failure category, and selected provider/model.
  Define retry semantics explicitly: physical attempts are diagnostic children; default model
  aggregates sum the successful terminal attempt plus failed attempts only in a separately
  labeled failed-attempt metric, never as extra successful client requests.
- Cancellation finalizes promptly; late events after finalization are ignored by identity.

**Tests.**

- `tests/core/test_request_outcome_state.py` and `tests/api/test_request_outcomes.py`: success,
  provider failure, HTTP failure, cancellation, fallback, retry-before-success, missing usage,
  multiple terminal observations, and late events.
- `tests/providers/test_attempt_loop.py` (or its current focused equivalent): provider/model
  identity and attempt ordinals survive fallback without changing behavior.

**Acceptance.** One client request has one final logical record; fallback does not duplicate
successful request counts; provider and gateway/provider model fields are not conflated.

**Effort.** 2 days.

### S2.3 — Non-persistent usage read model behind the Admin API

**Goal.** Prove aggregation semantics before introducing a migration.

**Changes.**

- Add an in-memory, bounded runtime usage store behind the same observer/finalizer interface
  planned for SQLite. It is explicitly process-local and ephemeral in this step.
- Add `AdminRuntimePort.usage(...)` and `GET /admin/api/usage` with strict filter parsing,
  allow-listed groupings, maximum range, deterministic ordering, and empty-result behavior.
- Populate the Wave 1 view with a separate ModelGlot usage section labeled “since server start.” Do
  not merge it with RTK/Headroom totals. Leave context rows empty until S3.3.

**Tests.**

- New `tests/runtime/test_usage_event_store.py`: concurrent finalization, bounded memory,
  filter/group/order behavior, null sums, and retry semantics.
- `tests/api/test_admin.py`: valid/invalid filters, range bound, loopback/no-store, empty data,
  and sanitized runtime errors.
- Extend the browser suite for loading, empty, populated, filter, and independent external/ModelGlot
  failure states.

**Acceptance.** Aggregate fixtures match hand-computed counts, unknown token values do not
become zero, restart loss is accurately labeled, and the external endpoint remains independent.

**Effort.** 1.5 days.

---

## Wave 3 — Durable Usage, Retention, and Context

### S3.1 — SQLite migration and repository

**Goal.** Replace process-local storage with bounded durable metadata using existing database
lifecycle and permissions.

**Changes.**

- Add `runtime/sqlite_migrations/v0006_usage_events.py` and register version 6 in
  `runtime/sqlite_migrations/__init__.py`. Register new tables with SQLiteDatabase's table
  ownership validation in `runtime/sqlite_database.py`.
- Create `usage_events` with logical request id, execution/attempt diagnostic identity where
  needed, provider id, gateway/provider model, wire API, outcome/status/duration/failure
  category, nullable canonical token fields, estimated input, and UTC epoch timestamp.
- Add a uniqueness key for the final logical record and, if attempts are stored, a separate
  `(execution_id, attempt, record_kind)` key. Add indexes for `(created_at, id)` and the exact
  provider/model grouping queries. Add `CHECK` constraints for non-negative counts/durations,
  valid outcomes, and consistent attempt numbers.
- New `runtime/usage_events_sqlite.py`: synchronous connection callbacks executed via
  `SQLiteDatabase.run`; upsert final records idempotently and materialize query results before
  returning. No SQL in `api` or `application`.
- Wire the same runtime sink used by S2.3 to SQLite in `runtime/bootstrap.py`. Telemetry write
  failures are best-effort and sanitized; a successful SQL commit is not acknowledged after
  caller cancellation contrary to `SQLiteDatabase.run` delivery guarantees.

**Tests.**

- `tests/runtime/test_sqlite_database.py`: fresh migration 1→6, existing version-5 upgrade,
  idempotent reopen, rollback, table ownership, indexes/constraints, and preservation of
  existing rows.
- New `tests/runtime/test_usage_events_sqlite.py`: insert/upsert, duplicate finalization,
  cancellation/rollback, concurrent writers, null handling, deterministic pagination/filtering,
  and no prompt/raw payload columns.

**Acceptance.** Existing databases upgrade without data loss, duplicate delivery cannot double
count, and usage storage shares the existing ModelGlot file and transaction lifecycle.

**Effort.** 2 days.

### S3.2 — Retention and durable Admin aggregates

**Goal.** Prevent unbounded growth and expose historical aggregates with explicit coverage.

**Changes.**

- Add bounded retention with a documented default (recommended 30 days) and maximum row/count
  guard. Apply deletion in bounded batches through the same writer pool; never use `VACUUM` in
  a request path. Configuration, if any, follows existing settings conventions and is not
  editable from the read-only view.
- Replace the S2.3 ephemeral store with SQLite-backed aggregates. Return `coverage_start`,
  `coverage_end`, `generated_at`, and `retention_days`; do not label retained history “all time.”
- Expose model/provider/day aggregates and duration statistics. Distinguish request count from
  physical attempt count and reported token coverage from unknown values.
- Keep external-tool collection outside the SQL transaction and outside this endpoint's critical
  path.

**Tests.**

- Runtime tests for boundary timestamps, batch deletion, max rows, retained aggregates,
  restart persistence, unknown-vs-zero sums, retry totals, and slow query timeout behavior.
- API tests for coverage metadata, bounded filters, empty history, and independent optimization
  endpoint behavior.
- Browser tests for time filter, model/provider/day grouping, restart persistence, and clear
  retention labeling.

**Acceptance.** Database size remains bounded under the retention policy, historical rows
survive restart, and no aggregate claims coverage beyond retained data.

**Effort.** 1.5 days.

### S3.3 — Context-window utilization

**Goal.** Show context occupancy only when its numerator and denominator are meaningful.

**Changes.**

- Use `application/model_catalog.py::CatalogModel.context_window_tokens` for model capacity,
  retaining provenance that distinguishes provider-confirmed metadata from fallback/unknown
  values. Do not invent a limit from a model-name heuristic.
- Reuse `code_sessions.context_used_tokens` persisted by migration 3 and
  `runtime/code_sessions_sqlite.py` for current Codex occupancy. For regular API requests,
  derive a clearly labeled per-request input/context observation only from canonical usage;
  do not call it conversation occupancy unless conversation identity and retained context are
  actually known.
- Add context rows to `/admin/api/usage` with model, used tokens, positive limit, percentage,
  limit source, and sample time. Average/max context cards state their population and window;
  requests lacking either value are excluded and counted as unavailable, not zero.
- Keep current Code session occupancy separate from request-input utilization; never average
  the two as if they were the same metric.

**Tests.**

- Application/runtime tests for missing/zero/negative limits, fallback metadata, current vs
  stale session samples, provider/gateway model mapping, and percentage rounding/capping policy.
- API/browser tests for known, unknown, and mixed limits; empty occupancy; separate current
  session and per-request cards; no false 0% values.

**Acceptance.** Every percentage has a named numerator, denominator, source, and time window;
unknown context is visibly unavailable rather than fabricated.

**Effort.** 1.5 days.

---

## Wave 4 — Trends, Export, and Optional Estimates

### S4.1 — Time-series trends

**Goal.** Add useful trends without changing the accounting contract.

**Changes.**

- Add allow-listed daily buckets to usage aggregates and, separately, parse
  `rtk gain --daily --format json` if the observed schema remains compatible.
- Render separate ModelGlot usage and RTK savings charts with accessible tabular equivalents. Keep
  Headroom trends separate unless its report supplies a compatible, validated time series.
- Cache and bound bucket counts; use UTC explicitly and document partial current-day buckets.

**Tests.** Bucket boundaries, timezone conversion, missing days, retention truncation, empty
series, external schema drift, and accessible chart/table parity.

**Acceptance.** No line or stacked chart visually implies additive RTK/Headroom/ModelGlot totals.

**Effort.** 1 day.

### S4.2 — CSV export

**Goal.** Export exactly the visible filtered aggregate, not hidden or sensitive data.

**Changes.**

- Add a loopback-only GET export route that reuses the same parsed filters and runtime query
  as `/admin/api/usage`; enforce `no-store`, a safe fixed filename, UTF-8 CSV, formula-injection
  escaping, bounded rows, and stable columns.
- Export aggregate rows only: no request ids, prompts, failure details, ledger paths, or raw
  external output. Include basis and coverage columns.

**Tests.** API security, content type/disposition, filter parity, quoting, Unicode, spreadsheet
formula prefixes, empty export, row bound, and browser download behavior.

**Acceptance.** CSV values match the visible aggregate and cannot expose data absent from the
JSON response.

**Effort.** 1 day.

### S4.3 — Optional theoretical cost estimate

**Goal.** Provide an explicitly approximate estimate only with a maintained price source.

**Changes.**

- Add a versioned price-source adapter with source URL, retrieval timestamp, currency, model
  matching, and separate input/output/cache prices. Missing or stale prices yield no estimate.
- Keep cost disabled by default. When enabled, label it “theoretical estimate,” never “invoice”
  or “money saved”; do not apply model prices to RTK savings or unknown Headroom models.
- Document update ownership and stale-price behavior. No secrets or provider invoice APIs.

**Tests.** Exact/ambiguous/missing model matches, stale source, cache prices, rounding,
disabled default, unknown tokens, and UI labels.

**Acceptance.** No number appears without model, price source, timestamp, coverage, and estimate
label. This step may be deferred indefinitely without blocking earlier waves.

**Effort.** 1.5 days.

---

## 3. Cross-Cutting Privacy, Performance, and Failure Checklist

Before completing each wave, verify:

- Non-loopback page, asset, JSON, and CSV requests receive 403; all Admin responses remain
  `no-store`.
- External commands use fixed argv, no shell, bounded output, bounded runtime, and no secrets;
  `RTK_TELEMETRY_DISABLED=1` is present for RTK.
- No raw stderr, local path, command history, prompt, completion, tool argument, credential,
  or environment value reaches API/HTML/CSV.
- One absent or failing tool does not hide the other tool or ModelGlot usage. Slow external collection
  does not block other Admin views or generation.
- Provider writes are best-effort; database lock/failure cannot change client response success.
- No duplicate successful request totals arise from retries, fallback, repeated terminal usage,
  process restart, or idempotent database upsert.
- Unknown and zero remain distinct in JSON, SQL aggregates, charts, and CSV.
- RTK and Headroom cards remain separate; no default combined savings, per-model RTK savings,
  or unqualified billing/cost claim appears.
- Apply remains hidden and no config manifest fields are added for this read-only view.

## 4. Rollback Strategy

- **Wave 1:** remove/hide the navigation entry and endpoint registration. Collector code is
  inert without the Admin call; provider request handling is untouched.
- **Wave 2:** detach the usage observer/finalizer sink and hide the ModelGlot usage section. Existing
  wire streams and request outcomes remain authoritative; no migration exists before Wave 3.
- **Wave 3:** disable the usage sink while leaving migration 6 and retained metadata in place.
  Never down-migrate or delete the shared ModelGlot database as part of feature rollback. Re-enable
  only after idempotent writes are verified.
- **Wave 4:** remove trends/export/cost routes independently; underlying aggregate data and
  earlier read-only cards remain valid.

## 5. Implementation and Validation Record — 2026-11-19

S0 through S4.2 are implemented. S4.3 was evaluated and deliberately not enabled: no
price catalog, routing change, or billing/cost claim was added. Production uses the shared
SQLite store; the bounded in-memory store remains available for tests and embeddings.

Focused application, provider, runtime, migration, API, manifest, and browser suites pass,
including 25 Token optimization/Admin asset browser tests. `ty check src` and Ruff checks
for the feature files pass. The complete local unit run finished with 11,908 passed and
33 skipped; its three failures are pre-existing/out-of-scope model-discovery assertions
and the out-of-scope `updater.desktop -> config.paths` import violation. The complete
browser run finished with 333 passed and one skipped; its one failure is the out-of-scope
fallback drag-indicator test. These unrelated working-tree failures were preserved rather
than hidden by changing routing, provider, or model-picker behavior.

## 6. Final Acceptance and Verification

The full feature is accepted when:

1. RTK and Headroom populated, zero, missing, timeout, malformed, and error states are covered.
2. Anthropic, OpenAI Chat, OpenAI Responses, and Gemini usage normalize without cache,
   reasoning, retry, or fallback double counting.
3. Provider/model token aggregates persist across restart within declared retention and expose
   unknown coverage honestly.
4. Context percentages appear only with valid occupancy and confirmed positive limits.
5. Direct navigation, reload, history, responsive states, loopback security, `no-store`, and
   hidden Apply behavior pass browser tests.
6. Focused suites and the complete existing CI gate pass on the supported platforms, including
   import boundaries, feature manifest, Admin API, SQLite migrations, and browser coverage.
7. Documentation uses “token/context optimization,” preserves source/basis labels, and makes
   no unqualified additive-savings or billing statement.

Rollback must leave provider routing, streaming, fallback, configuration, and existing Admin
views unchanged.
