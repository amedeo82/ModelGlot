# Implementation Plan: Reversible Claude Desktop Gateway Integration

Status: proposed; not implemented on `custom/main`
Date: 2026-11-12; revalidated on 2026-11-16
Input: [`claude-desktop-gateway-login-analysis.md`](claude-desktop-gateway-login-analysis.md)
Audience: maintainers and contributors

This plan converts the Claude Desktop gateway/login analysis into an ordered, reviewable
implementation. The target behavior is a reversible FCC-owned Desktop configuration that
routes inference through FCC when selected without removing normal Claude.ai sign-in or
destroying the native login/bootstrap state.

The plan does not attempt to make standard Claude.ai identity and 3P gateway identity
simultaneous. Anthropic documents them as alternative deployment modes.

## Current Step Status

Status values reflect `custom/main` at commit `12914bd`.

| Step | Status | Evidence / remaining work |
| --- | --- | --- |
| S0.1 | Partially complete | Focused Desktop unit, API, runtime, cleanup, and E2E tests exist, but the recorded baseline is not part of this document. |
| S0.2 | Open | No live cross-version Claude Desktop compatibility matrix is recorded. |
| S0.3 | Open | The default deployment policy remains undecided. |
| S1.1 | Open | No restore journal exists. |
| S1.2 | Open | Native state capture and restoration helpers do not exist. |
| S1.3 | Open | Connected state still requires `deploymentMode == "3p"` and absent `hybridPointer`. |
| S2.1 | Open | Connect still removes `hybridPointer` and forces `deploymentMode: "3p"`. |
| S2.2 | Open | Disconnect still selects the Default profile and forces `deploymentMode: "1p"`. |
| S2.3 | Open | A native-profile selection conflict policy is not implemented. |
| S2.4 | Open | Legacy `3p`-state migration is not implemented. |
| S3.1 | Open | The integration status does not expose chooser or restoration state. |
| S3.2 | Open | The Admin integration card does not describe reversible mode selection. |
| S3.3 | Open | README does not document the target reversible lifecycle. |
| S4.1 | Partially complete | The existing Desktop E2E test covers the current destructive lifecycle, not the reversible contract. |
| S4.2 | Open | The reversible implementation does not yet have a quality-gate result. |
| S4.3 | Open | No manual acceptance matrix for the reversible lifecycle is recorded. |
| S4.4 | Open | No release note or rollback guidance for the reversible lifecycle exists. |

A step marked **Open** has not satisfied this plan's acceptance criteria. **Partially
complete** means a named part exists but the step still requires further work.

---

## 0. Ground Rules

These apply to every implementation step.

1. **One behavioral concern per pull request.** Steps below propose one PR per step unless a
   step explicitly requires otherwise.
2. **PR title prefixes are mandatory.** Changes under `src/`, `tests/`, `e2e/`, `README.md`,
   or `pyproject.toml` use exactly one of `patch: `, `minor: `, or `major: ` followed by a
   description. This is a user-visible behavioral change and therefore uses `minor: `.
3. **Do not modify unrelated working-tree changes.** The current checkout already contains
   unrelated modified or untracked documentation. Implementation must stage only files owned by
   the relevant step.
4. **Tests accompany behavior.** Every change to the Desktop lifecycle adds focused unit
   tests and relevant API, runtime, cleanup, or end-to-end coverage.
5. **Preserve ownership boundaries.** FCC may modify only the FCC-owned profile and fields it
   explicitly owns. It must not rewrite unknown user fields or the native credential store.
6. **Preserve `hybridPointer`.** Do not synthesize, normalize, or delete the undocumented
   value. Preserve it exactly when present and continue working when it is absent.
7. **Preserve idempotency and rollback.** Connect, refresh, and disconnect must remain safe
   to retry after interruption.
8. **No credential leakage.** Do not write proxy tokens, Anthropic tokens, or other secrets to
   logs, diagnostics, exception messages, or new plaintext state files.
