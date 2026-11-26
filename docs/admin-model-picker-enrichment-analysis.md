# Admin Model Picker Enrichment Analysis

Status: implemented for the initial Admin scope and the approved Wave 4 catalog expansion
Input: [`model-picker-info-enrichments.md`](model-picker-info-enrichments.md), [`model-picker-metadata-research.md`](model-picker-metadata-research.md), and live verification of the local Admin server
Audience: Admin UI, API, model metadata, and configuration maintainers

Related documents:

- [`admin-model-picker-enrichment-implementation-plan.md`](admin-model-picker-enrichment-implementation-plan.md)
- [`model-display-names-implementation-plan.md`](model-display-names-implementation-plan.md)
- [`claude-terminal-model-display-names-implementation-plan.md`](claude-terminal-model-display-names-implementation-plan.md)

> **Implementation update — 2026-11-20.** Wave 4 now retains provider-scoped models.dev facts in
> cache schema v2, exposes them through the additive `catalog` namespace, and renders compact
> options plus a selected detail card. Solid badges remain provider/ModelGlot facts; dashed badges with
> visible `Catalog` text are declarations for the exact hosting-provider row, never runtime
> guarantees. Runtime facts win conflicts. Pricing is not retained or displayed.
>
> **UX refinement — 2026-11-22.** Provider identity reuses the display names and packaged
> `logo_filename` assets already shown on the Admin Providers screen; models.dev logos are not
> downloaded for providers. Capability/limit facts use meaningful static SVG icons, and the
> canonical reference is no longer rendered in visible model information: it remains only in
> component state, data attributes, search, and Apply payloads.

---

## Executive Summary

The Admin model picker already has two useful foundations:

1. `/admin/api/models` resolves a display title for every canonical provider model.
2. `ModelGlotModelCombobox` renders a searchable list of those titles.

The picker does not currently expose that title in the selected state because the visible input always contains the canonical routing value, for example `nvidia_nim/minimaxai/minimax-m3.1-flash`. The canonical value is also the persistence and routing contract, so replacing it with a title would break saved configuration and provider routing.

The recommended design is to keep the canonical value as the field's authoritative value and add a separate presentation layer:

- the visible input shows the display title;
- the canonical value is preserved in component state and a data attribute;
- a selected-model summary shows the provider, canonical reference, and provider-authoritative capability badges;
- the dropdown options use the same title-first presentation;
- unknown values remain valid and are displayed as their canonical reference.

The Admin API should retain its existing `models` and `model_labels` fields for compatibility and add a structured `model_details` map keyed by canonical model ID. The initial release should use provider metadata as the source of truth for badges and models.dev only for human-oriented descriptions. Numeric limits from models.dev must not be promoted to provider limits unless the provider confirms them.

## Ground Rules

- Do not change the canonical routing value or the meaning of the persisted `MODEL` setting.
- Do not replace the visible input value with a display title without an explicit canonical-value channel.
- Do not infer unknown capabilities, limits, prices, modalities, or release dates.
- Do not promote a default fallback to a provider-authoritative limit.
- Do not remove the current API fields; add structured data compatibly.
- Keep the Admin and CLI model-label behavior aligned with the shared title catalog.
- Include automated coverage for value separation, keyboard behavior, API contracts, and configuration persistence.

---

## 1. Current State

### 1.1 Admin API contract

`GET /admin/api/models` currently returns:

- `models`: a list of canonical provider model identifiers;
- `model_labels`: a map from canonical identifier to resolved display title.

Live verification on 2026-11-16 against `http://127.0.0.1:8082` confirmed the selected configuration and title mapping:

```text
MODEL = nvidia_nim/minimaxai/minimax-m3.1-flash
model_labels["nvidia_nim/minimaxai/minimax-m3.1-flash"] = "MiniMax-M3.1-Flash"
```

The endpoint is already capable of resolving titles for custom and catalog-backed models. It does not currently expose structured provider metadata, capability facts, source descriptions, or provenance.

Relevant code:

- `src/free_claude_code/api/admin_routes.py`
- `src/free_claude_code/api/admin_static/admin.js`
- `src/free_claude_code/application/model_titles.py`
- `src/free_claude_code/config/model_title_overrides.py`
- `src/free_claude_code/providers/model_catalog_source.py`

