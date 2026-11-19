# Implementation Plan: Admin Model Picker Enrichment

Status: proposed
Input: [`admin-model-picker-enrichment-analysis.md`](admin-model-picker-enrichment-analysis.md)
Audience: Admin UI, API, model metadata, configuration, and test maintainers

This plan turns the Admin model-picker analysis into ordered, reviewable steps. Each step is
one pull request. Steps within a wave are sequential when they share a contract; otherwise
the dependency table identifies the allowed order. The plan is documentation only: it does
not implement the API, combobox, or styling changes described below.

The target behavior separates two values for every known model:

```text
display value:   MiniMax-M3.1-Flash
canonical value: nvidia_nim/minimaxai/minimax-m3.1-flash
```

The canonical value is the FCC `provider_model_ref` used by configuration and routing. It is
not the models.dev `canonical_model_id` field. The display value is presentation only.

> **Implementation update — 2026-11-19.** Model Routing now qualifies known-model display labels
> as `Title (Provider)` whenever more than one provider has `status: "configured"`. The rule
> applies to Default Model, the other route selectors, and both new and existing Fallback Models
> editors, so identical titles from different providers remain distinguishable in the input and in
> the option list. With zero or one configured provider, the display label remains `Title`.
> Provider qualification is presentation only: canonical values, fallback serialization, API-key
> association, and Apply payloads are unchanged. Browser coverage verifies both the multi-provider
> and single-provider cases.

---

## 0. Ground Rules

These apply to every step in this plan.

1. **One finding focus per pull request.** Each step below proposes one pull request. Do not
   combine independent metadata, value-state, visual, and documentation findings into one
   large change.
2. **Pull request title prefixes are mandatory** for changes touching `assets/`, `scripts/`,
   `src/`, `pyproject.toml`, or `uv.lock`: exactly one of `patch: `, `minor: `, or `major: `
   followed by a description (`CONTRIBUTING.md:15`). The additive Admin behavior in this plan
   uses `minor: `.
3. **Tests accompany behavior.** Every behavioral step includes focused tests and edge cases.
   Updating existing assertions is not a substitute for coverage of the new contract.
4. **Documentation ships with code.** README and project-document updates belong in the same
   pull request as the behavior they describe. The analysis and this plan may land as an
   owner-approved documentation pull request; otherwise bundle them with step S1.1
   (`CONTRIBUTING.md:7`).
5. **Canonical identity is invariant.** No step may persist a display title, alter a provider
   model reference, change routing candidates or fallback order, or translate a title back to
   an identifier by string matching.
6. **Unknown remains unknown.** `null`, absent metadata, and unsupported values must not become
   `false`, zero, a default capability, or an authoritative badge.
7. **No fallback capabilities.** Never use `context_window_for_client()` or its default
   `200000` result to populate Admin model details. The API consumes raw catalog/provider
   facts instead.
8. **Authority controls badges.** Provider identity may use the FCC provider catalog. Runtime
   capabilities and numeric limits require provider-confirmed or explicitly curated FCC facts.
   models.dev text may be shown as attributed editorial description; its limits, capabilities,
   modalities, cost, and dates do not become authoritative badges by default.
9. **Compatibility is additive.** `models`, `model_labels`, and `failed_providers` retain their
   current meaning and shape. New data is exposed through `model_details`.
10. **Custom values remain supported.** Manual provider/model references, unknown models,
    optional `None`, locked fields, fallback rows, and provider refreshes must continue to work.
11. **No suppression shortcuts or version edits.** Follow the existing typing, import-boundary,
    feature-manifest, CI/local-parity, and release rules in `CONTRIBUTING.md`.
12. **Preserve unrelated work.** Implementation must not overwrite pre-existing changes in
    `e2e/test_admin_assets.py`, `src/free_claude_code/api/admin_static/index.html`,
    `tests/api/test_admin.py`, or any other concurrently edited file. Rebase and merge
    surgically when a planned file is already dirty.

Effort estimates are rough developer-days for a contributor already familiar with the codebase.

---