9. **No version edits.** Versions are managed by the release pipeline.
10. **Documentation ships with code.** README and user-facing behavior updates must be in the
    same PR as the code they describe.

Effort estimates are rough developer-days for a maintainer already familiar with the project.

---

## 1. Target State

### 1.1 Behavioral contract

After the implementation:

- Connect creates or updates the FCC-owned gateway profile.
- Connect selects that profile.
- Connect preserves `hybridPointer` if it exists.
- Connect does not force the deployment chooser away from Claude.ai.
- Connect preserves the selected native profile and its pointer in a recoverable journal.
- Refresh rotates only FCC-owned gateway fields.
- Disconnect restores the previous profile, pointer, and deployment state.
- If safe restoration is impossible, the Desktop configuration remains valid and standard
  sign-in remains reachable.
- FCC never revokes Anthropic credentials and never explicitly disables skills, plugins, or
  connectors.

### 1.2 Explicit non-goals

The implementation must not:

- proxy Anthropic-hosted connectors;
- reproduce or modify Claude.ai account content;
- emulate Claude.ai identity inside a 3P session;
- patch Claude Desktop binaries or private JavaScript bundles;
- write to the Claude Desktop credential store;
- guarantee that account-synchronized skills and plugins are present in 3P;
- add gateway-only mode in the first implementation wave.

---

## 2. State Model

Introduce an explicit persisted journal for the reversible lifecycle. The journal must be
FCC-owned, local, atomic, and sufficient to reconstruct the user's pre-Connect state.

Recommended record shape:

```json
{
  "version": 1,
  "root": "<resolved Claude-3p root>",
  "previous_applied_id": "<native profile id or null>",
  "previous_hybrid_pointer": "<preserved value or null>",
  "previous_deployment_mode": "any | 3p | 1p | null",
  "fingerprint": "<hash of previous profile selection state>"
}
```

Requirements:

- Store it in an FCC-owned state directory, not inside Claude Desktop's `configLibrary`.
- Use the same atomic-write helper used by the existing Desktop integration.
- Do not store tokens, credentials, model definitions, or profile contents in the journal.
- Treat `null` and an absent value as distinct only where that distinction is required to
  restore the original state exactly.
- Version the schema so future changes can migrate or discard it safely.
- Delete the journal only after restoration is complete and verified.

---

## 3. Waves

### Wave 0 — Baseline and compatibility discovery

### S0.1 — Capture the current Desktop integration baseline

**Goal.** Establish the exact behavior and test baseline before changing the lifecycle.

**Changes.**

- No production source changes.
- Record the results of the focused test suite and the current lint/type-check baseline.
- Add a test inventory to the implementation branch or implementation notes, covering:
  - connect;
  - refresh;
  - disconnect;
  - pending disconnect;
  - unrelated selected profile;
  - managed-policy rejection;
  - Windows legacy-root migration.

**Commands.**

```powershell
uv run pytest tests/harnesses/test_claude_desktop_integration.py tests/api/test_claude_desktop_integration.py tests/runtime/test_integration_startup.py tests/harnesses/test_integration_cleanup.py
uv run ruff check src/free_claude_code/harnesses/claude_desktop_integration.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_claude_desktop_integration.py
uv run ty check
```

**Acceptance.**

- The focused suite passes before implementation.
- Existing failures, if any, are recorded separately and are not attributed to the new work.
- The exact commands and results are available in the PR description.

**Effort.** 0.25 day.

---

### S0.2 — Build a live Desktop compatibility matrix

**Goal.** Validate the assumptions that depend on undocumented `configLibrary` behavior.

**Changes.**

- No production source changes.
- On disposable test profiles or a dedicated OS account, capture before-and-after snapshots of:
  - `configLibrary/_meta.json`;
  - `configLibrary/<selected-profile>.json`;
  - `claude_desktop_config.json`;
  - the Claude Desktop diagnostic report;
  - the login-screen choices;
  - `main.log` configuration and mode events.
