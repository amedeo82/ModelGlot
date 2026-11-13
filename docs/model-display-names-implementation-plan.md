# Implementation Plan: Descriptive Model Names

Status: proposed
Input: [`model-display-names-analysis.md`](model-display-names-analysis.md)
Audience: maintainers and contributors

This plan turns the analysis of descriptive model names into ordered, reviewable steps. Each
step is one pull request except where a step states that a single pull request must cover
several changes to stay coherent. The plan changes presentation only: no advertised model
id, routing decision, fallback order, capability fact, or provider request changes.

---

## 0. Ground Rules

These apply to every step in this plan.

1. **One finding focus per pull request.** Steps below propose one pull request each, except
   where a step explicitly states that a single pull request must cover several changes to
   stay coherent.
2. **Pull request title prefixes are mandatory** for any change touching `assets/`, `scripts/`,
   `src/`, `pyproject.toml`, or `uv.lock`: exactly one of `patch: `, `minor: `, `major: `
   followed by a description (`CONTRIBUTING.md:15`). Behavioral and packaging changes use
   `minor: `.
3. **CI/local parity.** Any new local check must be mirrored in `scripts/ci.sh`,
   `scripts/ci.ps1`, and `.github/workflows/tests.yml`, and the parity itself must be covered
   by `tests/scripts/test_ci_scripts.py`.
4. **No suppression shortcuts.** `# type: ignore`, `# ty: ignore`, and
   `from __future__ import annotations` remain banned (`CONTRIBUTING.md:54`).
5. **Tests accompany behavior.** Every step lists the tests it adds. New behavior requires
   focused tests plus edge cases, not only modified existing tests.
6. **Documentation ships with code.** README/CONTRIBUTING updates go in the same pull request
   as the code they describe. A standalone documentation pull request is reserved for the
   repository owner (`CONTRIBUTING.md:7`): the two documents in `docs/` land bundled with
   the first code pull request of Wave 1 (step S1.1), or as an owner-approved documentation
   pull request.
7. **Contract invariants hold.** New modules must respect the import boundaries asserted by
   `tests/contracts/test_import_boundaries.py` and, where a feature is added, declare a test
   owner in the feature manifest (`tests/contracts/test_feature_manifest.py:28`).
8. **No version edits.** Versions are computed and published by the release pipeline
   (`CONTRIBUTING.md:17`); steps never touch version strings.
9. **Presentation-only scope.** No step in this plan may change an advertised model id, the
   provider/model reference, the routing candidate list, the fallback order, or the
   capability facts reported to clients. Any such change is a separate, explicitly approved
   proposal.

Effort estimates are rough developer-days for a contributor already familiar with the
codebase.

---

## Wave 0 — Baseline (before any behavior change)

### S0.1 — Record the current labels

**Goal.** Establish the exact baseline that later steps must improve, so a reviewer can
prove that ids and routing stayed untouched.

**Changes.** No source change. Record in the pull request description:

- `GET /v1/models` output for a configuration containing one NVIDIA NIM model, one MiniMax
  model, one custom provider model, and one native Anthropic model, for the `claude`,
  `claude-desktop`, `messages`, and `responses` views;
- the Admin API payload of `GET /admin/api/models`, including `model_labels`;
- the generated `~/.fcc/codex-model-catalog.json`.

**Acceptance.** The baseline shows `display_name` equal to the provider/model reference for
every provider-backed row, and shows the ids that must remain stable.

**Effort.** 0.5 day.

---

## Wave 1 — Resolution in the application layer

### S1.1 — Carry a descriptive title and a provider description in the catalog

**Goal.** Give the application inventory two distinct presentation facts: a title and a
provider attribution, without touching ids or routing.

**Changes.**

- `src/free_claude_code/application/model_metadata.py:9` — extend `ProviderModelInfo` with an
  optional `display_name` and an optional `description` field, both metadata only.
- `src/free_claude_code/application/model_catalog.py:23` — extend `CatalogModel` with an
  optional `description` field next to `display_name`.