## Wave 0 — Baseline and Contract Protection

### S0.1 — Record the current routing and picker behavior

**Goal.** Establish a reproducible baseline so later steps can prove that presentation changes
do not alter saved model references or routing.

**Changes.** No production change. Record in the pull request description or a test fixture:

- the `GET /admin/api/models` response from the verified local configuration;
- `MODEL = nvidia_nim/minimaxai/minimax-m3.1-flash`;
- `model_labels["nvidia_nim/minimaxai/minimax-m3.1-flash"] = "MiniMax-M3.1-Flash"`;
- the selected input value, dropdown option text, and Apply payload before enrichment;
- behavior for a manually entered custom model, an optional model set to `None`, a fallback
  row, and a locked/process-owned field;
- the current keyboard sequence: open, ArrowDown/ArrowUp, Home/End, Enter, Escape, and Tab;
- the existing models.dev description, structured limits, capabilities, modalities, cost, and
  release date as research evidence, not as approved UI facts.

**Tests.** Run the focused existing suites without changing their assertions:

```powershell
uv run pytest tests/api/test_admin.py -q
uv run pytest e2e/test_admin_models.py e2e/test_admin_providers.py -q
```

**Acceptance.**

- The baseline distinguishes visible input text from the canonical Apply payload.
- The existing `models` and `model_labels` payload is recorded byte-for-byte for the fixture.
- The MiniMax fixture records provider facts as unknown and does not record the fallback 200K
  context as a provider limit.

**Documentation.** Link the baseline from the analysis Evidence Index when the first code step
lands.

**Dependencies.** None; this step precedes every behavioral step.

**Rollback.** Documentation/test-fixture removal only; no runtime rollback is required.

**Effort.** 0.5 day.

---

## Wave 1 — Model Details and API Contract

### S1.1 — Preserve model descriptions without changing title resolution

**Finding.** The reduced models.dev cache already stores name and description, but the title
resolver consumes only the name. The existing `CatalogModel.description` is provider
attribution, so it cannot simply be repurposed as a model-purpose description.

**Goal.** Make the cached model description available to the application inventory while
keeping title resolution, provider attribution, public model IDs, and existing client
projections unchanged.

**Changes.**

- `src/free_claude_code/application/model_titles.py` — add a small, pure metadata resolver or
  lookup helper that can return both cached values. Keep `resolve_model_title()` behavior and
  its public result unchanged. Do not perform I/O or fetch models.dev from this layer.
- `src/free_claude_code/application/model_catalog.py` — add explicit presentation fields such
  as `model_description` and `model_description_source` to `CatalogModel`; keep the existing
  `description` provider-attribution field unchanged for current consumers.
- `src/free_claude_code/application/model_catalog.py` — derive provider label separately from
  model-purpose description. Custom providers use their configured display name as the provider
  label and do not invent a model description.
- `src/free_claude_code/providers/model_catalog_source.py` — no cache-schema change is needed
  for the initial release because the reduced cache already retains `name` and `description`.
  Add or adjust tests only if the current read/write compatibility behavior is not already
  covered.
- `src/free_claude_code/config/model_title_overrides.py` — do not add MiniMax-specific context
  claims. A curated description may be added only when its wording and provenance are reviewed.

**Tests.**

- `tests/application/test_model_titles.py`:
  - title-only legacy cache entries still resolve exactly as before;
  - a cached `(name, description)` pair returns the same title and exposes the description;
  - missing, blank, or malformed descriptions become absent, never fabricated;
  - curated title precedence remains unchanged.
- `tests/application/test_model_catalog.py`:
  - model-purpose description and provider attribution remain distinct;
  - the MiniMax/NVIDIA NIM fixture exposes `MiniMax-M3.1-Flash`, `NVIDIA NIM`, and the cached
    description without changing `provider_model_ref` or `wire_slug`;
  - an absent cache leaves title fallback and provider attribution unchanged.
- `tests/providers/test_model_catalog_source.py`:
  - cache read/write preserves both name and description;
  - older title-only cache entries remain readable.