- Exercise at least:
  1. a Desktop release that supports `deploymentMode`;
  2. the oldest release still supported by the project;
  3. a machine with no prior `Claude-3p` directory;
  4. a machine with a native profile and `hybridPointer`;
  5. a machine with a native profile without `hybridPointer`.
- Verify whether `deploymentMode: "any"` leaves the Claude.ai sign-in choice available.
- Verify that removing `hybridPointer` is what suppresses the native choice in the affected
  releases.

**Acceptance.**

- The matrix records the Desktop version and effective result for every case.
- The implementation chooses a compatibility policy based on observed behavior rather than
  assumptions about the private pointer.
- If no second release can be tested, the PR records that limitation and the implementation
  keeps the behavior conservative by default.

**Effort.** 1 day.

---

### S0.3 — Decide the default deployment policy

**Goal.** Record the maintainer decision before changing behavior.

**Decision.**

Recommended default:

- use `deploymentMode: "any"`;
- preserve `hybridPointer`;
- leave an explicit gateway-only mode out of scope.

Alternative, rejected for the first release:

- continue forcing `3p`.

**Acceptance.**

- The decision, rationale, and rollback path are recorded in the PR description.
- The README wording in later steps uses the approved semantics.

**Effort.** 0.25 day.

---

### Wave 1 — Reversible state and pure configuration helpers

### S1.1 — Add the Desktop restore journal

**Goal.** Persist the minimum information required to restore the user's previous Desktop
configuration without storing credentials or profile contents.

**Changes.**

- `src/free_claude_code/config/paths.py` — add a dedicated path for the Desktop restore
  journal under the FCC-owned state directory.
- `src/free_claude_code/harnesses/claude_desktop_integration.py`:
  - add a typed journal structure;
  - add strict parsing and validation;
  - add atomic create, read, replace, and remove operations;
  - reject unknown schema versions with a recoverable error;
  - keep the journal separate from the pending-disconnect marker because it describes the
    desired restoration target, not an in-progress cleanup.
- `src/free_claude_code/runtime/integration_service.py` — pass the journal path to the Desktop
  integration without changing startup behavior.

**Tests.**

Add focused cases in `tests/harnesses/test_claude_desktop_integration.py`:

- journal is created atomically with the expected schema;
- an existing valid journal round-trips;
- missing optional previous values round-trip as `null`;
- unknown versions are rejected;
- malformed JSON is rejected without overwriting the original;
- a journal for a different root is rejected;
- the journal contains no API key or profile payload;
- write failure leaves the prior journal intact.

**Acceptance.**

- The journal can survive process termination between every connect mutation.
- No secret is present in the journal.
- Existing connect and disconnect tests remain green before lifecycle behavior changes.

**PR title.** `minor: Persist a recoverable Claude Desktop restoration journal`

**Effort.** 1 day.

---

### S1.2 — Separate native state capture from restoration

**Goal.** Make the current-state capture logic pure and independently testable.

**Changes.**

- `src/free_claude_code/harnesses/claude_desktop_integration.py`:
  - introduce a helper that captures the selected profile ID, `hybridPointer`, and
    `deploymentMode` from a loaded library;
  - make it preserve the distinction between an absent pointer and a present pointer;
  - introduce a helper that validates a candidate previous profile before it can be restored;
  - do not mutate Claude Desktop state in these helpers.
- Keep `_Library` as the owner of parsed configuration state.

**Tests.**

- selected native profile is captured;
- absent `hybridPointer` is captured correctly;
- present `hybridPointer` is preserved exactly, including nested JSON types;
- absent, `any`, `3p`, and `1p` deployment modes are distinguished;
- a previous profile ID that no longer exists is identified as unrestorable;
- the helper does not write files.

**Acceptance.**

