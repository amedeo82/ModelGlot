# Research: Additional Model Metadata in Claude Code and Desktop Pickers

Status: proposed
Scope: `modelglot`
Audience: maintainers, contributors, and product reviewers

This document records the research on model information that could be added to the Claude Code
Terminal and Claude Desktop model pickers beyond the descriptive title and provider attribution
already implemented by ModelGlot. It is a design proposal; the metadata enrichment
is not implemented yet.

Related documents:

- [`model-display-names-analysis.md`](model-display-names-analysis.md) for the title
  resolution architecture and the presentation-only invariant;
- [`model-display-names-implementation-plan.md`](model-display-names-implementation-plan.md)
  for the shipped title implementation;
- [`claude-terminal-model-display-names-analysis.md`](claude-terminal-model-display-names-analysis.md)
  for the Terminal discovery contract and client-owned cache;
- [`hot-to-use-models.dev.md`](hot-to-use-models.dev.md) for the models.dev endpoints and SDK;
- [`admin-model-picker-enrichment-implementation-plan.md`](admin-model-picker-enrichment-implementation-plan.md)
  for the separate, implemented Admin picker. That plan does not implement the Terminal/Desktop
  metadata-enrichment proposal in this document.

---

## 1. Executive Summary

ModelGlot currently shows a human-readable model title and a provider attribution in the Claude Code
and Desktop model pickers. The next useful information is not another title source: it is a
compact model summary that helps a user answer practical selection questions before choosing a
model.

The research identifies three groups of information:

1. **Operational facts:** context window, maximum output, reasoning, and input modalities.
2. **Catalog facts:** model description, family or canonical identity, release date, lifecycle
   status, and provider-specific pricing.
3. **Research facts:** benchmarks, open-weight information, licenses, model cards, and weights
   links.

The recommended first release is an operational summary with provider attribution. The
recommended second release adds selected catalog facts after the product decisions are
resolved in a future implementation plan. Benchmarks, weights, licenses, and logos should not be part of
the picker line.

The client protocol is the main constraint. Claude Code gateway discovery consumes only:

- `id`;
- optional `display_name`;
- optional `description`.

There are no native discovery fields for prices, badges, context limits, grouping, or icons.
The `modelPicker` settings format supports `label`, `description`, and `behavesAs`, but ModelGlot
should not generate user-owned `modelPicker` entries because the catalog is dynamic and the
setting can replace the built-in lineup. Consequently, additional picker information must be
encoded as a short, human-readable `description` unless the client protocol changes.

The recommended description shape is compact and provider-specific:

```text
NVIDIA NIM · 1M context · 128K output · reasoning · vision
```

A model-specific description may be preferable when available:

```text
Frontier multimodal coding model · NVIDIA NIM · 1M context · reasoning
```

No change to advertised model IDs, routing, fallback order, capability facts used by inference,
or provider requests is required for this work.

---

## 2. Current State

### 2.1 Shared Terminal and Desktop projection

Claude Code Terminal and Claude Desktop already use the same application inventory and the
same API projection. Only the advertised ID encoding differs.

| Surface | View | Advertised ID |
| --- | --- | --- |
| Claude Code Terminal | `claude` | `anthropic/<provider/model>` |
| Claude Code Terminal, no thinking | `claude` | `claude-3-modelglot-no-thinking/<provider/model>` |
| Claude Desktop | `claude-desktop` | `claude-modelglot/<hex(provider/model)>` |
| Claude Desktop, no thinking | `claude-desktop` | `claude-3-modelglot/<hex(provider/model)>` |

Relevant implementation points:

- `src/free_claude_code/application/model_catalog.py:31-43` owns `CatalogModel`, including the
  title, provider description, reasoning flag, input modalities, context window, and maximum
  output tokens;
- `src/free_claude_code/application/model_titles.py:52-67` resolves titles through curated
  overrides, the models.dev cache, a deterministic ID heuristic, and finally the raw
  provider/model reference;
- `src/free_claude_code/application/model_catalog.py:145-164` builds each catalog model and
  currently sets `description` to the provider display name;
- `src/free_claude_code/api/model_catalog.py:172-204` builds the shared Claude and Desktop
  response;
- `src/free_claude_code/api/model_catalog.py:280-291` shows that the shared Claude projection
  currently emits only `id`, `display_name`, `description`, and `created_at`;