- `src/free_claude_code/application/model_catalog.py:102` — `_catalog_model` resolves the
  title through the resolver of step S1.3 and keeps `display_name` as the fallback value; the
  fallback remains the current raw reference, so the no-behavior-change case is byte-identical
  to today.
- `src/free_claude_code/application/model_catalog.py:70` — the custom provider branch keeps
  its current `<custom display name>/<model id>` shape when no curated title exists and adds
  the provider attribution as description.
- New module `src/free_claude_code/application/model_titles.py` — the single owner of title
  resolution: curated overrides, catalog lookup, id heuristic, raw reference. It must not
  import from `providers/` or `api/`.

**Tests.**

- `tests/application/test_model_catalog.py` (extend):
  - a model without a curated title keeps `display_name` equal to the provider/model
    reference;
  - a model with a curated title uses it and keeps `provider_model_ref` and `wire_slug`
    unchanged;
  - the ` (no thinking)` suffix is still appended to the resolved title and is still the
    only difference between the reasoning and no-reasoning rows;
  - the description carries the provider display name.
- New `tests/application/test_model_titles.py`:
  - curated override wins over catalog and heuristic;
  - the heuristic transforms known id shapes deterministically
    (`nvidia/nemotron-3-ultra-550b-a55b` → `Nemotron 3 Ultra 550B A55B`);
  - an unknown id returns the reference unchanged;
  - two models of the same provider that resolve to the same title get a disambiguated
    second title.

**Acceptance.**

- `CatalogModel.provider_model_ref` and `CatalogModel.wire_slug` are byte-identical to the
  baseline for every row.
- The resolver is a pure function of its inputs, with no I/O and no clock.

**Effort.** 1.5 days.

### S1.2 — Curated title table for the flagship models

**Goal.** Guarantee a good title for the models FCC advertises most, independent of any
external catalog.

**Changes.**

- New module `src/free_claude_code/config/model_title_overrides.py` — a frozen mapping from
  `(provider_id, model_id)` to a title and an optional description. Seed it with the NVIDIA
  NIM Nemotron family and the MiniMax family, using the wording verified in the analysis
  (for example `Nemotron 3 Ultra 550B A55B`, `MiniMax-M3.1-Flash`).
- `src/free_claude_code/application/model_titles.py` — consult the curated table first.
- README — a short section listing the models with curated titles and explaining that other
  models derive their title from the shared catalog.

**Tests.**

- New `tests/config/test_model_title_overrides.py`: every override key is a syntactically
  valid provider/model pair; the provider exists in `PROVIDER_CATALOG`; no duplicate keys;
  titles are non-empty and trimmed.
- `tests/application/test_model_titles.py` (extend): the curated table takes precedence over
  the heuristic for the seeded models.

**Acceptance.** The flagship models have a curated title whether or not any external
catalog is reachable.

**Effort.** 1 day.

### S1.3 — Heuristic title derivation from the model id

**Goal.** Produce a readable title for every model, including models no catalog knows, using
a deterministic transformation of the id.

**Changes.**

- `src/free_claude_code/application/model_titles.py` — add the heuristic step: drop a known
  vendor prefix segment, split the remaining segments on `-`, `_`, `.`, and `/`, capitalize
  each token, preserve numeric tokens and known unit tokens (`550B`, `A55B`, `M3.1`), and
  keep the vendor prefix when it is the only meaningful part.
- The heuristic must be total: any string input yields a non-empty result.

**Tests.**

- `tests/application/test_model_titles.py` (extend): table-driven cases covering
  `vendor/model` ids, bare ids, ids with version suffixes, ids with underscores, ids with
  mixed case, empty input, and ids consisting only of separators.

**Acceptance.** No model is ever shown with an empty title, and the transformation is
reproducible across runs and platforms.

**Effort.** 1 day.

---

## Wave 2 — The external catalog as an optional, cached source