**Acceptance.**

- `resolve_model_title()` produces the same result for every baseline fixture.
- The description `1M context` can be carried as catalog text with models.dev provenance, but
  it is not parsed into a numeric context limit.
- Existing Claude/Desktop/API descriptions remain unchanged.

**Documentation.** State the distinction between provider attribution and model-purpose
description in the relevant model-catalog documentation. Bundle this plan and its analysis if
they have not already landed.

**Dependencies.** S0.1.

**Rollback.** Revert the additive application fields and resolver helper. The existing cache
format remains valid, so no cache deletion or migration is necessary.

**PR title.** `minor: Preserve model descriptions in the application catalog`

**Effort.** 1 day.

---

### S1.2 — Add `model_details` to the Admin model API

**Finding.** `/admin/api/models` exposes only canonical IDs and titles; the picker cannot render
provider, description, or capability details without inventing client-side metadata.

**Goal.** Add a typed, additive details projection keyed by the canonical provider/model
reference.

**Changes.**

- `src/free_claude_code/api/admin_routes.py` — extend `_model_options()` with a `model_details`
  map for both `GET /admin/api/models` and `POST /admin/api/models/refresh`.
- Use the application inventory as the only source. Do not add provider calls or models.dev
  requests to either endpoint.
- Emit the following fields for each known model:

| Field | Meaning |
| --- | --- |
| `display_name` | Same resolved title as `model_labels` |
| `provider_id` | FCC provider identifier |
| `provider_label` | Human-readable provider badge text |
| `description` | Optional model-purpose text |
| `description_source` | Optional provenance such as `models.dev` |
| `supports_reasoning` | Provider-confirmed boolean or `null` |
| `input_modalities` | Provider-confirmed FCC-supported modalities or `null` |
| `context_window_tokens` | Raw provider-confirmed limit or `null` |
| `max_output_tokens` | Raw provider-confirmed limit or `null` |

- Keep `models`, `model_labels`, and `failed_providers` unchanged.
- Omit unsupported modalities rather than passing through models.dev audio/video/PDF claims.
- Do not expose price, release date, tools, structured output, or models.dev limits in the
  initial authoritative badge contract. They remain candidates for the gated Wave 4.

**Tests.**

- `tests/api/test_admin.py`:
  - the existing `models` and `model_labels` values remain exactly equal to the S0.1 baseline;
  - `model_details` has the same canonical keys as `model_labels`;
  - the MiniMax fixture returns `MiniMax-M3.1-Flash`, provider `nvidia_nim`/`NVIDIA NIM`, the
    attributed description, and `null` provider capabilities/limits;
  - a provider-backed fixture with known reasoning, image input, context, and output returns
    those facts;
  - unknown booleans remain `null`, not `false`;
  - absent context does not become `200000`;
  - refresh returns the same additive shape and preserves partial-failure behavior;
  - no provider/network refresh is triggered by reading the endpoint.

**Acceptance.**

- The example response in analysis §6 is reproducible from a fixture.
- The endpoint remains a read of cached/application state.
- The new payload contains enough information for title, provider badge, description, canonical
  reference, and authoritative badges without client-side lookups.

**Documentation.** Document `model_details` and unknown-value semantics next to the Admin API
contract, without presenting it as a public non-loopback API.

**Dependencies.** S1.1.

**Rollback.** Remove `model_details` from the response. Existing consumers of `models` and
`model_labels` require no migration.

**PR title.** `minor: Add structured model details to the Admin model API`

**Effort.** 1 day.

---

## Wave 2 — Canonical and Display Value Separation

### S2.1 — Give the combobox an explicit canonical-value channel

**Finding.** `FccModelCombobox.select()` writes the canonical reference into `input.value`, and
`readFieldValue` reads that value directly. Replacing it with a title without another identity
channel would persist the title and break routing.

**Goal.** Display a resolved title while keeping the canonical provider/model reference as the
only value used for dirty-state comparison, fallback membership, and persistence.

**Changes.**