- `src/free_claude_code/api/model_catalog.py:233-259` shows that the Messages and Responses
  projections already serialize capability facts, but those fields are not part of the Claude
  picker contract.

### 2.2 Information already available but not shown in the picker

| Fact | Current owner | Current state |
| --- | --- | --- |
| Provider attribution | `ProviderDescriptor.display_name` | Already shown as the description |
| Reasoning support | `ProviderModelInfo.supports_thinking` | Available internally, not shown in the Claude picker |
| Input modalities | `ProviderModelInfo.input_modalities` | Available internally, not shown in the Claude picker |
| Context window | `ProviderModelInfo.context_window_tokens` | Available internally, not shown in the Claude picker |
| Maximum output | `ProviderModelInfo.max_output_tokens` | Available internally, not shown in the Claude picker |
| Detailed reasoning capability | `ReasoningCapability` | Available internally, reduced to a boolean in the shared Claude projection |
| Models.dev name and description | `ModelCatalogSource` cache | Name is used for the title; the model-specific description is currently discarded |
| Default model | `ModelCatalog.default_model_id` | Used internally and by other views, not a model property to show in the picker |

This means the first operational summary can be implemented without replacing the provider
discovery layer or changing the routing model.

### 2.3 Client rendering contract

The official Claude Code gateway compatibility guide defines discovery as
`GET /v1/models?limit=1000` and documents `id`, `display_name`, and `description` as the
consumed response fields. The description is displayed as secondary text and collapsed to one
line.

The `modelPicker` settings format supports:

- `model`;
- `label`;
- `description`;
- `behavesAs`;
- `replaceBuiltInOptions`.

There is no native `group`, `section`, `icon`, `cost`, `contextWindow`, or capability-badge
field in discovery. Unknown response fields should not be assumed to produce visible UI.

ModelGlot should continue using discovery because:

- the model inventory changes dynamically;
- the catalog already has one shared Terminal and Desktop projection;
- generated `modelPicker` entries would duplicate catalog state;
- `replaceBuiltInOptions` can hide discovered rows;
- `modelPicker` is user- or managed-owned state that ModelGlot should not overwrite.

Sources:

- [Claude Code gateway compatibility guide — Model discovery](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery);
- [Claude Code settings reference — modelPicker](https://code.claude.com/docs/en/settings-reference#modelpicker).

---

## 3. Metadata Sources

### 3.1 Provider model listings

ModelGlot already parses provider model listings for operational facts. The generic OpenAI-shaped
parser extracts:

- model ID;
- explicit reasoning facts;
- input modalities;
- context window;
- maximum output tokens.

Relevant implementation points:

- `src/free_claude_code/providers/model_listing.py:40-219` extracts provider model facts;
- `src/free_claude_code/providers/model_listing.py:269-284` distinguishes optional, required,
  absent, and disabled reasoning controls;
- `src/free_claude_code/application/model_metadata.py:9-20` stores the resulting facts.

Provider listings are authoritative for what a specific host actually serves. They are usually
inconsistent about descriptive names and model marketing descriptions, so they remain the
preferred source for operational facts rather than titles.

### 3.2 models.dev provider catalog

The `api.json` endpoint contains provider-specific model offerings. The generated v1 model
schema exposes:

| Area | Available fields |
| --- | --- |
| Identity | `id`, `name`, `description`, `family`, `canonical_model_id` |
| Capability | `reasoning`, `reasoning_options`, `tool_call`, `structured_output`, `temperature`, `attachment`, `interleaved` |
| Limits | `limit.context`, `limit.input`, `limit.output` |
| Modalities | `modalities.input`, `modalities.output` |
| Cost | `cost.input`, `cost.output`, `cost.reasoning`, `cost.cache_read`, `cost.cache_write`, `cost.input_audio`, `cost.output_audio` |
| Dates | `release_date`, `last_updated`, `knowledge` |
| Lifecycle | `status`: `alpha`, `beta`, `deprecated` |
| Model identity | `canonical_model_id` |

Provider-specific fields are important because the same canonical model can have different
prices, limits, reasoning controls, or lifecycle status at different hosts.

### 3.3 models.dev canonical catalog

The `models.json` endpoint contains model-only metadata independent of the host. It can add:

- family;
- canonical lab/model identity;
- description;
- modalities;
- base limits;
- knowledge cutoff;
- release date;
- open-weight status;
- license;
- model-card, paper, weights, and other links;
- benchmark results with metric, harness, dataset, variant, source, and date.

The `catalog.json` endpoint combines provider and canonical metadata and links them with
`canonical_model_id`.

Source: [models.dev README and API reference](https://github.com/anomalyco/models.dev/blob/dev/README.md).

### 3.4 Data completeness and trust

The dataset is community-maintained. A missing field means “not documented or unknown,” not
necessarily `false`. This distinction must be preserved:

- `supports_reasoning=None` must not be rendered as “no reasoning”;
- a missing cost must not be rendered as “free”;
- a missing modality must not be rendered as “text only”;
- a missing status must not be rendered as “stable”;
- a missing benchmark must not be rendered as zero or as a low score.

Provider facts should win when both provider metadata and models.dev provide a value. Catalog
metadata may fill a gap, but should not silently override a provider's smaller effective
context window, disabled reasoning mode, or different price.

---

## 4. Candidate Information

### 4.1 Priority P0 — operational selection facts

#### Provider attribution

Already implemented. It remains necessary because the same model can be offered by multiple
providers with different prices, limits, and availability.

#### Model-specific description

models.dev already provides a concise description for many models. ModelGlot currently stores this
value in the reduced cache but replaces it with the provider name when constructing
`CatalogModel`.

A model-specific description explains what the model is for, while provider attribution
explains where it runs. The ideal description combines both, but only if the result remains
readable.

#### Context window

The context window tells the user how much material can be held in one conversation. It is
one of the most useful differentiators between models with otherwise similar titles.

ModelGlot already has provider-reported context values. models.dev may fill missing values, but a
provider-specific effective limit must win.

#### Maximum output tokens

The output limit is useful for long generations and agentic workflows. It is already collected
by ModelGlot.

#### Reasoning

The picker already creates separate reasoning and no-thinking rows. A reasoning marker remains
useful in the description, but it must not duplicate the no-thinking suffix. The exact
supported effort values are more relevant to the effort control than to the picker summary.

#### Input modalities

Vision support is useful in a desktop coding application because it predicts whether images,
screenshots, PDFs, or other attachments can be used. ModelGlot currently models only `text` and
`image`; it must not advertise audio, video, or PDF support unless the end-to-end protocol path
preserves those modalities.

### 4.2 Priority P1 — catalog context

#### Tool calling and structured output

These facts predict agent and automation compatibility. They are useful only when documented
for the specific provider. An absent value must remain unknown.

#### Lifecycle status

`alpha`, `beta`, and `deprecated` can warn users about experimental or retired offerings.
Deprecated status is provider-specific. The product must decide whether to:

- annotate the row;
- move it to the bottom;
- filter it from discovery;
- or leave it unchanged.

Filtering is risky because it changes the visible inventory and may remove a model that the
provider still serves.

#### Indicative price

Provider-specific input, output, reasoning, and cache prices can help users choose between
equivalent models. They are list prices, not necessarily the user's contracted price, and they
may become stale.

The picker should label them explicitly as indicative or list prices and should never derive
zero cost from a missing value.

#### Release and update dates

Release and last-update dates help distinguish versions and identify recent additions. They
are less useful in the default compact line and may fit better in a detailed mode.

#### Canonical model identity

`canonical_model_id` distinguishes the underlying model from a provider-specific alias. It is
most useful when the same canonical model appears under multiple providers or several provider
IDs. The raw value is technical and should not be the default picker text.

### 4.3 Priority P2 — research and provenance

#### Benchmarks

Benchmark values are not directly comparable without the metric, harness, dataset, variant,
source, and date. They are unsuitable for the default picker description. They could support a
future comparison view if the client gains a detail surface.

#### Open weights, licenses, and weights

Open-weight status can be a compact marker for open models. License text and weights links are
more appropriate in documentation, an Admin detail panel, or a future model page.

#### Model-card, paper, and documentation links

The discovery protocol has no link field. Links cannot be made clickable in the current picker
line and should not be encoded as URLs in the description.

#### Provider and lab logos

models.dev exposes provider and lab SVG logos. The current discovery protocol has no logo
field, so logos require a client-side change and are out of scope for an modelglot-only
implementation.

---

## 5. Recommended Presentation

### 5.1 Recommended default

The default description should answer, in order:

1. Which provider serves the model?
2. What is the model's practical purpose, when a concise description exists?
3. What are the important operational limits and capabilities?

Examples:

```text
NVIDIA NIM · 1M context · 128K output · reasoning · vision
```

```text
MiniMax · frontier multimodal coding model · 1M context · reasoning
```

### 5.2 Suggested vocabulary

| Concept | Suggested label | Notes |
| --- | --- | --- |
| Provider | Provider name | Existing behavior |
| Context | `1M context` | Use compact binary or decimal units consistently |
| Output | `128K output` | Omit when unknown |
| Reasoning | `reasoning` | Omit when unknown or disabled |
| Vision | `vision` | Only for confirmed image input support |
| Tools | `tools` | Only when explicitly documented for the provider |
| Structured output | `structured output` | Usually too long for the default line |
| Beta | `beta` | Only when status is known |
| Deprecated | `deprecated` | Product decision required |
| Price | `$x in / $y out` | Detailed mode only; label as list price |

### 5.3 Detailed mode

A detailed mode could add release date, status, canonical identity, and price. It should remain
a single description string and should be opt-in initially.

A possible detailed line is:

```text
MiniMax · frontier multimodal coding model · 1M context · 512K output · reasoning · vision · tools · beta
```

Price should be kept out of this example by default because it changes frequently and can make
the line difficult to scan.

### 5.4 Length and consistency

The description should have a deterministic maximum length. The implementation should define:

- a maximum character count;
- token separators;
- the order of included facts;
- the treatment of unknown values;
- whether the no-thinking suffix remains the final suffix;
- how duplicate model rows are disambiguated.

The exact limit should be verified against the real Claude Code and Desktop renderers. The
formatter must not depend on terminal width because the same payload is used by both clients.

---

## 6. Data Ownership and Precedence

The recommended precedence for each category is:

| Category | First source | Second source | Never inferred |
| --- | --- | --- | --- |
| Title | Curated override | models.dev, then heuristic | A title must never affect routing |
| Provider | ModelGlot provider catalog | Custom provider definition | Provider identity must not be guessed from a model ID |
| Context/output | Provider listing | Curated profile, then catalog fallback with explicit policy | A missing limit is not a default real limit |
| Reasoning | Provider listing | Curated profile | Unknown is not false |
| Modalities | Provider listing and ModelGlot capability model | Catalog metadata only when equivalent | Unsupported modalities must not be advertised |
| Description | Curated override | models.dev | External text must be bounded and sanitized |
| Status | Provider listing | models.dev | Missing is not stable |
| Price | models.dev provider entry | None | Missing is not free |
| Canonical identity | models.dev | None | Never derive it from a title |
| Benchmarks | Canonical models.dev entry | None | Never display an incomplete score as authoritative |

The product must decide whether catalog fallback for operational facts is acceptable. A safer
initial release uses provider facts only and adds catalog fallback later after coverage and
accuracy have been measured.

---

## 7. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Description becomes too long | Poor picker readability | Enforce a deterministic limit and verify both real clients |
| Community metadata is stale | Misleading capability or price | Prefer provider data, include source freshness internally, and label prices |
| Missing metadata is interpreted as false | Users choose an unsuitable model | Represent unknown explicitly and omit unknown facts |
| Provider and canonical values conflict | Confusing context or capability summary | Define and test precedence; never silently override an effective provider limit |
| Same model appears through many providers | Duplicate-looking rows | Keep provider attribution and the raw routing ID stable |
| User-authored Desktop labels are overwritten | Loss of user intent | Preserve `inferenceModels` and `labelOverride` unchanged |
| Pricing causes accidental commitments | Users assume a guaranteed price | Treat all prices as indicative list prices and keep them out of the default mode |
| Benchmark scores mislead users | False model-quality comparison | Exclude benchmarks from the picker |
| Logos or richer badges are expected | Scope mismatch | Document the current protocol limit and treat visual enhancement as a separate client feature |
| Metadata changes routing behavior | Provider requests or fallback regress | Enforce a routing-invariance contract across all metadata states |

---

## 8. Alternatives Considered

### 8.1 Generate `modelPicker` entries

Rejected for the primary implementation. It duplicates the dynamic catalog, conflicts with
user-owned settings, and can hide discovery results through `replaceBuiltInOptions`.

### 8.2 Add arbitrary JSON fields to `/v1/models`

Rejected as a user-visible strategy. The model response schema can remain additive for other
clients, but the current Claude picker does not document visual rendering for those fields.

### 8.3 Replace the discovery description with a static badge string

Rejected. A short badge string can be a detailed-mode variant, but it loses the model's purpose
and becomes less readable than a natural sentence or compact metadata line.

### 8.4 Show benchmarks in the picker

Rejected. Scores require context and are not comparable across harnesses and datasets.

### 8.5 Use canonical models.dev metadata for all operational facts

Rejected as the initial approach. Canonical limits do not describe what every provider
actually serves. Provider-specific facts must remain authoritative.

### 8.6 Add a separate Desktop-only metadata path

Rejected. Terminal and Desktop already share one application catalog and one Claude
projection. A Desktop-only implementation would duplicate state and make the surfaces diverge.

---

## 9. Recommended Scope

### Recommended first release

- compact provider attribution;
- optional model-specific description;
- provider-reported context window;
- provider-reported maximum output;
- explicit reasoning support;
- confirmed image input support;
- deterministic length and ordering;
- unknown values omitted;
- Terminal and Desktop parity;
- routing invariance.

### Recommended second release

- explicit tool-calling support;
- lifecycle status;
- release or update date;
- optional indicative price;
- opt-in detailed description mode.

### Not recommended for the picker

- benchmark scores;
- licenses and full weight metadata;
- clickable links;
- logos;
- raw canonical IDs in the default line;
- audio, video, or PDF badges until ModelGlot preserves those modalities end to end.

---

## 10. Open Product Decisions

A future implementation plan must turn the following questions into explicit decision gates:

1. Should the default description show the model-specific purpose, operational facts, or both?
2. Which facts belong in the default line and which require a detailed mode?
3. May models.dev fill missing operational facts, or must the first release use provider facts only?
4. How should unknown, false, and unavailable values be represented?
5. Should the price be shown by default, only in detailed mode, or not at all?
6. Should deprecated models be annotated, reordered, filtered, or left unchanged?
7. Should canonical identity be visible only when it resolves a real ambiguity?
8. What maximum description length works in both Terminal and Desktop?
9. Should the user be able to disable external catalog metadata independently of titles?
10. Should richer metadata be exposed through `modelPicker` as an opt-in alternative?
11. Which capabilities are safe to display when they are known only from the catalog?
12. What is the rollout order between the default compact description and a detailed mode?

The document leaves the product decisions and implementation sequence open; no metadata-enrichment implementation plan or shipped API contract exists yet.

---

## 11. Evidence Index

| Claim | Evidence |
| --- | --- |
| Claude and Desktop share the same builder | `src/free_claude_code/api/model_catalog.py:141-145` |
| Shared Claude rows currently emit title and provider description | `src/free_claude_code/api/model_catalog.py:172-204`, `:280-291` |
| Catalog stores reasoning, modalities, and limits | `src/free_claude_code/application/model_catalog.py:31-43` |
| Provider facts are parsed | `src/free_claude_code/providers/model_listing.py:40-219` |
| models.dev title and description are cached but reduced | `src/free_claude_code/providers/model_catalog_source.py:125-155` |
| The models.dev cache currently stores name and description | `src/free_claude_code/providers/model_catalog_source.py:26-40` |
| Direct views already serialize capability fields | `src/free_claude_code/api/model_catalog.py:233-259` |
| Desktop preserves user-owned model pins | `src/free_claude_code/harnesses/claude_desktop_integration.py:285-295` |
| Official discovery response fields | [Claude Code gateway compatibility guide](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery) |
| Official model picker fields and precedence | [Claude Code settings reference](https://code.claude.com/docs/en/settings-reference#modelpicker) |
| models.dev endpoint roles and schema | [models.dev README](https://github.com/anomalyco/models.dev/blob/dev/README.md) |
| models.dev generated schema | [models.dev schema](https://github.com/anomalyco/models.dev/blob/dev/packages/core/src/schema.ts) |
| models.dev API endpoints | [`api.json`](https://models.dev/api.json), [`models.json`](https://models.dev/models.json), [`catalog.json`](https://models.dev/catalog.json) |