### S2.1 — Catalog client and reduced local cache

**Goal.** Obtain titles and descriptions from models.dev without ever blocking a request.

**Changes.**

- New module `src/free_claude_code/providers/model_catalog_source.py` — the single owner of
  the external catalog access: fetch `https://models.dev/api.json`, validate the payload
  shape, and reduce it to a map of `(models.dev provider id, model key) -> (name,
  description)` for the mapped providers only.
- New module `src/free_claude_code/config/model_catalog_paths.py` (or an addition to
  `config/paths.py:107`) — the cache file path under `~/.fcc`, for example
  `models-dev-catalog.json`.
- The writer reuses the atomic publish pattern of `runtime/codex_catalog.py:43`–`:62`
  (temporary file plus `replace`).
- The cache stores the reduced map plus the fetch timestamp, not the full payload.
- No call site of this module may sit on the request path. The module exposes an explicit
  `refresh()` that the runtime schedules in the background.

**Design decision to make first.** Two candidate semantics for freshness:

- *Option A (recommended):* the cache is refreshed at most once every 24 hours, in the
  background, and a stale cache is still served.
- *Option B:* the cache is refreshed on every model-list refresh request, with a hard
  timeout and a failure budget.

Option A is preferred: the catalog response carries
`cache-control: public, max-age=0, must-revalidate`, so HTTP caching does not help, and a
title is presentation only, so daily freshness is sufficient.

**Tests.**

- New `tests/providers/test_model_catalog_source.py`:
  - a valid payload is reduced to the expected map for the mapped providers;
  - an unrelated provider is dropped;
  - a malformed payload raises a typed error and never produces partial data;
  - the network call is never made from a catalog read path.
- New `tests/providers/test_model_catalog_cache.py`:
  - a fresh cache is read without network access;
  - an expired cache is still readable and is marked stale;
  - writing is atomic and a failed write leaves the previous cache intact.

**Acceptance.**

- With the network disabled, the title resolution path still returns the curated title, the
  heuristic title, or the raw reference.
- The cache file contains only the reduced map.

**Effort.** 2 days.

### S2.2 — Provider-id mapping and catalog integration

**Goal.** Join the catalog to FCC provider/model references without guessing.

**Changes.**

- New module `src/free_claude_code/config/model_catalog_mapping.py` — an explicit, frozen
  mapping from FCC provider ids to models.dev provider ids, based on the table in the
  analysis (`nvidia_nim` → `nvidia`, `open_router` → `openrouter`, `together` →
  `togetherai`, `gemini` → `google`, `novita` → `novita-ai`, `fireworks` → `fireworks-ai`,
  `github_copilot` → `github-copilot`, `azure_openai` → `azure`, `alibaba_cloud` →
  `alibaba`, `opencode_zen` and `opencode_go` → `opencode`, plus the direct matches).
- `src/free_claude_code/application/model_titles.py` — accept an optional catalog snapshot
  and use it between the curated table and the heuristic.
- `src/free_claude_code/runtime/provider_manager.py:348` — schedule the background catalog
  refresh next to the existing model-list refresh pass, so the refresh never runs inside a
  request.
- `src/free_claude_code/runtime/bootstrap.py:70` — wire the catalog source into the runtime
  construction.

**Tests.**

- New `tests/config/test_model_catalog_mapping.py`: every mapped FCC provider id exists in
  `PROVIDER_CATALOG`; every models.dev provider id is a known catalog provider id; no
  provider maps to two different catalog providers.
- `tests/application/test_model_titles.py` (extend): the catalog title is used when the
  curated table has no entry; the mapping is applied per provider; two different providers
  exposing the same model id get their own titles.
- `tests/runtime/` (extend): the background refresh does not delay the first model-list
  response.

**Acceptance.**

- A model title never comes from a catalog entry belonging to a different provider.
- A catalog outage changes nothing observable except the title source.

**Effort.** 2 days.

### S2.3 — Settings and operational controls

**Goal.** Give operators control over the external catalog access.