- `src/free_claude_code/api/admin_static/model_combobox.js`:
  - store canonical identity in component state and `input.dataset.canonicalValue`;
  - expose one canonical-value accessor for Admin consumers;
  - on known-model selection, set canonical state to `optionEl.dataset.value` and visible input
    text to `displayValue(canonicalValue)`;
  - on initial hydration, map a configured canonical value to its title when a label exists;
  - on genuine user typing, clear the known-selection mapping so the typed text is treated as a
    custom canonical value;
  - use canonical identity, not visible text, to find the selected option;
  - keep `optionEl.dataset.value` canonical and preserve keyboard/active-descendant behavior;
  - search across canonical reference, title, provider label, and description without changing
    the stored value.
- `src/free_claude_code/api/admin_static/admin.js`:
  - make `readFieldValue()` use the canonical accessor for model fields;
  - keep optional `None` mapped to `null` before persistence;
  - preserve `input.dataset.original` as the canonical baseline;
  - update `ModelListEditor` add/edit/provider/API-key logic to read canonical values through the
    same accessor rather than `combobox.input.value`;
  - qualify known-model display labels as `Title (Provider)` when more than one configured
    provider exists, resolving the provider display name from the canonical provider prefix; do
    not alter `model_labels` or append provider text to canonical/custom values;
  - ensure model refreshes update labels/details without overwriting a custom edit in progress.
- Do not infer a canonical value by looking up a title. Duplicate titles and unknown custom
  values must remain safe.

**State rules.**

| Interaction | Visible value | Canonical value |
| --- | --- | --- |
| Initial known model | Resolved title, with `(Provider)` when multiple providers are configured | Original provider/model reference |
| Select known option | Resolved title, with `(Provider)` when multiple providers are configured | Selected option's `data-value` |
| Type custom model | Typed text | Same typed text |
| Edit a known title | Edited text | Edited text, treated as custom |
| Optional `None` | `None` | `null` at Admin serialization |
| Unknown metadata | Canonical reference | Same canonical reference |

**Tests.**

- `tests/api/test_admin.py` static contract coverage:
  - canonical state and display text have separate code paths;
  - no persistence path reads a display label as the model ID;
  - fallback editor uses the canonical accessor;
  - no title-to-canonical reverse lookup is introduced.
- `e2e/test_admin_models.py`:
  - selecting `MiniMax-M3.1-Flash` displays that title and sends
    `nvidia_nim/minimaxai/minimax-m3.1-flash` in Apply;
  - selecting then reopening without edits produces `No changes` and no Apply payload field;
  - typing a custom reference marks the field dirty and saves the custom reference;
  - clearing/replacing a known title does not resurrect the previous canonical selection;
  - duplicate display titles select their own distinct canonical references;
  - with multiple configured providers, Default Model and Fallback Models display
    `Shared Model (OpenRouter)` and `Shared Model (Groq)` while preserving their distinct canonical
    references in fallback state and Apply;
  - with one configured provider, the same titles remain unqualified as `Shared Model`;
  - `None`, fallback add/edit, provider-specific API-key selection, and reload round trips remain
    correct;
  - Arrow/Escape/Enter/Tab behavior and focus restoration remain correct.
- `e2e/test_admin_providers.py`:
  - replace the raw-input-only assumption with assertions for both visible title and canonical
    serialization; retain a regression assertion that the provider/model reference is unchanged.

**Acceptance.**

- The displayed MiniMax title and persisted canonical value are simultaneously observable and
  different.
- Dirty state is based only on canonical values.
- Equal model titles are visibly provider-qualified whenever multiple providers are configured.
- Every existing model and fallback workflow from the baseline passes.

**Documentation.** Add a short maintainer note explaining the canonical/display invariant and
warning future consumers not to read model identity from visible input text.

**Dependencies.** S1.2 so initial and refreshed display data use the same contract. The
canonical/display mechanics may be prototyped earlier, but must not merge against an undefined
metadata contract.

**Rollback.** Revert the combobox and Admin reader changes together. Rolling back only one side
is unsafe because it can expose or persist a title as a model ID.