- Capture and validation behavior is fully covered without filesystem mutation.
- The implementation does not yet change the user-visible lifecycle.

**Effort.** 0.75 day.

---

### S1.3 — Define and validate the effective active state

**Goal.** Replace the current `hybridPointer`-absence requirement with a model that reflects
the new reversible contract.

**Changes.**

- `src/free_claude_code/harnesses/claude_desktop_integration.py`:
  - split the current `active` concept into:
    - `gateway_configured`: the FCC profile is selected and contains valid FCC-owned gateway
      fields;
    - `native_login_available`: the Desktop metadata retains a valid native profile or
      pointer state and the deployment chooser has not been forced off;
    - `connected`: the public integration status reported to the Admin UI.
  - keep `_current()` responsible for validating the gateway URL, credential, model-discovery
    setting, and FCC ownership header;
  - never infer that standard login is unavailable merely because `hybridPointer` is absent;
  - treat `deploymentMode: "3p"` as gateway-only configuration, while `any` or an absent mode
    remains chooser-enabled.

**Tests.**

- gateway profile selected with `any` is configured but chooser-enabled;
- gateway profile selected with `3p` is gateway-only;
- gateway profile selected with `1p` is reported as a conflict rather than silently claiming
  the gateway is active;
- a valid native profile remains selected after the FCC profile is registered but not
  applied;
- `hybridPointer` absence does not itself mean login was destroyed;
- a modified FCC URL or token causes the current-state check to fail;
- a non-FCC profile with the same ID is rejected.

**Acceptance.**

- The new state model expresses configuration, mode, and connection status independently.
- Existing API response semantics remain backward compatible or receive an explicit versioned
  update in S3.2.

**Effort.** 1 day.

---

### Wave 2 — Reversible connect and disconnect

### S2.1 — Make Connect preserve native login state

**Goal.** Change Connect so it no longer removes `hybridPointer` and no longer forces the
Desktop into gateway-only mode by default.

**Changes.**

- `src/free_claude_code/harnesses/claude_desktop_integration.py`, `configure()`:
  - capture the previous selected profile, `hybridPointer`, and deployment mode before any
    mutation;
  - write the restore journal before mutating `_meta.json` or `claude_desktop_config.json`;
  - register and select the FCC profile without deleting `hybridPointer`;
  - set `deploymentMode` to `any` when the file previously had no effective mode or had `any`;
  - preserve an existing user-selected mode unless it conflicts with the gateway profile;
  - if the existing mode is `1p`, report a conflict or require explicit user choice rather
    than silently overwriting it;
  - keep all existing profile-field merging, URL validation, egress preservation, and model
    preservation behavior.
- Do not add a `3p` compatibility fallback that again removes native state. If a release does
  not support `any`, report the effective incompatibility and leave native state intact.

**Tests.**

Extend `tests/harnesses/test_claude_desktop_integration.py`:

- Connect preserves an existing `hybridPointer` exactly;
- Connect preserves a native profile entry;
- Connect writes `deploymentMode: "any"` when no mode was present;
- Connect does not change an existing compatible mode;
- Connect refuses to replace an incompatible `1p` mode without explicit intent;
- the journal exists before the first metadata mutation;
- existing `inferenceModels`, custom headers, and egress fields remain unchanged;
- unknown top-level profile fields remain unchanged;
- a failed metadata write leaves the journal available for retry;
- a failed mode write can be retried without losing the previous state.

**Acceptance.**

- No Connect path removes or synthesizes `hybridPointer`.
- The standard sign-in choice remains available on supported Desktop versions.
- Existing gateway configuration and model discovery behavior remain intact.

**PR title.** `minor: Preserve native Claude Desktop sign-in when connecting the gateway`

**Effort.** 1.5 days.

---

### S2.2 — Implement profile restoration on Disconnect

**Goal.** Restore the user's previous Desktop profile instead of selecting an empty Default
profile and forcing `1p`.

