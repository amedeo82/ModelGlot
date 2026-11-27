# Analysis: Claude Code Terminal Model Discovery Improvements

Status: partially implemented; remaining discovery improvements proposed
Scope: `modelglot` on branch `custom/main`, aligned on 2026-11-16
Audience: maintainers and contributors

This document records the current Claude Code Terminal model-discovery behavior, explains why
terminal sessions can appear to lack the descriptive model names already available in Claude
Desktop, and defines the improvements to implement. It is the input to
[`claude-terminal-model-display-names-implementation-plan.md`](claude-terminal-model-display-names-implementation-plan.md).

Related: [`model-display-names-analysis.md`](model-display-names-analysis.md) for the title
resolution design and [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the repository quality
gate.

---

## 1. Problem Statement

ModelGlot already resolves descriptive model titles for every client projection. The
Terminal and Desktop views share the same catalog and the same title resolver, so a second
Terminal-specific title implementation would duplicate an existing feature and risk divergent
labels.

The remaining problem is operational: a Terminal session can keep showing the previous raw
`provider/model` labels even though the live ModelGlot endpoint now returns descriptive names.
The causes are the client-owned discovery cache, the opt-in nature of gateway discovery in
manual Claude Code installations, and an authentication mismatch that can make the discovery
request fail before the client reaches the model list.

The proposed work therefore improves discovery reliability, verification, and operator
guidance. It does not introduce another title source.

Current status on `custom/main`:

| Capability | State |
| --- | --- |
| Shared descriptive titles for Terminal and Desktop | Implemented |
| Launcher-provided gateway URL, token, and discovery opt-in | Implemented |
| README cache and stale-cache recovery guidance | Implemented |
| `x-api-key` acceptance on `GET /v1/models` | Proposed; the route still uses bearer-only proxy authentication |
| Isolated live Claude Code discovery verification | Proposed |
| Feature-manifest declaration for Terminal discovery | Proposed |

---

## 2. Current Architecture

### 2.1 One title path serves Terminal and Desktop

The application inventory resolves each title once and stores it in `CatalogModel`:

- title and provider description: `src/modelglot/application/model_catalog.py:31-38`;
- resolution order: `src/modelglot/application/model_titles.py:52-67`;
- provider attribution: `src/modelglot/application/model_catalog.py:145-164`.

The API then projects that inventory into client-specific views:

- `claude` is the Terminal view and `claude-desktop` is the Desktop view;
- both call `_build_claude_models_response` at
  `src/modelglot/api/model_catalog.py:141-145`;
- the shared builder attaches `display_name` and `description` at
  `src/modelglot/api/model_catalog.py:172-203`.

Only the advertised ID encoding differs:

| Surface | View | Provider model ID |
| --- | --- | --- |
| Claude Code Terminal | `claude` | `anthropic/<provider/model>` |
| Claude Code Terminal, no thinking | `claude` | `claude-3-modelglot-no-thinking/<provider/model>` |
| Claude Desktop | `claude-desktop` | `claude-modelglot/<hex(provider/model)>` |
| Claude Desktop, no thinking | `claude-desktop` | `claude-3-modelglot/<hex(provider/model)>` |

The existing test `tests/api/test_model_listing.py:199-208` already proves that the Terminal
and Desktop rows carry the same title and description.

### 2.2 Terminal discovery flow

The supported `modelglot-claude` launcher prepares the Anthropic-compatible environment:

- `ANTHROPIC_BASE_URL`: `src/modelglot/harnesses/claude.py:11-16`;
- `ANTHROPIC_AUTH_TOKEN`: `src/modelglot/harnesses/claude.py:15`;
- `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`:
  `src/modelglot/harnesses/claude.py:16`.

Claude Code then requests `GET /v1/models?limit=1000`. ModelGlot selects the default `claude`
view unless an explicit query or `X-ModelGlot-Model-View` header selects another view:
`src/modelglot/api/routes.py:405-423`.

The launcher test verifies the discovery environment at
`tests/cli/test_claude_launcher.py:23-33`.

### 2.3 Client-owned cache

Anthropic documents that Claude Code stores discovered models in:

- `~/.claude/cache/gateway-models.json` on Unix-like systems;
- `%USERPROFILE%\.claude\cache\gateway-models.json` on Windows;
- `<CLAUDE_CONFIG_DIR>/cache/gateway-models.json` when `CLAUDE_CONFIG_DIR` is set.

The cache is refreshed on Claude Code startup. Claude Code falls back to the previous cache
when discovery fails and does not perform the request in the foreground of an inference call.

A local inspection on 2026-11-14 found a cache fetched on 2026-11-12, before the descriptive
title implementation was installed. The cached rows still contained references such as
`nvidia_nim/minimaxai/minimax-m3.1-flash`. The live ModelGlot endpoint returned
`MiniMax-M3.1-Flash` with description `NVIDIA NIM` for the same routing identity. This is
direct evidence that the apparent Terminal regression was stale client state, not a missing
Terminal projection.

### 2.4 Manual launch compatibility gap

Gateway discovery is opt-in in Claude Code. `modelglot-claude` enables it, but a user who starts
`claude` directly must set `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` in the environment
or in a supported settings `env` block.

Claude Code 2.1.248 and later can send both `Authorization` and `x-api-key` on the discovery
request. ModelGlot currently protects `GET /v1/models` with `require_proxy_auth`, which accepts
only Bearer authorization:

- route dependency: `src/modelglot/api/routes.py:405-414`;
- Bearer-only implementation: `src/modelglot/api/dependencies.py:47-70`;
- existing Anthropic-compatible credential implementation:
  `src/modelglot/api/dependencies.py:73-109`.

A manual installation that provides only `ANTHROPIC_API_KEY` can therefore fail discovery
with HTTP 401 even though the same credential is accepted by the Messages endpoint. This
failure is silent from the picker: Claude Code falls back to cached or built-in models.

### 2.5 Verification gap

The repository verifies the model payload and launcher environment, but no automated test
proves that a real Claude Code process:

1. calls the gateway discovery endpoint;
2. accepts the response;
3. writes `display_name` and `description` to its gateway-model cache.

The absence of this test allowed a stale-client-cache condition to be mistaken for a missing
Terminal title feature.

---

## 3. Official Client Contract

Anthropic's gateway compatibility guide defines the relevant Terminal behavior:

| Concern | Contract |
| --- | --- |
| Discovery enablement | `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` |
| Request | `GET /v1/models?limit=1000` |
| Request timeout | 3 seconds by default; configurable from 2.1.269 |
| Credentials | `Authorization` and/or `x-api-key`, depending on version and configuration |
| Response fields | `id`, optional `display_name`, optional `description` |
| ID filter | the ID must contain `claude` or `anthropic`, case-insensitively |
| Picker title | `display_name` when it differs from the ID |
| Picker description | `description`, collapsed to one line |
| Cache | client-owned and refreshed at startup |
| Failure behavior | fall back to the previous cache or built-in models |

ModelGlot's Terminal IDs satisfy the ID filter because they start with `anthropic/` or
`claude-3-modelglot-no-thinking/`.

Source: [Claude Code gateway compatibility guide — Model discovery](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery).

Claude Code also supports a user-owned `modelPicker` setting with `label` and `description`
fields. That setting is useful for manual curation, but it is not the appropriate primary
mechanism for ModelGlot: it duplicates catalog data, can become stale, and may hide discovered
models when `replaceBuiltInOptions` is enabled.

Source: [Claude Code settings reference — modelPicker](https://code.claude.com/docs/en/settings-reference#modelpicker).

---

## 4. Required Outcomes

1. **No duplicate title implementation.** Terminal continues to consume the shared
   application catalog and the `claude` API projection.
2. **Manual discovery works with supported credentials.** A discovery request authenticated
   with `x-api-key` is accepted when the configured proxy token matches.
3. **The behavior is verified at the real-client boundary.** An opt-in live test proves that
   Claude Code consumes and caches ModelGlot's descriptive Terminal rows.
4. **Operators can diagnose stale labels.** Documentation identifies the client-owned cache,
   the correct launcher and environment, and the safe recovery procedure.
5. **Routing remains unchanged.** Authentication, cache, tests, and documentation must not
   alter advertised IDs, routing candidates, fallback order, capability facts, or provider
   requests.
6. **ModelGlot does not mutate client-owned state.** ModelGlot must not delete the Claude Code cache or
   write `modelPicker` entries without an explicit product decision.

---

## 5. Proposed Improvements

### 5.1 Accept Anthropic-compatible discovery credentials

Use `require_anthropic_proxy_auth` for `GET /v1/models`. The dependency already implements
the required precedence:

- accept a valid Bearer token;
- otherwise accept an exact `x-api-key` value;
- reject missing or invalid credentials when proxy authentication is enabled.

The change is route-scoped. Other non-Anthropic endpoints retain their existing credential
contracts.

### 5.2 Strengthen the Terminal payload contract

Keep one shared builder, but make the Terminal contract explicit in tests:

- exact `display_name` and provider `description` for a known provider model;
- no-thinking title and description suffix;
- unchanged Terminal IDs;
- unchanged Desktop IDs;
- native Anthropic passthrough behavior;
- both Bearer and `x-api-key` authentication for the discovery route.

### 5.3 Add an isolated live Claude Code discovery test

Add an opt-in E2E test that uses:

- the real Claude Code binary when available;
- an isolated `CLAUDE_CONFIG_DIR`;
- an isolated ModelGlot instance backed by a deterministic local provider;
- the existing `MODELGLOT_SMOKE_CLAUDE_BIN` prerequisite convention.

The test starts Claude Code in a non-interactive mode, waits for gateway discovery, and
asserts that the isolated cache contains a descriptive title and provider description for a
known ModelGlot model. It must skip cleanly when the Claude Code binary is unavailable and must
never use the developer's real `~/.claude` directory.

### 5.4 Document Terminal discovery and stale-cache recovery

Update the README and project documentation with:

- the shared Terminal/Desktop title behavior;
- `modelglot-claude` as the supported launcher;
- the environment required for manual launches;
- the client-owned cache location;
- the requirement to restart Claude Code to refresh discovery;
- the safe manual cache-removal procedure;
- `claude --debug` and `[gatewayDiscovery]` as the native diagnostic;
- the distinction between a stale cache, a failed discovery request, and a replaced
  `modelPicker` lineup.

### 5.5 Declare the public capability

Extend the existing `drop_in_claude_code_replacement` feature and capability manifests with
the Terminal discovery contract. No new top-level feature ID is needed: this is part of the
existing Claude Code replacement path.

---

## 6. Alternatives Considered

### 6.1 Write `modelPicker` into `~/.claude/settings.json`

Rejected. Claude Code owns that file, `modelPicker` can replace the built-in lineup, and a
generated static list would duplicate the dynamic catalog. It also creates write conflicts
with user configuration and Claude Code's own persistence.

### 6.2 Delete the gateway-model cache automatically

Rejected. The cache belongs to Claude Code, may be used by concurrent sessions, and may be the
only usable model list while the gateway is offline. The safe behavior is to refresh on the
next Claude Code startup and document an explicit manual recovery procedure.

### 6.3 Implement a separate Terminal title resolver

Rejected. Terminal and Desktop already share `CatalogModel.display_name`,
`CatalogModel.description`, and `_build_claude_models_response`. A second resolver would
produce divergent labels and violate the presentation-only design.

### 6.4 Add a strict minimum Claude Code version gate

Rejected as a separate change. The ModelGlot ID prefixes satisfy the historical ID filter, and the
installed Claude Code version supports the full contract. If a future compatibility baseline
is needed, it should be justified by a separately tested capability rather than guessed from
the newest release.

---

## 7. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Broader authentication on `/v1/models` affects non-Claude clients | A client that previously received 401 may now authenticate through `x-api-key` | Restrict the dependency to this route, preserve Bearer precedence, and cover valid, missing, and invalid credentials in route tests |
| Live Claude Code test is unstable or requires credentials | CI flakiness or secret exposure | Keep it opt-in, use an isolated config directory and local provider, require the existing Claude binary prerequisite, and never use real user settings |
| Claude Code changes its cache schema | The live test fails even though discovery works | Assert the documented public cache location and fields, keep the test opt-in, and treat the test as a compatibility signal rather than an inference contract |
| Users delete the cache while another Claude Code session is running | That session temporarily loses discovered models | Document that the cache is refreshed on the next startup and that removal is a manual recovery action only |
| `modelPicker` hides discovered models | Users report that titles are still absent | Document the `replaceBuiltInOptions` interaction and preserve user-owned settings |
| Authentication work changes routing behavior | Provider requests regress | Keep the change in an API dependency only and rerun the routing-invariance contract |

---

## 8. Out of Scope

- A second title resolver or a Terminal-only models.dev client.
- Automatic deletion or rewriting of files under `~/.claude`.
- Automatic generation of `modelPicker` options.
- Provider grouping in the Claude Code picker.
- Changes to model IDs, routing, fallback order, capabilities, or provider request payloads.
- A guarantee that the interactive picker can be fully asserted without a live Claude Code
  binary.

---

## 9. Evidence Index

| Claim | Evidence |
| --- | --- |
| The launcher enables gateway discovery | `src/modelglot/harnesses/claude.py:11-16` |
| The launcher uses Bearer authentication | `src/modelglot/harnesses/claude.py:15` |
| Terminal is the default model view | `src/modelglot/api/routes.py:405-423` |
| Terminal and Desktop share one builder | `src/modelglot/api/model_catalog.py:141-145` |
| Shared builder emits title and description | `src/modelglot/api/model_catalog.py:172-203` |
| Titles use curated, catalog, heuristic, and raw fallbacks | `src/modelglot/application/model_titles.py:52-67` |
| Terminal and Desktop labels are already compared | `tests/api/test_model_listing.py:199-208` |
| The launcher test verifies discovery enablement | `tests/cli/test_claude_launcher.py:23-33` |
| `/v1/models` currently requires Bearer only | `src/modelglot/api/dependencies.py:47-70` |
| Anthropic-compatible auth already supports `x-api-key` | `src/modelglot/api/dependencies.py:73-109` |
| The Claude feature already exists in the smoke inventory | `smoke/features.py:53-90` |
| Official discovery request and response contract | `https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery` |
| Official `modelPicker` behavior | `https://code.claude.com/docs/en/settings-reference#modelpicker` |