### 1.2 Model combobox value behavior

`ModelGlotModelCombobox` writes the selected canonical identifier to `input.value`. The selected option label is derived from the shared title map, but it is not retained as the selected display value.

The Admin editor reads the field with `readFieldValue`. For model fields, that currently means the raw `input.value`. The fallback editor also uses the raw input value when it constructs the saved configuration.

Consequently, the canonical identifier currently serves three roles at once:

1. visible editable text;
2. persisted configuration value;
3. identity used to compare selections and detect changes.

A title-first display requires separating at least the first two roles.

### 1.3 Provider metadata availability

`ProviderModelInfo` already records provider-authoritative facts such as:

- reasoning support;
- supported input modalities;
- provider context window;
- provider maximum output tokens.

`CatalogModel` can also represent reasoning, modalities, context window, and output limits. However, the Admin model-options projection currently focuses on routing identity and labels. It does not construct a presentation-safe detail contract.

The live MiniMax provider data is an important boundary case:

- provider context: unknown;
- provider output limit: unknown;
- provider modalities: unknown;
- reasoning support: unknown.

The catalog can provide a default context window of `200000`, but that value is a fallback rather than a provider-confirmed MiniMax limit. It must not be rendered as an authoritative "200K context" badge.

### 1.4 models.dev metadata

The reduced models.dev cache already preserves the provider, display name, and model description. The title resolver currently consumes only the name and discards the cached description. The reduced cache does not retain capability flags, numeric limits, cost, status, release date, or the other structured fields.

The current models.dev record for MiniMax M3.1 Flash includes, among other values:

- purpose description referring to a 1M context;
- structured context limit `262144`;
- structured output limit `262144`;
- reasoning, tools, and structured output enabled;
- text, image, and video input modalities;
- cost `0`;
- release date `2026-10-19`.

These values are useful research input, but they are not equivalent to provider-authoritative runtime facts. They must be labeled as catalog metadata and must not contradict provider data.

---

## 2. Requirement Decomposition

| Requirement | Current support | Gap |
|---|---|---|
| Readable selected model title | Available in API and dropdown | Selected input still shows canonical ID |
| Provider identity | Available separately from model selection | Not shown next to the selected model |
| Human-oriented description | Partly available from models.dev | Reduced cache discards it; no Admin contract |
| Canonical reference | Available in input | Becomes less discoverable after display enrichment |
| Capability badges | Provider metadata exists for some models | No structured Admin projection or formatter |
| Numeric context/output badges | Provider metadata and catalog metadata exist | Conflicting/unknown semantics are not encoded |
| Search by title | Supported | Search should also include canonical ID and provider |
| Manual custom model | Supported | Must continue to work with display/canonical separation |
| Optional model (`None`) | Supported | Must preserve the special value |
| Saved configuration compatibility | Canonical value is saved | Must remain unchanged after UI redesign |

---

## 3. Source-of-Truth and Precedence

The picker should distinguish three classes of information.

### 3.1 Routing identity

Canonical provider model IDs are authoritative routing values. They are produced by the provider/model catalog and consumed by configuration persistence and provider execution.

Rules:

- the canonical value must never be inferred from a display title;
- the canonical value is always the saved value;
- the canonical value must be included in the selected summary for verification.

### 3.2 Provider-authoritative facts

Provider metadata is the default source for runtime capability and limit badges.

Rules:

- a badge is shown only when the corresponding provider fact is present and true;
- false and unknown are not rendered as equivalent capabilities;
- unknown context/output limits are omitted rather than replaced with catalog defaults;
- provider metadata wins over catalog metadata when both explicitly exist and conflict.

### 3.3 Catalog-derived context

models.dev and curated overrides are useful for:

- purpose descriptions;
- human-readable model identity;
- supplementary badges only when clearly labeled and policy-approved.

Rules:

- a catalog value must not be presented as a provider-confirmed limit;
- marketing text such as "1M context" must not be parsed into a structured limit;
- a structured catalog limit and a marketing description can disagree; the structured field is authoritative for the catalog badge, but it still needs explicit catalog provenance;
- a missing cost is unknown, not zero;
- an explicit zero cost must not be labeled "free" without a product decision;
- modalities unsupported by the Admin request contract are omitted.