**Changes.**

- `src/free_claude_code/harnesses/claude_desktop_integration.py`, `_disconnect()`:
  - load and validate the restore journal;
  - verify that the journal still belongs to the current root and FCC ownership state;
  - if the recorded previous profile exists and remains valid, restore it as `appliedId`;
  - restore the recorded `hybridPointer` exactly when it was present;
  - remove the pointer only when the journal proves FCC added it, which the new Connect path
    never does;
  - restore the previous deployment mode, mapping an absent value to removal of the FCC-owned
    key or an explicit `any` according to the approved compatibility policy;
  - remove the FCC profile and FCC library entry;
  - verify the final state before deleting the journal;
  - remove the journal only after successful verification;
  - if restoration fails, keep the pending-disconnect marker and journal for a later retry.
- Retain the existing empty Default profile only as a last-resort fallback when no previous
  profile can be restored.
- Do not delete a native profile or user-owned profile.

**Tests.**

- Disconnect restores the previous profile ID.
- Disconnect restores the exact previous `hybridPointer`.
- Disconnect restores the previous deployment mode.
- Disconnect removes the FCC profile and FCC entry.
- Disconnect leaves a native profile and its fields untouched.
- Disconnect works when the journal has no previous profile.
- Disconnect uses the safe fallback when the recorded profile no longer exists.
- Disconnect refuses to overwrite a newer user-owned selection that conflicts with the
  journal.
- interruption at every write boundary leaves a retryable state;
- the journal is deleted only after verified restoration;
- the pending-disconnect marker continues to block a conflicting new Connect until cleanup
  completes.

**Acceptance.**

- Connect → native profile → Disconnect returns the Desktop configuration to the captured
  pre-Connect state.
- No native profile is deleted or recreated.
- Interrupted cleanup is resumable.

**Effort.** 2 days.

---

### S2.3 — Preserve the native profile when the user selects it manually

**Goal.** Handle the case where the user chooses Claude.ai after FCC has applied its profile.

**Changes.**

- `src/free_claude_code/harnesses/claude_desktop_integration.py`:
  - refresh must not reactivate the FCC profile if another profile is now selected;
  - Disconnect must not restore an obsolete profile over a deliberate newer user selection;
  - define the conflict rule explicitly in code and document it;
  - retain the FCC profile and journal until the user explicitly disconnects or the journal
    can be safely superseded.
- If the native profile ID cannot be determined from the current metadata, do not guess.

**Tests.**

- Refresh does not reselect the FCC profile after the user selects another profile.
- Disconnect recognizes a deliberate newer selection and does not overwrite it.
- Refresh remains idempotent when the FCC profile is still selected.
- A stale journal cannot force restoration over a newer selection.

**Acceptance.**

- The user can switch to Claude.ai after connecting without FCC switching the profile back
  on the next server refresh.
- The integration status truthfully reports that the FCC gateway profile is configured but
  not currently selected.

**Effort.** 1 day.

---

### S2.4 — Define a safe migration from the existing destructive behavior

**Goal.** Make installations created by the old Connect flow recoverable.

**Changes.**

- On startup or Connect, detect an existing FCC installation whose metadata lacks
  `hybridPointer` and whose mode is `3p`.
- Do not infer the original native pointer or profile automatically.
- Surface a migration status that tells the user that native sign-in state cannot be recovered
  automatically and that Claude Desktop may need to be relaunched to recreate its chooser.
- Provide a recovery path that:
  - leaves the existing gateway profile available;
  - does not delete any native profile;
  - changes the mode to `any` only after explicit user confirmation;
  - does not fabricate `hybridPointer`.
- Ensure the old pending-disconnect marker and new restore journal can coexist safely.

**Tests.**

- legacy FCC state is detected;
- detection does not mutate state;
- explicit migration changes `3p` to `any` and preserves profiles;
- migration does not create a fake pointer;
- a legacy pending disconnect is completed before migration;
- migration is idempotent.