**PR title.** `minor: Separate display and canonical values in the Admin model picker`

**Effort.** 2 days.

---

## Wave 3 — Enriched Graphical Presentation

### S3.1 — Render title-first options and a selected-model summary

**Finding.** The current option is one monospace text node and the selected field has no place
for provider, description, canonical reference, or badges.

**Goal.** Present useful model details while keeping the canonical reference secondary and the
control editable.

**Changes.**

- Add a focused presentation helper, preferably
  `src/free_claude_code/api/admin_static/model_picker_details.js`, loaded before
  `model_combobox.js`/`admin.js` from `src/free_claude_code/api/admin_static/index.html`.
  Register the new filename in `_ADMIN_ASSET_FILENAMES` in
  `src/free_claude_code/api/admin_routes.py`; otherwise the versioned asset route will not serve
  it. Integrate with any pre-existing index changes rather than replacing the file.
- The helper converts `model_details` into a safe view model:
  - prominent title;
  - provider badge;
  - optional attributed description;
  - canonical reference as secondary monospace text;
  - capability/limit badges only for authoritative, known facts.
- `src/free_claude_code/api/admin_static/model_combobox.js` renders structured option rows using
  DOM nodes and `textContent`; never inject catalog text with `innerHTML`.
- `src/free_claude_code/api/admin_static/admin.js` renders the selected-model summary adjacent
  to the combobox and refreshes it on selection, custom input, hydration, and model refresh.
- For the MiniMax fixture:
  - show `MiniMax-M3.1-Flash` prominently;
  - show an `NVIDIA NIM` provider badge;
  - show `1M context` only as the models.dev description, never as a structured `1M` badge;
  - show the canonical reference as secondary detail;
  - show no reasoning, tools, structured-output, context, output, cost, release, or video badge
    when the only evidence is the current models.dev entry.
- Unknown/custom models fall back to title-equals-canonical presentation without empty badges or
  placeholder descriptions.

**Tests.**

- `e2e/test_admin_assets.py` and the API static-asset tests:
  - `model_picker_details.js` is served through the versioned asset route before the dependent
    scripts execute;
  - no browser page error reports a missing helper or asset.
- Helper tests through the existing browser/E2E harness:
  - authoritative known values produce the expected badges;
  - `null`, `false`, absent, and fallback values produce no positive capability badge;
  - catalog description never becomes a numeric limit badge;
  - video and other FCC-unsupported modalities are omitted;
  - long and HTML-like descriptions are rendered as text, not markup;
  - custom/unknown values produce a minimal valid summary.

**Acceptance.**

- The MiniMax selected state visibly contains title, provider, description, and canonical
  reference with the prescribed hierarchy.
- No prohibited badge appears for the MiniMax fixture.
- The helper has no routing or persistence responsibilities.

**Documentation.** Include a small UI contract/example in the Admin documentation and record
that models.dev description is editorial text rather than a confirmed runtime limit.

**Dependencies.** S2.1; rendering must not introduce another value-state implementation.

**Rollback.** Remove the helper and structured rendering while retaining S2.1's canonical/display
separation. The picker returns to title-only options without changing saved configuration.

**PR title.** `minor: Add title-first model details to the Admin picker`

**Effort.** 1.5 days.

---

### S3.2 — Style, responsive behavior, and accessibility hardening

**Finding.** Rich option content can overflow the two-column Model Routing layout and can make
the active option or accessible name ambiguous.

**Goal.** Deliver a legible, keyboard- and screen-reader-compatible picker at desktop and narrow
widths.

**Changes.**

- `src/free_claude_code/api/admin_static/admin.css`:
  - separate title, provider badge, description, canonical reference, and capability-badge
    typography;
  - replace the current all-monospace option treatment with monospace only for the canonical
    reference;
  - allow wrapping without clipping and preserve the dropdown's scroll constraints;
  - stack secondary content at narrow widths;
  - retain visible hover, active, focus, disabled, and locked states;
  - keep provider badges visually distinct from capability badges and never rely on color alone.