**Changes.**

- `src/free_claude_code/config/settings.py` — add settings with the project prefix:
  - `FCC_MODEL_CATALOG_SOURCE` (default `models.dev`, allowed values `models.dev` and
    `none`): `none` disables the external catalog entirely and leaves curated plus
    heuristic titles;
  - `FCC_MODEL_CATALOG_URL` (default `https://models.dev/api.json`): the catalog endpoint.
- The CLI doctor output (`cli/doctor.py`) reports the effective source, the cache path, the
  cache age, and the last refresh outcome.
- README — a "Model display names" section explaining the resolution order, the cache, the
  TTL, and the `none` escape hatch.

**Tests.**

- `tests/config/` (extend): the settings parse, validate, and default correctly; an invalid
  source value raises a configuration error; `none` disables the external lookup.
- `tests/cli/` (extend): the doctor output contains the effective source and the cache age.

**Acceptance.** An operator can disable all external catalog traffic with one setting, and
the doctor command states whether the descriptive titles are complete, degraded, or absent.

**Effort.** 1 day.

---

## Wave 3 — Client-visible presentation

### S3.1 — Advertise the provider attribution as a description

**Goal.** Give the flat Claude Code picker the provider context that it cannot group.

**Changes.**

- `src/free_claude_code/api/model_catalog.py:57` — add an optional `description` field to
  `ModelResponse`.
- `src/free_claude_code/api/model_catalog.py:171`–`:203` — populate `description` for the
  provider-backed rows in the `claude` and `claude-desktop` views with the provider display
  name, and keep the existing no-thinking wording consistent with the title.
- `src/free_claude_code/api/model_catalog.py:206`–`:261` — populate `description` in the
  `messages` and `responses` views.
- `src/free_claude_code/api/model_catalog.py:147`–`:168` — keep the Muse envelope consistent
  with the new description.
- Native Anthropic passthrough rows keep their current label and description.

**Tests.**

- `tests/api/test_model_listing.py` (extend):
  - each provider-backed row carries a description naming its provider;
  - the description is absent for native passthrough rows if none is defined;
  - `response_model_exclude_none` still omits the field when it is empty;
  - the ids of every row are identical to the Wave 0 baseline.
- `tests/core/test_desktop_model_ids.py` (extend): the Desktop view ids are unchanged and
  carry the same descriptions as the Claude view.

**Acceptance.**

- The Claude Code picker shows `Nemotron 3 Ultra 550B A55B` with the provider underneath,
  and `NVIDIA NIM` identifies the provider.
- No advertised id changed relative to the baseline.

**Effort.** 1.5 days.

### S3.2 — Claude Desktop label handling

**Goal.** Ensure the Desktop picker shows the descriptive title and never fights the user.

**Changes.**

- `src/free_claude_code/harnesses/claude_desktop_integration.py:285` — keep preserving the
  user-authored `inferenceModels` array unchanged, including `labelOverride` entries.
- Confirm that the Desktop profile receives the descriptive title through model discovery
  (`modelDiscoveryEnabled: True` at `:263`) rather than through a rewritten
  `inferenceModels` array; no rewrite of user pins is introduced.
- If the Desktop client is found to ignore discovery titles, add an explicit, opt-in
  `labelOverride` only for models FCC itself pinned, never for user entries.

**Tests.**

- `tests/harnesses/test_claude_desktop_integration.py` (extend): a profile with user
  `inferenceModels` and `labelOverride` entries is unchanged after refresh, reconnect, and
  credential rotation.
- `tests/runtime/test_integration_startup.py` (extend): the same guarantee through runtime
  startup.

**Acceptance.** User-owned Desktop pins survive every refresh cycle unchanged.

**Effort.** 1 day.

### S3.3 — Admin UI and Codex catalog consistency

**Goal.** Make every FCC surface show the same descriptive titles.

**Changes.**