**Acceptance.**

- Existing users can adopt the new reversible behavior without losing their gateway setup.
- No migration can overwrite an unknown native state.

**Effort.** 1 day.

---

### Wave 3 — API, Admin UI, and user documentation

### S3.1 — Extend the integration status response

**Goal.** Expose chooser and restoration state to the Admin UI and diagnostics without
exposing secrets.

**Changes.**

- `src/free_claude_code/api/admin_routes.py` — extend the Desktop integration status model
  with non-secret fields such as:
  - `gateway_profile_configured`;
  - `gateway_profile_selected`;
  - `deployment_mode`;
  - `deployment_chooser_enabled`;
  - `native_login_state`;
  - `restore_pending`;
  - `legacy_migration_available`.
- Keep the existing `connected` field backward compatible.
- Add an explicit `mode` or `state` enum if needed to avoid ambiguous booleans.
- Never expose `hybridPointer`, profile contents, proxy tokens, or journal paths that reveal
  sensitive data.

**Tests.**

- status distinguishes configured-but-not-selected from selected and connected;
- status reports `any`, `3p`, `1p`, or absent deployment mode;
- status reports legacy migration availability;
- response contains no token or pointer value;
- existing consumers continue to receive a valid `connected` boolean.

**Acceptance.**

- The API reports the new lifecycle accurately and without sensitive values.
- API schemas and validation tests pass.

**Effort.** 1 day.

---

### S3.2 — Update the Admin integration card

**Goal.** Make the reversible behavior visible and understandable in the product UI.

**Changes.**

- `src/free_claude_code/api/admin_static/index.html` — update the Claude Desktop integration
  copy to explain:
  - the gateway profile is applied;
  - standard Claude.ai sign-in remains available;
  - account-hosted Anthropic connectors remain exclusive to standard Desktop.
- `src/free_claude_code/api/admin_static/admin.js` — render the new status fields and offer
  clear actions for:
  - Connect;
  - Disconnect;
  - Restore/confirm legacy migration where applicable.
- Do not add an automatic destructive migration action.
- Preserve accessibility and existing UI test conventions.

**Tests.**

- Admin API/UI tests verify the new status values.
- The card remains usable when the deployment mode is absent.
- The UI does not claim that Claude.ai account content synchronizes into 3P.
- Existing E2E integration flow remains functional.

**Acceptance.**

- A user can understand why standard login is still offered and how to return to it.
- No UI wording promises unsupported simultaneous identity behavior.

**Effort.** 1 day.

---

### S3.3 — Update README and user documentation

**Goal.** Document the final behavior and its limitations accurately.

**Changes.**

- `README.md`, “Connect Your Client” section:
  - state that Claude Desktop on 3P supports MCP connectors, skills, and plugins;
  - state that user-added and account-backed extensions are different models;
  - state that connectors hosted by Anthropic require standard Claude Desktop;
  - explain the standard/3P choice on the Claude Desktop sign-in screen;
  - explain that Disconnect restores the previously selected Desktop configuration;
  - retain the instruction to fully quit Desktop before connect or disconnect.
- Update the integration status wording in any Admin documentation.
- Link the analysis and implementation-plan documents if repository policy permits internal
  engineering documents to be linked from user documentation.

**Acceptance.**

- README instructions match the implemented lifecycle.
- No statement implies that `ANTHROPIC_BASE_URL` configures the Desktop application.
- The documented limitations match the vendor behavior.

**Effort.** 0.5 day.

---

### Wave 4 — End-to-end validation and release readiness

### S4.1 — Extend the Desktop integration end-to-end suite

**Goal.** Verify the complete lifecycle through the Admin API and, where available, the
Desktop UI.

**Changes.**

- `e2e/test_claude_desktop_integration.py`:
  - connect from the Admin UI;
  - verify the gateway profile and chooser-enabled mode;
  - refresh without changing login state;
  - disconnect and verify the previous profile and pointer are restored;
  - verify a second connect is idempotent.