- `src/free_claude_code/api/admin_static/model_combobox.js` and `admin.js`:
  - preserve a concise accessible name for the input;
  - associate canonical/description text with `aria-describedby` where useful;
  - give each option an unambiguous accessible name containing its title and canonical identity;
  - mark decorative badge separators/icons hidden from assistive technology;
  - keep one active descendant and correct `aria-selected` state after filtering.

**Tests.**

- `e2e/test_admin_models.py` and `e2e/test_admin_assets.py`:
  - 1280px, 900px, and 390px layouts have no horizontal document overflow;
  - long titles, canonical references, descriptions, and badges wrap without hiding the toggle;
  - option activation and input focus remain visible;
  - accessible option names distinguish duplicate titles;
  - keyboard navigation still scrolls the active option into view;
  - reduced-motion behavior remains unchanged.
- Merge carefully with any existing asset/layout tests rather than weakening their assertions.

**Acceptance.**

- Model Routing and fallback rows remain usable at all baseline viewport sizes.
- Screen-reader output identifies both the selected model and its canonical reference without
  reading decorative badge punctuation as essential content.

**Documentation.** Record the supported responsive and keyboard behavior in the same pull
request.

**Dependencies.** S3.1.

**Rollback.** Revert the CSS/accessibility refinement only if the underlying semantic DOM remains
compatible; otherwise roll back with S3.1. Do not roll back S2.1 as part of a visual-only issue.

**PR title.** `minor: Make enriched Admin model options responsive and accessible`

**Effort.** 1 day.

---

## Wave 4 — Optional Catalog Metadata Expansion (Decision Gate)

### S4.1 — Retain additional models.dev facts only after provenance approval

**Finding.** models.dev currently reports a structured context/output limit of `262144`,
reasoning/tools/structured output `true`, text/image/video modalities, cost `0`, and release date
`2026-10-19`, while provider-live MiniMax facts are unknown and the description says `1M context`.

**Goal.** Define a separate, explicitly labeled catalog-metadata path without allowing these
values to masquerade as provider-confirmed runtime capabilities.

**Decision gate.** This step must not start until maintainers approve all of the following:

1. whether models.dev is authoritative enough for any individual badge class;
2. how catalog provenance and freshness are displayed;
3. how conflicting provider and catalog facts are resolved;
4. whether `cost: 0` has a documented meaning other than “free” (the initial UI omits cost
   regardless);
5. how FCC-supported text/image modalities are derived without promising video;
6. whether the description conflict (`1M context` versus structured `262144`) is acceptable as
   attributed editorial text or requires suppression.

**Changes if approved.**

- `src/free_claude_code/providers/model_catalog_source.py` — extend the reduced cache with a
  versioned, allowlisted subset of structured fields and source timestamp; preserve legacy cache
  reads and atomic writes.
- `src/free_claude_code/application/model_catalog.py` — keep provider facts and catalog facts in
  separate fields/namespaces.
- `src/free_claude_code/api/admin_routes.py` — expose catalog facts only with explicit source
  metadata; do not overwrite the provider-fact fields from S1.2.
- Admin presentation — show only the approved catalog badges with a visible source distinction.
  Never derive `1M` from the description, never show fallback `200000`, never translate cost
  zero to “free”, and never show video while FCC supports only text/image.

**Tests.**

- Legacy and new cache versions round-trip atomically.
- Missing catalog fields remain unknown.
- Provider facts win on conflict; a provider absence does not silently become a provider badge.
- The exact MiniMax contradictory fixture produces only the approved presentation.
- Routing, canonical IDs, and refresh behavior remain invariant.

**Acceptance.** A reviewer can identify the source and authority of every badge from the payload
and the UI.

**Documentation.** Publish the approved source-precedence table before enabling the badges.

**Dependencies.** S3.2 plus explicit product/maintainer approval. This wave is not required for
the initial title/provider/description/canonical-reference delivery.

**Rollback.** Disable the catalog-badge rendering and ignore the additive cache fields. Keep the
legacy title/description cache readable; no destructive cache migration.