- `src/free_claude_code/api/admin_routes.py:539` — the Admin API already publishes
  `model_labels` from the application inventory; confirm no change is needed and add a test
  that the labels carry the descriptive titles.
- `src/free_claude_code/api/admin_static/admin.js:1762` — no change expected; the selector
  consumes `model_labels` as-is. Adjust only if the longer titles overflow, and only with a
  layout change.
- `src/free_claude_code/runtime/codex_catalog.py:23` — the Codex catalog inherits the title
  from the inventory; confirm the generated file carries the descriptive titles.

**Tests.**

- `tests/api/test_admin.py` (extend): `model_labels` values are the descriptive titles.
- `tests/runtime/test_codex_catalog.py` (extend): the generated catalog carries the
  descriptive titles and unchanged model ids.

**Acceptance.** The Admin selector, the Codex catalog, and the client pickers show the same
titles for the same models.

**Effort.** 1 day.

---

## Wave 4 — Hardening and release

### S4.1 — Failure-mode coverage and contract declaration

**Goal.** Prove the feature cannot degrade routing, and register it in the feature manifest.

**Changes.**

- `smoke/features.py` — declare the feature and its contract test owners, as required by
  `tests/contracts/test_feature_manifest.py:28`.
- `tests/contracts/test_import_boundaries.py` — assert the new modules do not create a cycle
  and that the catalog source stays inside `providers/` while the resolver stays inside
  `application/`.
- Add a contract test asserting that no title ever reaches a routing decision: the routing
  candidate list for a given configuration is identical with the catalog source present,
  absent, and stale.

**Tests.**

- The feature manifest test passes with the new entry.
- The routing-invariance test fails if any step leaks a title into an id or a candidate
  list.

**Acceptance.** The feature is declared, the boundaries hold, and routing invariance is
enforced by a test rather than by review.

**Effort.** 1 day.

### S4.2 — Documentation and release notes

**Goal.** Publish the contract of the feature.

**Changes.**

- `README.md` — the "Model display names" section from S2.3, extended with the resolution
  order, the examples for the flagship models, and the behavior when the catalog is
  unreachable.
- `docs/model-display-names-analysis.md` and `docs/model-display-names-implementation-plan.md`
  — updated to reflect the shipped behavior, and referenced from `CONTRIBUTING.md` under
  "Project Documentation" (`:56`–`:59`).

**Acceptance.** A reader can predict the label of any model without reading the source.

**Effort.** 0.5 day.

---

## Traceability Matrix

| Analysis finding | Plan step |
| --- | --- |
| Label defaults to the raw reference (§2.1) | S1.1, S1.3 |
| Two facts needed: title and provider (§5.2) | S1.1, S3.1 |
| Ids and routing are invariant (§2.3) | S0.1, S1.1, S3.1, S4.1 |
| Claude Code picker is flat, no groups (§3.1) | S3.1 (provider in `description`) |
| Desktop delivers titles through discovery (§3.2) | S3.2 |
| Upstream listings give ids only (§4.1) | not used as a title source |
| Curated table is a fallback, not the primary (§4.2) | S1.2 |
| models.dev schema and coverage (§4.3) | S2.1, S2.2 |
| Catalog license check open (§4.3) | S2.1 (runtime consumption), S2.3 (opt-out) |
| Resolution order (§6) | S1.1, S1.2, S2.2, S1.3 |
| Risks and mitigations (§7) | S2.1, S2.3, S4.1 |
| Admin and Codex inherit the label (§2.4) | S3.3 |

## Effort Summary

| Wave | Steps | Estimate (days) |
| --- | --- | --- |
| 0 — Baseline | S0.1 | 0.5 |
| 1 — Application resolution | S1.1, S1.2, S1.3 | 3.5 |
| 2 — External catalog | S2.1, S2.2, S2.3 | 5 |
| 3 — Client presentation | S3.1, S3.2, S3.3 | 3.5 |
| 4 — Hardening | S4.1, S4.2 | 1.5 |
| **Total** | 10 steps | **14** |