- Add a fixture for a pre-existing native profile with `hybridPointer`.
- Add a fixture for a native profile without `hybridPointer`.
- Keep platform-specific behavior behind the existing platform checks.

**Acceptance.**

- The E2E lifecycle passes on the supported CI platforms.
- The E2E test does not require or modify a real user's Anthropic session.
- A failure produces a diagnostic artifact containing the before/after Desktop metadata.

**Effort.** 1.5 days.

---

### S4.2 — Run the complete quality gate

**Goal.** Verify that the implementation does not regress the wider project.

**Commands.**

```powershell
uv run pytest tests/harnesses/test_claude_desktop_integration.py tests/api/test_claude_desktop_integration.py tests/runtime/test_integration_startup.py tests/harnesses/test_integration_cleanup.py
uv run pytest tests/contracts
uv run ruff check .
uv run ty check
```

If the repository's CI wrapper is the canonical full-suite command, run the relevant wrapper
check for the supported platform as well:

```powershell
./scripts/ci.ps1
```

**Acceptance.**

- Focused Desktop tests pass.
- Contract tests pass.
- Ruff and type checks pass.
- The full CI-equivalent suite passes, or any unrelated failure is identified with evidence
  and approved by a maintainer.
- No test writes to a real `%LOCALAPPDATA%\Claude-3p` or user `~/.claude` directory.

**Effort.** 0.5 day.

---

### S4.3 — Perform a manual acceptance matrix

**Goal.** Validate the behavior against real Claude Desktop releases after automated tests
pass.

**Matrix.**

| Scenario | Expected result |
| --- | --- |
| Fresh install, no native profile | Gateway profile is selectable; standard sign-in choice is not destroyed |
| Existing native profile with pointer | Connect preserves pointer and profile; Disconnect restores both |
| Existing native profile without pointer | Connect and Disconnect succeed without fabricating a pointer |
| User selects Claude.ai after Connect | Refresh does not switch back; Disconnect does not overwrite the newer choice |
| Gateway restart with token rotation | Gateway fields update; profile selection and pointer do not change |
| Interruption during Disconnect | Retry completes restoration and removes the pending marker |
| Legacy FCC state from the old implementation | Migration is detected and requires explicit confirmation |
| MDM-managed Desktop | Connect fails safely and leaves managed configuration untouched |

**Acceptance.**

- Each expected result is confirmed on at least one supported Desktop release.
- Screenshots or diagnostic excerpts are attached to the PR without exposing secrets.
- Known unsupported releases are documented.

**Effort.** 1 day.

---

### S4.4 — Prepare release notes and rollback guidance

**Goal.** Make the behavior change safe for users to adopt.

**Changes.**

- Add a release-note entry describing:
  - Connect no longer removes native sign-in state;
  - the Desktop application may show both the provider-configuration and Claude.ai choices;
  - Disconnect restores the previously selected profile;
  - existing users may require a one-time explicit migration from legacy `3p` state.
- Document how to roll back to the previous release and how to manually restore the gateway
  profile if the new flow is problematic.

**Acceptance.**

- The release note contains no secrets.
- Rollback instructions identify which files FCC owns and which files the user must not edit
  by hand unless necessary.

**Effort.** 0.5 day.

---

## 4. Dependency Map