---

## 4. Recommended UX

### 4.1 Selected state

The selected area should show, in order:

1. **Display title** — prominent, for example `MiniMax-M3.1-Flash`.
2. **Provider badge** — for example `NVIDIA NIM`.
3. **Purpose description** — optional plain text from a curated or catalog description.
4. **Canonical reference** — secondary, copyable where useful, for example `nvidia_nim/minimaxai/minimax-m3.1-flash`.
5. **Authoritative badges** — only facts confirmed by provider metadata, such as `Reasoning` or `Image input`.

The selected area must remain readable when no structured details are available. In that case, it shows only the title and canonical reference.

### 4.2 Dropdown options

Each option should preserve a compact title-first layout:

```text
MiniMax-M3.1-Flash                 NVIDIA NIM
General-purpose model ...
nvidia_nim/minimaxai/minimax-m3.1-flash
```

Badges may be appended on wide screens and stacked below the title on narrow screens. The option must never rely on color alone.

### 4.3 Editing and custom models

The field remains editable.

- Selecting a known model sets the canonical value and displays its title.
- Focusing or pressing the standard replacement shortcut allows the user to type a new canonical model ID.
- A typed value that does not match a known model remains a valid canonical value and is displayed unchanged.
- The title and provider summary are cleared or marked unknown until the value matches a known model.
- `None` remains the special optional value used by the Admin editor.

This behavior avoids a hidden canonical channel while allowing users to recover from an accidental selection.

### 4.4 Accessibility

- The input retains a concise accessible name.
- The canonical value is exposed through a description element associated with the input.
- Option identity is available to assistive technology even when decorative badges are present.
- Keyboard navigation, focus restoration, active-descendant behavior, and escape handling remain unchanged.
- Description and badge text meet contrast requirements.
- A narrow viewport produces stacked content without horizontal clipping.

---

## 5. Architecture Options

### Option A — Replace the input value with the display title

Rejected.

This is the smallest visual change but breaks the persistence and routing contract. The title cannot be resolved back to a canonical provider model reliably, especially for custom entries.

### Option B — Overlay a title on the input and keep the canonical value underneath

Rejected.

This preserves the value but introduces duplicate focusable or visually overlapping elements, synchronization problems, and fragile screen-reader behavior. It is also difficult to make robust for editable custom values.

### Option C — Explicit canonical/display separation in the combobox

Recommended.

The component keeps both values:

- the visible input holds the display title for a known selection;
- the component stores the canonical value in its state and in a data attribute;
- the Admin's read path obtains the canonical value through the component API;
- unknown values remain visible as canonical IDs.

The approach preserves compatibility, supports keyboard and screen-reader use, and creates a clear boundary for enriched presentation.

### Option D — Separate visible title input and hidden canonical input

Not recommended for the initial implementation.

This is a valid fallback if component state and data attributes prove insufficient, but it adds a second form control, changes focus and tab order, and increases the amount of DOM synchronization that must be tested.

---

## 6. Proposed API Contract

The existing response remains unchanged:

```json
{
  "models": ["nvidia_nim/minimaxai/minimax-m3.1-flash"],
  "model_labels": {
    "nvidia_nim/minimaxai/minimax-m3.1-flash": "MiniMax-M3.1-Flash"
  }
}
```

A compatible structured map is added:

```json
{
  "models": ["nvidia_nim/minimaxai/minimax-m3.1-flash"],
  "model_labels": {
    "nvidia_nim/minimaxai/minimax-m3.1-flash": "MiniMax-M3.1-Flash"
  },
  "model_details": {
    "nvidia_nim/minimaxai/minimax-m3.1-flash": {
      "display_name": "MiniMax-M3.1-Flash",
      "provider_id": "nvidia_nim",
      "provider_label": "NVIDIA NIM",
      "description": "1M context",
      "description_source": "models.dev",
      "supports_reasoning": null,
      "input_modalities": null,
      "context_window_tokens": null,
      "max_output_tokens": null,
      "catalog": {
        "source": "models.dev",
        "source_provider_id": "nvidia",
        "canonical_model_id": "minimax/MiniMax-M3.1-Flash",
        "lab": {"id": "minimax", "label": "MiniMax", "logo_url": null},
        "provider_logo_url": null,
        "fetched_at": 1763654400,
        "stale": true,
        "last_updated": "2026-11-01",
        "reasoning": true,
        "tool_call": true,
        "structured_output": true,
        "modalities": {"input": ["text", "image", "video"], "output": ["text"]},
        "limit": {"context": 262144, "input": 262144, "output": 262144},
        "release_date": "2026-10-19",
        "status": null,
        "knowledge": null,
        "open_weights": true
      }
    }
  }
}
```

