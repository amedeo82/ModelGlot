# Implementation Plan: Claude Code Terminal Model Discovery Improvements

Status: proposed
Input: [`claude-terminal-model-display-names-analysis.md`](claude-terminal-model-display-names-analysis.md)
Audience: maintainers and contributors

This plan improves the reliability and verification of Claude Code Terminal model discovery.
The descriptive title feature itself is already implemented and shared with Claude Desktop.
The plan therefore improves credential compatibility, real-client coverage, diagnostics, and
operator documentation without creating a second title resolver.

---

## 0. Ground Rules

These apply to every step in this plan.

1. **One finding focus per pull request.** Steps below propose one pull request each, except
   where a step explicitly requires one pull request to cover several changes that must stay
   coherent.
2. **Pull request title prefixes are mandatory.** Any change touching `assets/`, `scripts/`,
   `src/`, `pyproject.toml`, or `uv.lock` uses exactly one of `patch: `, `minor: `, or
   `major: ` followed by a description (`CONTRIBUTING.md:13-17`).
3. **Documentation ships with code.** README, CONTRIBUTING, and project-document updates land
   in the same pull request as the behavior they describe.
4. **Tests accompany behavior.** New behavior requires focused tests plus edge cases, not
   only modified existing tests.
5. **No suppression shortcuts.** `# type: ignore`, `# ty: ignore`, and
   `from __future__ import annotations` remain banned (`CONTRIBUTING.md:54`).
6. **CI/local parity.** Any new local check must be mirrored in `scripts/ci.sh`,
   `scripts/ci.ps1`, and `.github/workflows/tests.yml`, with parity covered by
   `tests/scripts/test_ci_scripts.py`.
7. **Contract invariants hold.** New or changed modules must respect
   `tests/contracts/test_import_boundaries.py` and the feature/capability manifests.
8. **No version edits.** Versions are computed and published by the release pipeline.
9. **Presentation-only scope.** No step may change advertised model IDs, provider/model
   references, routing candidate lists, fallback order, capability facts, or provider request
   payloads.
10. **Client-owned state remains untouched.** FCC must not delete, rewrite, or synthesize
    files under `~/.claude` unless a later proposal explicitly approves that product
    decision.

Effort estimates are rough developer-days for a contributor already familiar with the
codebase.

---

## Wave 0 — Baseline

### S0.1 — Record the Terminal discovery baseline

**Goal.** Establish the exact state before changing authentication or verification.

**Changes.** No source change. Record in the pull request description:

- `GET /v1/models?limit=1000` with `Authorization: Bearer <proxy-token>`;
- the same request with `x-api-key: <proxy-token>`;
- the same request without credentials;
- the Terminal payload for one NVIDIA NIM model, one MiniMax model, one custom-provider
  model, and one native Anthropic model;
- the corresponding `claude-desktop` payload;
- the current Claude Code gateway-model cache location, timestamp, and representative
  `display_name` values;
- the installed Claude Code version and whether it supports gateway discovery.

**Expected baseline.**

- Bearer authentication succeeds.
- `x-api-key`-only authentication returns HTTP 401 when proxy authentication is enabled.
- The Terminal and Desktop views already contain the same descriptive titles and provider
  descriptions.
- IDs are the routing identities documented in
  [`claude-terminal-model-display-names-analysis.md`](claude-terminal-model-display-names-analysis.md).

**Acceptance.** The baseline demonstrates that the remaining defect is discovery compatibility
and verification, not a missing Terminal title projection.

**Effort.** 0.5 day.

---

## Wave 1 — Discovery credential compatibility

### S1.1 — Accept `x-api-key` on the model-discovery route

**Goal.** Let Claude Code authenticate discovery with the credential shapes it officially
supports.

**Changes.**

- `src/free_claude_code/api/routes.py:401-411` — use
  `require_anthropic_proxy_auth` for `GET /v1/models`.
- Keep `require_proxy_auth` on endpoints that are not Anthropic-compatible. Do not broaden
  the authentication contract of unrelated routes.
- Do not change the response body, view selection, model IDs, title resolution, or routing.

**Tests.**

