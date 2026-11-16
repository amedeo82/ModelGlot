# Analysis: Descriptive Model Names in Client Model Pickers

Status: implemented
Scope: baseline analyzed at commit `56621010`; revalidated on `custom/main` at `12914bd`
Audience: maintainers and contributors

This document records the original analysis of descriptive model names, the available data
sources, and the protocol limits that constrained the design. The feature is now
implemented; sections describing the pre-implementation label flow are retained as the
baseline used to prove that routing and advertised IDs did not change.

The shipped implementation is documented in
[`model-display-names-implementation-plan.md`](model-display-names-implementation-plan.md).
Its current resolution order is curated override → cached models.dev metadata →
deterministic model-ID heuristic → original provider/model reference.

Related: [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the quality gate that any change
described here must satisfy.

---

## 1. Problem Statement

Before the implementation, clients that discovered models through Free Claude Code (FCC)
rendered one row per advertised model with the exact FCC routing reference, for example
`nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b` or `minimax/MiniMax-M3.1-Flash`. The shipped
presentation now uses a human-readable title such as `Nemotron 3 Ultra 550B A55B` (provider
`NVIDIA NIM`) or `MiniMax-M3.1-Flash` (provider `MiniMax`), while the routing identity,
the advertised id, and the fallback behavior remain unchanged.

Three requirements follow from that goal:

1. **Presentation only.** The change must not alter model ids, routing, fallback order,
   capability reporting, or any provider request.
2. **No network dependency in the request path.** A model-list response must be produced
   even when the machine is offline, the catalog source is unreachable, or the cache is
   cold.
3. **No licensing or redistribution assumptions.** The catalog data must be usable under
   terms compatible with the project distribution.

---

## 2. How the Baseline Label Was Produced

### 2.1 Application inventory

`application/model_catalog.py` owns the client-independent inventory.

| Element | Location | Behavior |
| --- | --- | --- |
| `CatalogModel` | `application/model_catalog.py:31`–`:43` | Carries `wire_slug`, `provider_model_ref`, `display_name`, `description`, and capability facts |
| `CatalogModel.display_name` | `application/model_catalog.py:37` | The single title field that every client projection reads |
| Title resolution | `application/model_catalog.py:145`–`:164` | `_catalog_model` resolves curated, cached, heuristic, and raw-reference titles and appends the no-thinking suffix |
| Custom provider label | `application/model_catalog.py:88`–`:102` | Custom endpoints become `<custom display name>/<model id>` |
| Ordering | `application/model_catalog.py:122`–`:142` | Rows are sorted by provider display name, then model id, so provider families appear as contiguous blocks |

In the baseline, `display_name` was the raw reference, so there was exactly one place to
change to introduce descriptive titles: the value stored in `CatalogModel`.

### 2.2 Protocol projections

`api/model_catalog.py` turns the application inventory into each client view.

| View | Location | Label source |
| --- | --- | --- |
| `claude` (Claude Code) | `api/model_catalog.py:172`–`:210` | `model.display_name` for provider-backed rows (`:184`), the raw reference for native Anthropic passthrough rows |
| `claude-desktop` | `api/model_catalog.py:141`–`:145` | Same builder with `desktop_model_id(ref)` instead of `gateway_model_id(ref)` |
| `messages`, `responses` | `api/model_catalog.py:213`–`:269` | `model.display_name`, or the raw reference for native passthrough (`:235`) |
| `muse-code` | `api/model_catalog.py:148`–`:169` | Wraps the Responses view and copies `display_name` into `metadata.muse_code.name` |

`ModelResponse` (`api/model_catalog.py:57`) has an optional `description` field, and
`/v1/models` is served with `response_model_exclude_none=True` (`api/routes.py:405`–`:423`),
so the field is additive and safe for clients that ignore it.

### 2.3 Identity that must not change

| Concern | Location | Invariant |
| --- | --- | --- |
| Claude Code id | `core/gateway_model_ids.py:27` | `anthropic/<provider/model>` |
| Claude Code no-thinking id | `core/gateway_model_ids.py:32` | `claude-3-freecc-no-thinking/<provider/model>` |
| Claude Desktop id | `core/gateway_model_ids.py:15` | `claude-fcc/<hex(provider/model)>` |
| Reference parsing | `config/model_refs.py:167` | `split_provider_model_ref` splits on the first `/` |
| Routing | `application/routing.py` | Resolves the decoded id back to the provider/model candidate list |

The no-thinking suffix is part of the label today (`application/model_catalog.py:158`,
`api/model_catalog.py:190`–`:203`) and is a routing-visible variant, not decoration. A
descriptive label must keep it.

### 2.4 Other consumers of the same label

- Admin API model options: `api/admin_routes.py:517`–`:525` publishes `model_labels` keyed by
  `provider_model_ref`; the Admin UI stores them in `state.modelLabels`
  (`api/admin_static/admin.js:1792`). Improving the application label improves the Admin UI
  selector for free, with no Admin-specific change.
- Codex catalog: `runtime/codex_catalog.py:23` publishes the same inventory to
  `~/.fcc/codex-model-catalog.json`. It is built from `CatalogModel` and therefore inherits
  the label; no separate change is required.

---

## 3. What the Clients Can Render

### 3.1 Claude Code

Claude Code reads the discovery payload and accepts `id`, `display_name`, and `description`
per model. `display_name` is the row title; `description` is secondary text. Its
`modelPicker` setting in `settings.json` accepts a flat `options[]` array with `model`,
`label`, `description`, and `behavesAs` fields, plus `replaceBuiltInOptions`. There is no
`group` or `section` field, so the picker is a flat list in both cases.

Consequence: provider grouping cannot be expressed in the Claude Code picker. The closest
available approximation is to group by ordering (FCC already orders by provider display
name, `application/model_catalog.py:79`–`:89`) and to carry the provider name in the
secondary `description` line.

### 3.2 Claude Desktop

The Desktop harness owns a `configLibrary` profile (`harnesses/claude_desktop_integration.py`).
It sets `inferenceProvider: "gateway"`, `modelDiscoveryEnabled: True`, and the gateway URL
and token (`:257`–`:264`). The harness never writes `inferenceModels` itself: it only
preserves a user-authored `inferenceModels` array, including per-model `labelOverride`
entries, across refresh and reconnect cycles (see
`tests/harnesses/test_claude_desktop_integration.py:247`–`:284` and
`tests/runtime/test_integration_startup.py:389`–`:398`).

Consequence: for Desktop, the descriptive title is delivered through the same discovery
payload (`/v1/models` with the `claude-desktop` view, selected by the
`X-FCC-Model-View` header written at `harnesses/claude_desktop_integration.py:290`).
`labelOverride` remains a user-owned pin and must not be overwritten by FCC.

---

## 4. Candidate Name Sources

### 4.1 Upstream provider listings (insufficient)

`providers/model_listing.py:40` parses OpenAI-shaped `/v1/models` payloads. It extracts the
model id (`:72`), capability tags, and token limits, and discards the upstream `name` and
`description` fields. Even if those fields were kept, the coverage would be inconsistent:
OpenAI-compatible gateways usually return only an `id`, and the ids themselves are
provider-scoped (`nvidia/nemotron-3-ultra-550b-a55b`, `anthropic/claude-sonnet-4-5`). Upstream
listings cannot be the primary source for a human-readable title.

They remain authoritative for **capability** facts (context window, output tokens, modality,
reasoning), which is exactly how FCC uses them today.

### 4.2 Curated in-repository table (partial)

FCC already owns a provider catalog with human provider names
(`config/provider_catalog.py:115`–`:143`, entries at `:147` and `:557` for `NVIDIA NIM` and
`MiniMax`). A curated per-model table would therefore be consistent with existing style and
fully offline, but it would need manual maintenance for every new upstream model, and FCC
discovers models dynamically from many providers.

Verdict: suitable as a curated override layer and as a fallback, not as the primary source.

### 4.3 models.dev (evaluated)

`models.dev` is a community-maintained catalog of AI models and providers, served as JSON
from `https://models.dev/api.json` (the full provider catalog, several megabytes) and
`https://models.dev/models.json` (the canonical model index, keyed `lab/model`). Upstream
source: the `anomalyco/models.dev` repository (branch `dev`), where provider data lives in
`providers/<provider-id>/models/<model-id>.toml`.

Schema of a provider entry, as observed live:

```
provider -> {
  id, name, npm, api, doc, env: [...],
  models: {
    "<model id>": {
      id, name, description, family, reasoning, tool_call, structured_output,
      modalities: {input, output}, limit: {context, output},
      cost: {input, output}, release_date, canonical_model_id
    }
  }
}
```

Verified examples (live query, 2026-11-12):

| Catalog key | `name` | `description` |
| --- | --- | --- |
| `nvidia/nvidia/nemotron-3-ultra-550b-a55b` | `Nemotron 3 Ultra 550B A55B` | Largest Nemotron 3 model for maximum open-weight reasoning and agent accuracy |
| `minimax/MiniMax-M3.1-Flash` | `MiniMax-M3.1-Flash` | Frontier multimodal coding model with 1M context window and tunable thinking depth |

Observed provider-id coverage against the FCC provider catalog:

| FCC provider id | models.dev provider id | Note |
| --- | --- | --- |
| `nvidia_nim` | `nvidia` | Id differs; model keys already carry the `nvidia/` prefix, matching the NIM model ids |
| `minimax` | `minimax` | Model keys match the MiniMax ids exactly |
| `open_router` | `openrouter` | Id differs; model keys are `vendor/model` and match |
| `together` | `togetherai` | Id differs |
| `gemini` | `google` | Id differs |
| `novita` | `novita-ai` | Id differs |
| `fireworks` | `fireworks-ai` | Id differs |
| `github_copilot` | `github-copilot` | Id differs |
| `azure_openai` | `azure` | Id differs |
| `alibaba_cloud` | `alibaba` | Id differs |
| `opencode_zen`, `opencode_go` | `opencode` | One catalog provider covers both FCC ids |
| `deepseek`, `groq`, `cerebras`, `siliconflow`, `nebius`, `chutes`, `cohere`, `xai`, `zai`, `huggingface`, `lmstudio`, `mistral`, `openai`, `anthropic`, `vercel`, `sambanova`, `scaleway`, `poolside`, `wandb`, `kilo`, `deepinfra`, `zenmux`, `inception` | same id | Direct match |
| `featherless`, `ollama_cloud`, `llamacpp`, `ollama`, `cloudflare`, custom providers | absent | No catalog entry; fallback required |

Two structural facts make the join straightforward for the largest providers:

1. The provider id used by models.dev is stable and can be stored as an explicit mapping
   table in FCC rather than guessed.
2. Model keys are provider-relative and match the ids FCC discovers upstream, including the
   `nvidia/…` and `vendor/model` shapes.

Operational facts that shape the design:

- `https://models.dev/api.json` responds with
  `cache-control: public, max-age=0, must-revalidate`, so HTTP caching does not reduce
  repeat traffic; a local cache with a TTL is required.
- The payload is large; only the provider entries that FCC actually uses need to be kept.

The shipped implementation consumes the catalog at runtime as a presentation-only source
and stores only a reduced cache; it does not vendor or redistribute the dataset. The
models.dev repository and per-provider terms remain relevant to attribution and future
distribution decisions.

---

## 5. Design Constraints Derived From the Analysis

1. **The label is owned in the application layer.** `CatalogModel.display_name` is the single
   place to change; the API projections, the Admin UI, and the Codex catalog inherit the
   result.
2. **Two facts are needed, not one.** A title (`Nemotron 3 Ultra 550B A55B`) and a provider
   attribution (`NVIDIA NIM`). The title belongs in `display_name`; the provider belongs in
   the new optional `description` field of `ModelResponse`, because the Claude Code picker
   is flat and cannot group rows.
3. **The id and the label must be decoupled.** `display_name` is presentation only. The
   advertised id (`anthropic/…`, `claude-fcc/<hex>`), the provider/model reference, and the
   no-thinking variant derivation stay exactly as they are.
4. **Native Anthropic passthrough rows keep their current label.** They are addressed by the
   client-visible Anthropic id (`api/model_catalog.py:183`, `:228`).
5. **Every lookup degrades to a usable label.** Missing catalog data must never remove a row
   from the inventory, never delay the response, and never fail a request.
6. **Capability facts stay with the upstream provider.** models.dev contributes names and
   descriptions only; context window, output limit, modality, and reasoning behavior remain
   sourced from the provider listing (`providers/model_listing.py:40`) and the curated
   profiles.
7. **User-owned Desktop pins win.** `inferenceModels` with `labelOverride` is preserved by
   the Desktop harness and is never rewritten by FCC.

---

## 6. Proposed Resolution Order

For one provider/model reference, the descriptive title is resolved as:

1. **Curated override** — an in-repository table for the flagship models where FCC wants a
   specific wording (for example `Nemotron 3 Ultra 550B A55B` for the NVIDIA Nemotron
   family).
2. **Catalog lookup** — the models.dev entry for the mapped provider and model key, giving
   `name` and `description`.
3. **Heuristic title from the id** — a deterministic transformation of the model id
   (`nvidia/nemotron-3-ultra-550b-a55b` → `Nemotron 3 Ultra 550B A55B`), used when no
   catalog entry exists.
4. **Raw reference** — the current behavior, used when even the heuristic would produce
   nothing useful.

The provider attribution always comes from `ProviderDescriptor.display_name`
(`config/provider_catalog.py:120`) or the custom provider definition
(`config/custom_providers.py:37`).

---

## 7. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Catalog source unreachable at startup | No descriptive names | Fetch in the background, never on the request path; serve the cached file, then the heuristic, then the raw reference |
| Stale catalog | Outdated titles after an upstream rename | Local cache with a TTL (24 h) and a background refresh; titles are presentation only, so staleness is cosmetic |
| Large payload | Slow start, memory pressure | Fetch in the background, persist a reduced map (only the providers and fields FCC uses) |
| Licensing of the dataset | Legal exposure | Verify the models.dev license and per-dataset terms before vendoring; runtime consumption is preferred, vendoring only after explicit approval |
| Model id ambiguity across providers | Wrong title attached to a row | Join on the explicit provider-id mapping table plus the provider-relative model key; never join on the model id alone |
| Label/id confusion in the picker | Users pick the wrong model | Keep the provider name visible in `description`; keep the id unchanged; never use the label for routing |
| Duplicate labels inside one provider | Ambiguous rows | Append a short disambiguator derived from the model key when two rows of the same provider resolve to the same title |
| New upstream models appear without a title | Raw reference shown | Heuristic fallback is the default, not an exception path |

---

## 8. Out of Scope

- Provider grouping or sections in the Claude Code picker: the client protocol has no such
  field (§3.1).
- Changing advertised ids, routing, or fallback behavior.
- Replacing upstream capability metadata with catalog metadata.
- Overwriting user-authored Claude Desktop `inferenceModels` or `labelOverride` entries.
- A live traffic study of model-list endpoint latency and payload size across every FCC
  provider.

---

## 9. Terminal Discovery Follow-up

The shipped title resolver is shared by Claude Code Terminal and Claude Desktop. The
remaining Terminal work concerns discovery reliability rather than another title
implementation: Anthropic-compatible discovery credentials, the client-owned model cache,
real-client verification, and operator guidance.

See
[`claude-terminal-model-display-names-analysis.md`](claude-terminal-model-display-names-analysis.md)
for the follow-up analysis and
[`claude-terminal-model-display-names-implementation-plan.md`](claude-terminal-model-display-names-implementation-plan.md)
for its execution plan.

---

## 10. Evidence Index

| Claim | Evidence |
| --- | --- |
| Title resolution and fallback order | `application/model_catalog.py:145`–`:164`, `application/model_titles.py:52`–`:92` |
| Custom providers get `<name>/<model id>` | `application/model_catalog.py:88`–`:102` |
| Ordering is grouped by provider display name | `application/model_catalog.py:122`–`:142` |
| Client views copy `display_name` | `api/model_catalog.py:172`–`:269` |
| `ModelResponse` exposes an optional `description` | `api/model_catalog.py:57`–`:96` |
| Model list is served with `exclude_none` | `api/routes.py:405`–`:423` |
| Ids are routing-visible and must not change | `core/gateway_model_ids.py:15`–`:73`, `config/model_refs.py:167` |
| Upstream listings expose only ids today | `providers/model_listing.py:40`–`:219` |
| Provider display names already exist | `config/provider_catalog.py:115`–`:143`, `:147`, `:557` |
| Admin UI consumes the application label | `api/admin_routes.py:517`–`:525`, `api/admin_static/admin.js:1792` |
| Desktop preserves user `inferenceModels` | `harnesses/claude_desktop_integration.py:285`–`:295`, `tests/harnesses/test_claude_desktop_integration.py:247`–`:284` |
| Codex catalog reuses the same inventory | `runtime/codex_catalog.py:23`–`:41` |
| Atomic file publish pattern exists | `runtime/codex_catalog.py:43`–`:62`, `config/paths.py:107`–`:110` |
| Background refresh hook exists | `runtime/provider_manager.py:348`–`:437` |