### 6.1 Contract rules

- `model_details` is keyed by the same canonical identifier as `model_labels`.
- `display_name` duplicates `model_labels` intentionally so clients can consume one typed detail object.
- `provider_id` is the normalized ModelGlot provider identifier; `provider_label` is its human-readable badge text.
- `description` is optional editorial text and `description_source` identifies its provenance.
- The `1M context` description is plain catalog text, not a structured limit and not an authoritative capability badge.
- boolean capability fields use `null` for unknown, not `false`.
- numeric limits are positive integers or `null`; default fallbacks are excluded from the Admin contract.
- `input_modalities` is a non-empty list or `null`.
- fields not applicable to a model may be omitted; clients must treat absent fields as unknown.
- `catalog` is additive and loopback-Admin-only. It identifies the models.dev source provider,
  canonical lab, fetch/update freshness, capabilities, modalities, limits, lifecycle, and logo URLs.
- Catalog facts never overwrite or backfill sibling provider/ModelGlot fields. Audio, video, and PDF are
  catalog declarations only; cost is neither retained nor exposed.
- Logo URLs are same-origin references to bounded, validated SVGs or `null`; clients use initials
  for `null` URLs and image-load failures. No Admin model-read endpoint fetches catalog or logos.
- The term *canonical value* in this document means the ModelGlot `provider_model_ref`; it is not the models.dev `canonical_model_id` field.

---

## 7. Presentation Architecture

The UI should separate data resolution from rendering:

1. the API returns canonical details with explicit nulls;
2. a small presentation helper derives badges and display strings;
3. the combobox renders the selected summary and option rows;
4. the helper contains unit-testable rules for limits, unknown values, and provenance.

Suggested helper responsibilities:

- format token counts using compact binary units such as `256K` or `1M`;
- omit unknown limits;
- select authoritative badges;
- provide the canonical reference separately from the title;
- keep provider badges visually distinct from capability badges.

This avoids scattering metadata precedence rules across `admin.js` and the combobox implementation.

---

## 8. Conflict Example: MiniMax M3.1 Flash

The observed data demonstrates why provenance is required.

| Fact | Provider | Catalog/models.dev | Admin decision |
|---|---|---|---|
| Display title | Resolved shared title | Available | Use shared title |
| Context window | Unknown | `262144` structured; description mentions 1M | Show `256K context` as a dashed Catalog declaration and `262,144 tokens` in details; keep provider field `null` |
| Output limit | Unknown | `262144` | Show `256K output` as a dashed Catalog declaration and `262,144 tokens` in details; keep provider field `null` |
| Reasoning | Unknown | Enabled | Omit provider badge; optional catalog badge behind policy |
| Tools / structured output | Unknown | Enabled | Omit from initial release |
| Input modalities | Unknown | Text, image, video | Do not expose video through the current Admin contract |
| Cost | Not a provider runtime fact | `0` | Omit from initial release |
| Release date | Not applicable | `2026-10-19` | Optional catalog badge behind policy |
| Provider description | Attribution string | Not a purpose description | Do not use as the purpose description |

Without explicit unknown semantics, the UI would incorrectly present catalog defaults and fallback values as provider capabilities.

---

## 9. Proposed Delivery Waves

### Wave 0 — Baseline and contract protection

Record the current API response, selected-state behavior, saved configuration, and relevant E2E behavior before changing the component.

### Wave 1 — Structured Admin details

Add a provider/catalog-aware detail projection to the Admin API without removing any existing field.

### Wave 2 — Canonical/display separation

Change the combobox so the known selection is displayed by title while the canonical value remains authoritative.