- Extend `tests/api/test_model_listing.py`:
  - a valid Bearer token returns HTTP 200;
  - a valid `x-api-key` returns HTTP 200;
  - a valid Bearer token takes precedence over a conflicting invalid `x-api-key`;
  - missing credentials return HTTP 401;
  - an invalid `x-api-key` returns HTTP 401;
  - an invalid Bearer token returns HTTP 401 even when `x-api-key` is valid;
  - authentication remains disabled when `proxy_auth_enabled` is false.
- Extend `tests/api/test_dependencies.py` only if route-level coverage does not fully expose
  the existing dependency behavior. Do not duplicate dependency tests without a distinct
  failure mode.

**Acceptance.**

- `fcc-claude` remains compatible because it uses Bearer authentication.
- Manual Claude Code installations using `ANTHROPIC_API_KEY` can complete discovery.
- No route other than the Anthropic-compatible discovery route changes credential
  acceptance.

**Effort.** 0.5 day.

### S1.2 — Preserve the public authentication contract

**Goal.** Ensure the route change does not contradict the repository's capability manifest or
smoke expectations.

**Changes.**

- `smoke/capabilities.py:129-139` — refine the bearer-only capability wording so the
  Bearer-only contract remains attached to non-Anthropic routes, and declare the Anthropic
  discovery route's accepted credential shapes if the manifest structure requires it.
- `smoke/features.py:53-90` — retain `drop_in_claude_code_replacement`; do not add a new
  top-level feature for an existing Claude Code path.

**Tests.**

- Extend the manifest contract tests affected by the wording and ownership change.
- Run the existing authentication, route, and smoke-manifest tests.

**Acceptance.** The manifests describe both Bearer-only and Anthropic-compatible route
contracts without claiming that every FCC endpoint accepts `x-api-key`.

**Effort.** 0.5 day.

---

## Wave 2 — Terminal discovery contracts

### S2.1 — Make the Terminal payload contract explicit

**Goal.** Prove that the Terminal receives descriptive titles and provider descriptions
without changing any routing identity.

**Changes.**

- `tests/api/test_model_listing.py:146-208` — strengthen the Terminal and Desktop assertions
  into an explicit shared contract.
- No production change is expected. If the test exposes a presentation defect, fix it in the
  application catalog or shared Claude projection, not in a Terminal-specific branch.

**Tests.**

The contract must assert:

- the Terminal and Desktop views have the same `display_name` and `description` for the same
  provider/model reference;
- a known model has the expected descriptive title and provider attribution;
- the no-thinking row differs only by the ` (no thinking)` suffix;
- the Terminal IDs remain `anthropic/<provider/model>` and
  `claude-3-freecc-no-thinking/<provider/model>`;
- the Desktop IDs remain the existing hex-encoded IDs;
- native Anthropic passthrough rows retain their current label and description policy;
- custom-provider titles retain their current provider-specific shape;
- the title remains independent from routing.

**Acceptance.** A reviewer can prove that Terminal and Desktop presentation is shared and
that all routing-visible IDs remain unchanged.

**Effort.** 0.5 day.

### S2.2 — Strengthen launcher environment coverage

**Goal.** Prove that every supported Terminal launch path enables discovery and supplies a
credential.

**Changes.**

- `tests/cli/test_claude_launcher.py:23-33` — retain the existing environment assertions.
- `tests/cli/test_entrypoints.py` and `tests/cli/test_managed_claude.py` — verify that the
  installed launcher and managed Claude integration continue to set
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, `ANTHROPIC_BASE_URL`, and
  `ANTHROPIC_AUTH_TOKEN`.
- `tests/harnesses/test_claude_integration.py` — retain coverage that user-owned settings
  are preserved while the FCC discovery entry remains correct.

**Tests.**

Cover:

- `fcc-claude` sets discovery to `1`;
- inherited `ANTHROPIC_*` variables cannot replace the FCC base URL or token;
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is removed for supported discovery behavior;
- the managed integration preserves unrelated user environment entries;
- a direct `claude` launch is documented as requiring the same opt-in variable.

**Acceptance.** Every FCC-owned Terminal launch path enables discovery, and no user-owned
setting is silently removed.