| Step | Depends on | Produces |
| --- | --- | --- |
| S0.1 | none | Baseline test and quality results |
| S0.2 | none | Desktop compatibility matrix |
| S0.3 | S0.2 | Approved deployment policy |
| S1.1 | S0.3 | Restore journal and path |
| S1.2 | S0.3 | Pure state-capture helpers |
| S1.3 | S1.2 | New active-state model |
| S2.1 | S1.1, S1.3 | Non-destructive Connect |
| S2.2 | S2.1 | Restoring Disconnect |
| S2.3 | S2.1 | User-selection conflict rules |
| S2.4 | S2.1, S2.2 | Legacy migration path |
| S3.1 | S2.2, S2.3, S2.4 | Extended integration status API |
| S3.2 | S3.1 | Updated Admin UI |
| S3.3 | S2.1–S2.4 | Accurate README |
| S4.1 | S2.1–S3.3 | Expanded E2E coverage |
| S4.2 | S4.1 | Full quality-gate result |
| S4.3 | S4.2 | Real Desktop acceptance evidence |
| S4.4 | S4.3 | Release note and rollback guidance |

Steps S1.1 and S1.2 may proceed in parallel after S0.3. S2.2, S2.3, and S2.4 may proceed in
parallel after S2.1, provided they agree on the shared state and journal helpers.

---

## 5. Proposed Pull Requests

### PR 1 — Reversible Desktop state foundation

- S1.1, S1.2, S1.3
- Title: `minor: Add reversible Claude Desktop gateway state management`
- No user-visible lifecycle change.

### PR 2 — Preserve native sign-in and restore on disconnect

- S2.1, S2.2, S2.3, S2.4
- Title: `minor: Preserve native Claude Desktop sign-in around the gateway`
- Primary behavioral change.
- Includes the legacy migration path.

### PR 3 — Expose the new lifecycle in the Admin UI

- S3.1, S3.2, S3.3
- Title: `minor: Explain Claude Desktop gateway and sign-in modes in the Admin UI`
- Includes README documentation.

### PR 4 — End-to-end validation and release readiness

- S4.1, S4.2, S4.3, S4.4
- Title: `patch: Validate the reversible Claude Desktop gateway lifecycle`
- Test expansion and release documentation; may be folded into PR 2 if the project prefers
  fewer pull requests.

---

## 6. Final Acceptance Checklist

- [ ] No production Connect path removes `hybridPointer`.
- [ ] No production Connect path silently forces `deploymentMode: "3p"`.
- [ ] A native profile remains restorable after a gateway connection.
- [ ] Disconnect restores the previous profile and pointer.
- [ ] Refresh changes only FCC-owned gateway fields.
- [ ] A deliberate user selection is not overwritten by refresh or disconnect.
- [ ] The journal contains no secrets and uses atomic writes.
- [ ] Interrupted connect or disconnect operations are retryable.
- [ ] Legacy FCC state has an explicit, non-destructive migration path.
- [ ] MDM-managed installations remain protected.
- [ ] The Admin API and UI describe the effective mode accurately.
- [ ] README documents the standard/3P distinction and Anthropic-hosted connector limitation.
- [ ] Focused tests, contract tests, Ruff, type checking, and CI-equivalent checks pass.
- [ ] At least one real Claude Desktop release passes the manual acceptance matrix.

---

## 7. Deferred Follow-Ups

These are intentionally outside the first implementation:

1. **Explicit gateway-only mode.** Add a separate opt-in action that sets `deploymentMode:
   "3p"` without deleting native state, with a clear confirmation prompt.
2. **Gateway credential helper.** Replace the static proxy token with the Desktop-supported
   helper-script flow if per-user attribution or token rotation becomes necessary.
3. **Managed connector and plugin provisioning.** Provide project-level templates for
   `managedMcpServers`, organization plugin directories, and managed marketplace policies.
   The per-user FCC profile already registers the official Anthropic marketplace; see
   `docs/claude-desktop-1m-context-and-official-marketplace.md`.
4. **Claude.ai export/import bridge.** Investigate the documented one-time import workflow
   for account skills and plugins; do not present it as continuous synchronization.
5. **Cross-platform release matrix.** Expand the manual matrix to every supported macOS and
   Linux version after the Windows path is stable.
6. **Telemetry.** Add aggregate, non-content diagnostics for deployment-mode selection and
   restoration failures only if the project has an approved telemetry policy.