### Wave 3 — Enriched selected and dropdown presentation

Add the provider, description, canonical reference, and provider-authoritative badges to the picker.

### Wave 4 — Approved catalog metadata

Expand the reduced models.dev cache and add explicitly labeled catalog-derived badges with the approved provider-scoped provenance semantics.

### Wave 5 — Hardening, documentation, and release

Complete contract, accessibility, responsive, E2E, and documentation coverage.

The ordered steps, acceptance criteria, tests, dependencies, and rollback strategy are defined in [`admin-model-picker-enrichment-implementation-plan.md`](admin-model-picker-enrichment-implementation-plan.md). The initial API, canonical/display separation, enriched presentation, accessibility, regression coverage, and approved Wave 4 catalog-derived badges are implemented.

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Display title becomes the saved model | Routing breakage | Component-level canonical/display split and persistence E2E test |
| Unknown values are shown as false capabilities | Misleading users | Use `null` for unknown and omit absent badges |
| Catalog defaults become provider limits | Incorrect capacity guidance | Exclude defaults from the Admin details contract |
| Marketing description conflicts with structured catalog limit | Confusing badges | Do not parse marketing text; label catalog provenance if shown |
| Title lookup becomes stale | Wrong selected display | Refresh labels on API/model refresh and canonical selection changes |
| Rich options degrade keyboard behavior | Accessibility regression | Preserve existing combobox focus and active-option logic; add keyboard E2E |
| API response shape changes break clients | Compatibility | Keep `models` and `model_labels`; add `model_details` additively |
| Broader metadata schema creates scope creep | Delayed core delivery | Put catalog-derived badges in an optional, separately gated wave |
| The title is visually prominent but the canonical ID is hidden | Verification difficulty | Always show the canonical reference in the selected summary |

---

## 11. Out of Scope

The first delivery should not include:

- changing provider routing semantics;
- renaming or migrating existing canonical model IDs;
- parsing free-form descriptions into numeric limits;
- adding model pricing or cost estimates to the Admin UI;
- advertising modalities that the Admin request contract does not support;
- a generic metadata browser or schema editor;
- changes to model selection outside the Admin **Model Routing** card;
- full cache retention of every models.dev field unless the optional catalog wave is approved.

---

## 12. Decisions

The following decisions are recommended for implementation:

1. Keep canonical provider model IDs as the only saved routing values.
2. Use a title-first selected presentation with a visible canonical reference.
3. Preserve manual custom-model editing.
4. Add `model_details` compatibly to `GET /admin/api/models`.
5. Use `null` for unknown metadata and omit unknown badges.
6. Treat provider metadata as authoritative for capability and limit badges.
7. Exclude models.dev details from the initial badge set.
8. Keep catalog-derived badges behind a separate decision gate.
9. Use the shared model-title catalog; do not create an Admin-only title map.
10. Implement the presentation rules in a separately testable helper.

---

## 13. Implementation Record

### S0.1 baseline — 2026-11-18

The pre-enrichment fixture retained the following exact routing and presentation values:

```text
MODEL = nvidia_nim/minimaxai/minimax-m3.1-flash
model_labels["nvidia_nim/minimaxai/minimax-m3.1-flash"] = "MiniMax-M3.1-Flash"
selected input = nvidia_nim/minimaxai/minimax-m3.1-flash
Apply MODEL = nvidia_nim/minimaxai/minimax-m3.1-flash
```

Provider reasoning, input modalities, context, and output facts were unknown for this MiniMax
fixture; the fallback `200000` context was not a provider fact. Manual custom references,
optional `None`, fallback rows, locked fields, and open/Arrow/Home/End/Enter/Escape/Tab keyboard
flows were covered by the existing browser suites.

Baseline results: `tests/api/test_admin.py` passed 207 tests. The combined Admin model/provider
browser suites passed 48 tests with `-n 0`; the initial auto-xdist run passed 45 tests and hit
three existing five-second server-startup timeouts, which disappeared in the serial rerun.

### S1.1–S3.2 implementation — 2026-11-19