**PR title.** `minor: Add provenance-aware catalog metadata to the Admin picker`

**Effort.** 1.5–2 days after the decision gate.

---

## Wave 5 — End-to-End Verification and Documentation

### S5.1 — Complete regression coverage and publish the final contract

**Goal.** Verify the combined feature against the live-shaped MiniMax scenario and leave a
maintainable contract for future Admin changes.

**Changes.**

- `e2e/test_admin_models.py` — add the integrated known-model, custom-model, fallback, refresh,
  persistence, keyboard, and narrow-viewport scenarios not already landed with earlier steps.
- `e2e/test_admin_providers.py` — verify provider setup and Model Routing still retain the same
  canonical provider/model reference after enrichment.
- `tests/api/test_admin.py` — retain focused API/static contracts without relying only on source
  string assertions for behavior already covered in the browser.
- `docs/admin-model-picker-enrichment-analysis.md` — change Status to implemented only when the
  corresponding steps have shipped; record any deferred Wave 4 decisions.
- `docs/admin-model-picker-enrichment-implementation-plan.md` — record shipped step status and
  measured verification results.
- `docs/model-picker-metadata-research.md` — repair or replace the dangling reference to
  `model-picker-metadata-implementation-plan.md` by clearly separating Terminal/Desktop research
  from this Admin-specific plan. Do not silently claim this Admin plan implements that separate
  Terminal/Desktop proposal.
- `docs/model-picker-info-enrichments.md` — cross-link this Admin work and correct its generic
  badge examples where they conflict with the authority rules.
- `CONTRIBUTING.md` — add both new documents under Project Documentation when the feature lands.
- `README.md` — add a concise Admin Model Routing description only if user-facing behavior needs
  operator explanation.

**Tests and final verification.**

```powershell
uv run pytest tests/api/test_admin.py tests/application/test_model_titles.py tests/application/test_model_catalog.py tests/providers/test_model_catalog_source.py -q
uv run pytest e2e/test_admin_models.py e2e/test_admin_providers.py e2e/test_admin_assets.py -q
uv run ruff check
uv run ty check
.\scripts\ci.ps1
```

Run the equivalent `./scripts/ci.sh` on macOS/Linux. Perform one manual verification against the
local Admin server using the MiniMax configuration and inspect both the selected state and the
actual Apply request.

**Acceptance.**

- Visible display value is `MiniMax-M3.1-Flash`.
- Canonical value everywhere in configuration, fallbacks, and Apply payloads is
  `nvidia_nim/minimaxai/minimax-m3.1-flash`.
- `models` and `model_labels` are unchanged from baseline; `model_details` is additive.
- No `1M` structured badge, fallback `200K` capability, “free” label, or video promise appears.
- Keyboard, responsive, custom-model, optional-model, locked-field, refresh, and persistence
  checks pass.
- All relevant documents link to each other and no new dangling local Markdown links remain.

**Dependencies.** S1.1–S3.2 for the initial release; S4.1 only if the optional catalog wave was
approved and included.

**Rollback.** Use the step-level rollbacks in reverse order. A documentation-only correction does
not require runtime rollback. If persistence correctness is in doubt, disable enriched rendering
and restore the canonical-input UI before release.

**PR title.** Use the prefix required by the files touched; for the combined source/test/docs
verification step, `minor: Verify and document the enriched Admin model picker`.

**Effort.** 1 day.

---

## Dependency and Sequencing Notes

| Step | Depends on | May run independently? |
| --- | --- | --- |
| S0.1 | None | Baseline only |
| S1.1 | S0.1 | No |
| S1.2 | S1.1 | No |
| S2.1 | S1.2 | Prototype only before API merge |
| S3.1 | S2.1 | No |
| S3.2 | S3.1 | No |
| S4.1 | S3.2 + product decision | Optional and separately gated |
| S5.1 | S1.1–S3.2; S4.1 if shipped | Final integration step |