**Effort.** 0.5 day.

### S2.3 — Add an isolated live Claude Code discovery test

**Goal.** Verify the real client consumes and caches FCC's descriptive Terminal rows.

**Changes.**

- New `e2e/test_claude_model_discovery.py` — start an isolated FCC instance backed by the
  existing deterministic local-provider test infrastructure.
- Use `FCC_SMOKE_CLAUDE_BIN` when present, consistent with the existing Claude CLI smoke
  convention (`smoke/features.py:53-90`).
- Set an isolated `CLAUDE_CONFIG_DIR` for every launched Claude Code process.
- Use an isolated model and a minimal deterministic prompt.
- Wait for the documented gateway-model cache under the isolated config directory and assert
  that the expected model has a descriptive `display_name` and a provider `description`.
- Assert that the raw provider/model reference is not the cached display title for the
  selected known model.
- Never read or write the developer's real `~/.claude` directory.

**Tests.**

The live test must:

- skip cleanly when the Claude Code binary is absent;
- skip when a required local-prerequisite setting is absent;
- fail on HTTP 401, 404, timeout, or redirect from discovery;
- fail when the cache contains the old raw label for the selected model;
- clean up the isolated Claude config directory and child process;
- avoid provider credentials and network inference dependencies by using the local test
  provider.

**Acceptance.** An available Claude Code binary completes discovery against FCC and stores
the descriptive Terminal presentation in its isolated cache.

**Effort.** 1.5 days.

### S2.4 — Declare Terminal discovery in the feature manifests

**Goal.** Make the public Terminal discovery behavior part of the explicit product contract.

**Changes.**

- `smoke/features.py:53-90` — add the new live discovery test and the focused Terminal
  contract tests to `drop_in_claude_code_replacement`.
- `smoke/capabilities.py` — add or refine a capability contract for Claude Terminal model
  discovery, with these declared facts:
  - owner: `free_claude_code.api.model_catalog` for the payload and
    `free_claude_code.harnesses.claude` for the launch environment;
  - input: authenticated `GET /v1/models`;
  - output: `id`, `display_name`, and `description` without routing changes;
  - failure: HTTP authentication failure or a client fallback to cached/built-in models.
- `tests/contracts/test_feature_manifest.py` and
  `tests/contracts/test_import_boundaries.py` — extend only as needed to enforce the new
  declaration.

**Acceptance.** The feature inventory identifies deterministic contract coverage and the
optional product E2E scenario for Terminal model discovery.

**Effort.** 0.5 day.

---

## Wave 3 — Operator documentation

### S3.1 — Document Terminal discovery and stale-cache recovery

**Goal.** Make the supported behavior and recovery procedure discoverable without requiring
knowledge of Claude Code internals.

**Changes.**