`CatalogModel.description` remains provider attribution. The additive `model_description` and
`model_description_source` fields carry normalized models.dev purpose text without changing
Claude/Desktop/API descriptions, titles, `provider_model_ref`, or `wire_slug`. Both Admin model
endpoints project `model_details` from the cached application inventory. Unknown reasoning,
modalities, context, and output stay `null`; no client fallback is used.

`ModelGlotModelCombobox.canonicalValue(input)` is the only Admin identity reader for model fields and
fallback editors. Component state and `data-canonical-value` retain routing identity while the
visible input holds the resolved title. Genuine typing marks a custom edit, so refreshes cannot
resurrect a previous selection. Optional `None`, locked fields, API-key association, dirty state,
Code sessions, and fallback serialization retain their prior contracts.

`model_picker_details.js` builds options and summaries with DOM nodes and `textContent`. Provider
badges are distinct from capability badges. Only provider-confirmed reasoning, image input, and
positive context/output limits produce badges; models.dev descriptions remain attributed plain
text. Responsive CSS wraps long values and stacks Model Routing at narrow widths. Accessible
option names include title and canonical identity, and selected summaries are associated through
`aria-describedby`.

### S4.1–S4.4 implementation — 2026-11-20

The models.dev background refresh now writes cache schema v2 with bounded, validated metadata for
canonical lab identity, reasoning, tool calling, structured output, input/output modalities,
provider-specific limits, lifecycle, open weights, and freshness. Legacy string and
name/description records remain readable. Invalid field types discard only the structured record,
not the legacy title/description. Unsupported fields, benchmarks, links, and pricing are ignored.

`config.model_catalog_metadata.ModelCatalogMetadata` is attached separately to
`CatalogModel.catalog_metadata`, leaving provider runtime facts unchanged. The Admin `catalog`
namespace exposes source provider, lab, freshness, exact limits, and logo URLs without network or
filesystem probes in model serialization. The NVIDIA fixtures retain MiniMax `262144/262144` and
Gemma `256000/16384`; descriptions such as `1M context` never populate numeric fields.

Provider/lab SVGs download from fixed models.dev paths only during the existing background refresh.
The store enforces a 64 KiB streaming cap, MIME and XML/SVG validation, rejects active/external
content, and publishes atomically. `/admin/catalog-logos/...` serves only cached allowlisted IDs
with `image/svg+xml`, `nosniff`, and restrictive CSP. Offline, missing, or invalid logos preserve
metadata and use initials.

The hybrid UI uses compact option rows and a selected detail card. Compact token labels divide by
1024 (`262144` → `256K`, `256000` → `250K`); detail stats show exact integers and `tokens`. Solid
badges identify provider/ModelGlot facts, dashed badges include visible `Catalog` text, and neutral
lifecycle/open-weight badges make no runtime assertion. Runtime values suppress conflicting
catalog values. The card exposes source, provider scope, update/freshness, and the runtime/catalog
explanation. No custom tooltip or interactive control is nested in listbox options.

---

## Evidence Index

- [`admin-model-picker-enrichment-implementation-plan.md`](admin-model-picker-enrichment-implementation-plan.md)
- `src/free_claude_code/api/admin_static/admin.js`
- `src/free_claude_code/api/admin_static/model_combobox.js`
- `src/free_claude_code/api/admin_static/admin.css`
- `src/free_claude_code/api/admin_routes.py`
- `src/free_claude_code/application/model_catalog.py`
- `src/free_claude_code/application/model_metadata.py`
- `src/free_claude_code/config/model_catalog_metadata.py`
- `src/free_claude_code/application/model_titles.py`
- `src/free_claude_code/providers/model_catalog_source.py`
- `src/free_claude_code/providers/model_catalog_logos.py`
- `src/free_claude_code/config/model_catalog_mapping.py`
- `src/free_claude_code/config/model_title_overrides.py`
- `tests/api/test_admin.py`
- `tests/providers/test_model_catalog_logos.py`
- `tests/providers/test_model_catalog_source.py`
- `e2e/test_admin_models.py`
- `e2e/test_admin_assets.py`
- `e2e/test_admin_providers.py`
- `docs/model-picker-info-enrichments.md`
- `docs/model-picker-metadata-research.md`
- `docs/model-display-names-implementation-plan.md`
- `docs/claude-terminal-model-display-names-implementation-plan.md`