The initial releasable scope is S0.1 through S3.2 plus the relevant parts of S5.1. Wave 4 must
not delay readable titles, provider attribution, description, canonical-reference visibility,
or correct persistence.

---

## Traceability Matrix

| Analysis finding / constraint | Plan step |
| --- | --- |
| Title already exists but selected input shows canonical reference | S0.1, S2.1 |
| Display and canonical values must remain separate | S2.1 |
| Equal titles from different configured providers need visible disambiguation | S2.1, S5.1 |
| Fallback editor and dirty state also consume input values | S2.1 |
| API needs structured details while `models`/`model_labels` remain stable | S1.2 |
| models.dev description is cached but discarded by title resolution | S1.1 |
| Provider badge and human-oriented description | S1.1, S1.2, S3.1 |
| Canonical reference remains visible as secondary detail | S3.1, S3.2 |
| Capability/limit badges require authority | S1.2, S3.1, S4.1 |
| Provider-live MiniMax facts are unknown | S0.1, S1.2, S3.1 |
| Fallback `200000` is not a real MiniMax limit | S1.2, S3.1 |
| Description `1M context` must not become a structured badge | S1.1, S3.1 |
| models.dev `262144`, reasoning/tools/structured output, cost, date need policy | S4.1 |
| FCC exposes only text/image; no video promise | S1.2, S3.1, S4.1 |
| Keyboard, accessibility, and responsive layout | S2.1, S3.2 |
| Existing Admin/provider E2E assertions must follow the new display contract | S2.1, S5.1 |
| Documentation cross-links and missing research-plan reference | S5.1 |

---

## Risk Register and Rollback Strategy

| Risk | Detection | Mitigation / rollback |
| --- | --- | --- |
| Display title is persisted as MODEL | Apply-payload E2E | Single canonical accessor; revert S2.1 atomically |
| Dirty state appears after opening/selecting same model | No-change E2E | Compare canonical baseline only |
| Custom model edits retain stale canonical state | Custom-edit E2E | Clear known mapping on genuine user input |
| Duplicate titles select the wrong model | Duplicate-title E2E | Show `Title (Provider)` with multiple configured providers; use option `data-value`, never reverse title lookup |
| Fallback rows save labels or lose API-key association | Fallback E2E | Update all consumers in S2.1; revert as one unit |
| Catalog/default facts become authoritative badges | MiniMax fixture tests | Provider-only badge fields; omit unknowns |
| Rich text introduces HTML injection | HTML-like-description test | DOM nodes plus `textContent`; no catalog `innerHTML` |
| Long details break Model Routing layout | 390/900/1280px E2E | Wrapping/stacking; revert visual steps independently |
| Optional catalog expansion blocks the core fix | Scope review | Keep Wave 4 explicitly optional |
| Rollback leaves mixed UI/value contracts | Rollback review | S2.1 is atomic; S3.x may revert without changing persistence |

---

## Definition of Done

A step is complete when:

1. its focused tests and edge cases pass;
2. canonical IDs, routing, fallback order, and provider requests are unchanged;
3. the listed documentation ships in the same pull request;
4. the pull-request title follows `CONTRIBUTING.md`;
5. import-boundary, feature-manifest, and other relevant contract tests pass;
6. the complete local CI sequence passes before merge;
7. the step outcome is recorded in this plan, and deferred decisions remain explicit rather than
   being presented as shipped behavior.

---

## Effort Summary

| Wave | Steps | Estimate (days) |
| --- | --- | --- |
| 0 — Baseline | S0.1 | 0.5 |
| 1 — Application metadata and Admin API | S1.1, S1.2 | 2 |
| 2 — Canonical/display separation | S2.1 | 2 |
| 3 — Graphical presentation and accessibility | S3.1, S3.2 | 2.5 |
| 4 — Optional catalog expansion | S4.1 | 1.5–2 after approval |
| 5 — Verification and documentation | S5.1 | 1 |
| **Initial total (Waves 0–3 + 5)** | **6 steps** | **8** |
| **Total including optional Wave 4** | **7 steps** | **9.5–10** |