- `README.md:492-516` — extend "Model Display Names" with a "Claude Code Terminal"
  subsection that explains:
  - Terminal and Desktop use the same descriptive-title implementation;
  - `fcc-claude` is the supported launcher;
  - direct `claude` launches require
    `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, `ANTHROPIC_BASE_URL`, and a supported
    credential;
  - the client-owned cache location and `CLAUDE_CONFIG_DIR` override;
  - discovery refresh happens on Claude Code startup;
  - the safe recovery procedure is to restart Claude Code and, only when necessary, remove
    the isolated gateway-model cache while no session is using it;
  - `claude --debug` exposes `[gatewayDiscovery]` diagnostics;
  - a user `modelPicker` with `replaceBuiltInOptions` can hide discovered rows.
- `README.md` — do not instruct users to write generated `modelPicker` entries or to edit
  routing IDs for display purposes.
- `docs/model-display-names-analysis.md` — add a cross-reference to the Terminal analysis
  and distinguish the shared title implementation from discovery compatibility.
- `docs/model-display-names-implementation-plan.md` — record that the shipped implementation
  covers the shared Terminal/Desktop projection and point to the follow-up plan for discovery
  hardening.

**Acceptance.** A reader can distinguish a stale cache, a failed discovery request, a
disabled discovery flag, and a replaced `modelPicker` lineup, and can recover without
changing model IDs.

**Effort.** 0.5 day.

### S3.2 — Register the new project documents

**Goal.** Make the Terminal analysis and plan discoverable from the contribution entry
point.

**Changes.**

- `CONTRIBUTING.md:56-63` — add links to
  `docs/claude-terminal-model-display-names-analysis.md` and
  `docs/claude-terminal-model-display-names-implementation-plan.md`.
- Keep the existing instruction to read the architecture and model-display-name documents
  before changing the request path, provider layer, or CI configuration.

**Acceptance.** Contributors can find the Terminal discovery contract and its execution plan
from the repository's documented entry points.

**Effort.** 0.25 day.

---

## Wave 4 — Hardening and release

### S4.1 — Enforce routing invariance across discovery states

**Goal.** Prove that authentication, titles, descriptions, and cache behavior cannot affect
routing.

**Changes.**

- `tests/contracts/test_model_display_name_routing.py` — retain the existing title-to-routing
  invariant.
- Extend it, if needed, to compare the Terminal routing result with discovery enabled under
  Bearer and `x-api-key` credentials and with the external title catalog present, absent,
  and stale.

**Tests.**

The contract must prove that the same provider/model reference produces:

- the same advertised ID;
- the same routing candidate list;
- the same fallback order;
- the same capability facts.

Only `display_name` and `description` may vary.

**Acceptance.** A test fails if any presentation or authentication change leaks into routing
or fallback behavior.

**Effort.** 0.5 day.

### S4.2 — Run the complete quality gate

**Goal.** Validate the combined behavior on every supported platform.

**Changes.** No source change unless the quality gate finds a defect.

Run:

```bash
uv run ruff format --check
uv run ruff check
uv run ty check
uv run pytest -v --tb=short
```

Then run the complete local CI sequence:

```powershell
.\scripts\ci.ps1
```

Also run the focused live discovery test when `FCC_SMOKE_CLAUDE_BIN` and its local
prerequisites are available.

**Acceptance.** The full deterministic suite passes. The live test passes when its explicit
prerequisites are present and skips cleanly otherwise.

**Effort.** 0.5 day.

### S4.3 — Publish the completed Terminal contract

**Goal.** Make the shipped behavior match the project documentation.

**Changes.**

- Update
  `docs/claude-terminal-model-display-names-analysis.md` to status `implemented` and record
  the final version-gate behavior.
- Update
  `docs/claude-terminal-model-display-names-implementation-plan.md` to status `implemented`
  and mark each completed step.
- Update the README Terminal subsection with only behavior verified by the completed tests.
- Add a release-note entry using the repository's existing release-note convention.

**Acceptance.** The documentation predicts the behavior of every supported Terminal launch
path without referring to unimplemented plans.

**Effort.** 0.25 day.

---

## Traceability Matrix

| Analysis finding | Plan step |
| --- | --- |
| Terminal and Desktop already share one title implementation (§2.1) | S2.1 |
| FCC launcher enables discovery (§2.2) | S2.2 |
| Claude Code owns and refreshes the discovery cache (§2.3) | S2.3, S3.1 |
| Manual `x-api-key` discovery receives HTTP 401 (§2.4) | S1.1 |
| Real-client cache behavior is not verified (§2.5) | S2.3 |
| Authentication contracts are declared in manifests | S1.2, S2.4 |
| FCC must not mutate `~/.claude` (§4, §6) | S3.1 |
| Routing must remain unchanged (§4) | S4.1 |
| Operators need stale-cache diagnostics | S3.1 |
| The public capability must be explicit | S2.4 |
| All changes pass the repository quality gate | S4.2, S4.3 |

---

## Effort Summary

| Wave | Steps | Estimate (days) |
| --- | --- | ---: |
| 0 — Baseline | S0.1 | 0.5 |
| 1 — Discovery authentication | S1.1, S1.2 | 1 |
| 2 — Terminal contracts | S2.1, S2.2, S2.3, S2.4 | 3 |
| 3 — Operator documentation | S3.1, S3.2 | 0.75 |
| 4 — Hardening and release | S4.1, S4.2, S4.3 | 1.25 |
| **Total** | **10 steps** | **6.5** |
