# Claude Desktop Gateway and Claude.ai Login Analysis

Status: analysis baseline; reversible implementation proposed
Date: 2026-11-12; revalidated on 2026-11-16
Scope: `free-claude-code` on branch `custom/main`, commit `12914bd`
Current profile implementation: [`claude-desktop-fcc-profile.md`](claude-desktop-fcc-profile.md)
Audience: maintainers and contributors

This document records the current Claude Desktop integration, the behavior of Anthropic's
standard and third-party deployment modes, and the feasible paths for preserving Claude.ai
login functionality while routing inference through Free Claude Code (FCC).

The implementation steps derived from this analysis are recorded in
[`claude-desktop-gateway-login-implementation-plan.md`](claude-desktop-gateway-login-implementation-plan.md).

Related: [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the quality gate that any
implementation of this analysis must satisfy.

---

## 1. Executive Summary

FCC currently configures Claude Desktop as a third-party deployment (3P) with the local FCC
gateway as its inference provider. It creates a dedicated FCC configuration profile, selects
that profile, writes `deploymentMode: "3p"`, and removes the internal `hybridPointer` value
from `configLibrary/_meta.json`.

FCC does not delete Claude Desktop credentials, revoke Anthropic OAuth tokens, remove
`~/.claude`, or explicitly disable skills, plugins, or connectors. Nevertheless, the resulting
Desktop application is locked into the 3P deployment mode and can no longer offer the normal
Claude.ai sign-in path while the FCC profile is applied.

Anthropic's current documentation establishes three important facts:

1. Standard Claude Desktop and Claude Desktop on 3P are alternative deployment modes.
2. `deploymentMode: "3p"` removes the Claude.ai sign-in choice; `deploymentMode: "any"` keeps it.
3. Claude Desktop on 3P supports MCP connectors, skills, and plugins, but account-backed
   Claude.ai content is not continuously synchronized into the 3P identity. Connectors hosted
   by Anthropic are available only in standard Claude Desktop.

Therefore:

- A Claude.ai login and a 3P gateway cannot simultaneously govern the same Desktop session.
- FCC can stop being destructive and preserve the ability to return to standard Claude Desktop.
- FCC should configure the gateway without forcing the deployment-mode chooser away from
  Claude.ai and without removing the native login/bootstrap pointer.
- The recommended implementation is a reversible, user-selectable configuration with faithful
  restoration of the previously applied Desktop profile.

---

## 2. Method and Evidence

The analysis combined repository inspection with current vendor documentation.

### 2.1 Repository inspection

The following areas were inspected read-only:

- `src/free_claude_code/harnesses/claude_desktop_integration.py`;
- `src/free_claude_code/runtime/integration_service.py`;
- `src/free_claude_code/config/paths.py`;
- `src/free_claude_code/harnesses/claude.py`;
- `src/free_claude_code/harnesses/claude_integration.py`;
- `src/free_claude_code/cli/managed/diagnostics.py`;
- `src/free_claude_code/api/admin_routes.py`;
- `src/free_claude_code/api/admin_static/`;
- Desktop integration unit, API, runtime, cleanup, and end-to-end tests;
- README instructions for the Claude Desktop integration.

### 2.2 Vendor documentation reviewed

- Claude Desktop on 3P overview:
  <https://claude.com/docs/third-party/claude-desktop/overview>
- Claude Desktop 3P configuration reference:
  <https://claude.com/docs/third-party/claude-desktop/configuration>
- Claude Desktop 3P gateway deployment:
  <https://claude.com/docs/third-party/claude-desktop/gateway>
- Claude Desktop 3P MDM and deployment-mode behavior:
  <https://claude.com/docs/third-party/claude-desktop/mdm>
- Claude Desktop 3P extensions, plugins, skills, and hooks:
  <https://claude.com/docs/third-party/claude-desktop/extensions>
- Claude Desktop 3P built-in connectors:
  <https://claude.com/docs/third-party/claude-desktop/built-in-connectors>
- Claude Desktop 3P identity and local data:
  <https://claude.com/docs/third-party/claude-desktop/data-storage>
- Claude Code gateway connection:
  <https://code.claude.com/docs/en/llm-gateway-connect>

Documentation was reviewed against the vendor pages available on 2026-11-12. Vendor behavior
can change, so implementation work must include a version-compatibility check against the
installed Claude Desktop release.

### 2.3 Scope not covered

This analysis did not perform:

- live sign-in or logout against Anthropic;
- inspection of an encrypted Claude Desktop credential store;
- a cross-version matrix against every Claude Desktop release;
- a live test of standard-mode and 3P-mode switching on the same Windows account.

Those limitations are explicit prerequisites in the implementation plan.

---

## 3. Current FCC Architecture

### 3.1 Configuration roots

The Desktop integration uses a separate 3P configuration root:

| Platform | Root |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Claude-3p` |
| macOS | `~/Library/Application Support/Claude-3p` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/Claude-3p` |

The root is defined in
`src/free_claude_code/harnesses/claude_desktop_integration.py:38-48`.

Relevant files are:

```text
<Claude-3p>/
├── configLibrary/
│   ├── <FCC_ID>.json
│   ├── <DEFAULT_ID>.json
│   └── _meta.json
└── claude_desktop_config.json
```

`FCC_ID` and `DEFAULT_ID` are deterministic UUIDs derived from the integration identity
(`claude_desktop_integration.py:18-23`). The paths are exposed by the integration for
diagnostics and UI display (`claude_desktop_integration.py:143-190`).

The disconnect intent record is stored separately at
`~/.fcc/claude-desktop-disconnect.json`
(`src/free_claude_code/config/paths.py:113-114`).

### 3.2 Connect behavior

`configure(..., connected=True)` performs these operations
(`claude_desktop_integration.py:373-413`):

1. Load and validate the Desktop configuration library.
2. Reject an incomplete or conflicting pending disconnect.
3. Check for a pending Windows migration from the legacy Roaming directory.
4. Create or update the dedicated FCC profile.
5. Register `{ "id": FCC_ID, "name": "FCC" }` in `_meta.json`.
6. Set `appliedId` to `FCC_ID`.
7. Remove `hybridPointer` from `_meta.json`.
8. Set `deploymentMode` to `"3p"` in `claude_desktop_config.json`.

The FCC profile contains the gateway connection:

```json
{
  "inferenceProvider": "gateway",
  "inferenceGatewayBaseUrl": "http://127.0.0.1:<port>",
  "inferenceCredentialKind": "static",
  "inferenceGatewayApiKey": "<proxy-token>",
  "inferenceGatewayAuthScheme": "bearer",
  "modelDiscoveryEnabled": true
}
```

The values are produced by `_values()` (`claude_desktop_integration.py:241-264`). The update
is merge-based (`_update_profile()`, `claude_desktop_integration.py:285-295`), so unrelated
profile fields, existing model definitions, custom headers, and user-owned egress settings are
preserved. FCC also ensures `coworkEgressAllowedHosts` contains `"*"` when the user has not
defined an egress policy.

The gateway base URL is constrained to HTTPS or loopback HTTP
(`claude_desktop_integration.py:241-256`).

### 3.3 Active-state model

The integration considers the FCC profile active only when all of the following are true
(`_Library.active`, `claude_desktop_integration.py:171-181`):

- `appliedId == FCC_ID`;
- `deploymentMode == "3p"`;
- `hybridPointer` is absent.

The absence of `hybridPointer` is therefore an explicit part of FCC's internal connected-state
contract, not merely leftover cleanup.

### 3.4 Refresh behavior

`refresh_connected()` runs during server startup
(`src/free_claude_code/runtime/integration_service.py:104-109`) and refreshes the proxy URL
and rotating token only when the FCC profile is already active
(`claude_desktop_integration.py:362-370`).

Refresh does not:

- change the selected profile;
- rewrite `deploymentMode`;
- rewrite `_meta.json`;
- rewrite `inferenceModels`;
- reactivate a profile that the user deliberately disconnected.

Writes are idempotent because `_write()` compares the desired and current JSON values before
writing (`claude_desktop_integration.py:120-124`).

### 3.5 Disconnect behavior

When the FCC profile is selected, `_disconnect()`
(`claude_desktop_integration.py:319-359`):

1. writes a pending-disconnect record;
2. creates a reserved empty Default profile if needed;
3. selects the Default profile;
4. removes `hybridPointer`;
5. sets `deploymentMode` to `"1p"`;
6. deletes the FCC profile;
7. removes the FCC entry from the library;
8. removes the pending-disconnect record.

If another profile is selected, FCC does not change the selection and preserves that profile's
configuration and `hybridPointer`.

### 3.6 What FCC does not do

FCC does not:

- revoke Anthropic OAuth tokens;
- delete or alter the Claude Desktop credential store;
- delete `~/.claude` or `~/.claude.json` for the Desktop integration;
- clear Claude.ai cookies or sessions;
- explicitly set `disableBundledSkills`;
- explicitly disable plugin uploads, plugin marketplaces, skill creation, local MCP, or
  desktop extensions;
- implement an Anthropic OAuth login or logout flow.

The effective loss of standard-login functionality is therefore caused by the selected 3P
profile and deployment-mode restrictions, not by an explicit feature-disable flag.

---

## 4. Vendor Behavior

### 4.1 Standard and 3P are alternative modes

Anthropic describes Claude Desktop on 3P as the standard desktop application with inference,
identity, storage, and configuration relocated according to the selected deployment:

| Capability | Standard Claude Desktop | Claude Desktop on 3P |
| --- | --- | --- |
| Model inference | Anthropic API | Configured provider or gateway |
| User identity | Anthropic account | Local device identity, unless centrally managed by Anthropic |
| Conversation storage | Anthropic backend | Local device storage |
| Web application | Loaded from claude.ai | Bundled in the desktop application |

Source: <https://claude.com/docs/third-party/claude-desktop/overview>

The modes are not two authentication layers for one request. A Desktop session runs in either
standard mode or 3P mode.

### 4.2 `deploymentMode` controls the chooser

The documented values are:

- `3p`: use the configured provider and do not offer Claude.ai sign-in;
- `1p`: use Claude.ai and ignore provider/bootstrap configuration;
- `any`: equivalent to omitting the key; the user may choose at sign-in.

The current implementation therefore intentionally selects the most restrictive documented
value, `3p`.

Source: <https://claude.com/docs/third-party/claude-desktop/mdm#restrict-a-device-to-one-deployment-mode>

The configuration reference also states that `inferenceProvider` activates third-party mode,
but a configured provider does not remove the Claude.ai choice unless `deploymentMode` is `3p`
or `disableDeploymentModeChooser` is enabled.

Source: <https://claude.com/docs/third-party/claude-desktop/configuration#inferenceprovider>

### 4.3 Desktop gateway routing does not use `ANTHROPIC_BASE_URL`

Anthropic documents that the Desktop application reads gateway routing from its third-party
inference configuration, not from `ANTHROPIC_BASE_URL` or `~/.claude/settings.json`.

Source: <https://code.claude.com/docs/en/llm-gateway-connect#desktop-app>

FCC's use of `configLibrary` is therefore the correct Desktop integration mechanism. Adding
environment variables alone would not route Desktop inference through FCC.

### 4.4 Skills, plugins, and connectors in 3P

Anthropic states that Claude Desktop on 3P supports MCP connectors, skills, and plugins. The
main difference is that administrators generally provision them through managed configuration
and the filesystem.

The documented layers are:

1. managed MCP servers;
2. organization plugins;
3. user extensions.

Source: <https://claude.com/docs/third-party/claude-desktop/extensions>

The behavior is not identical to a Claude.ai-backed standard session:

- user-added extensions are stored locally and apply to that device;
- the documented marketplace synchronization concerns administratively managed marketplace
  revisions, not continuous synchronization of a user's Claude.ai account;
- Claude.ai import is an explicit export/import operation, and imported plugins and skills
  arrive disabled;
- connectors labeled "Made by Anthropic" are hosted on Anthropic infrastructure and are
  available only in standard Claude Desktop;
- other directory connectors can be installed and used in 3P;
- Microsoft 365, GitHub, and web search are available as managed built-in servers.

Sources:

- <https://claude.com/docs/third-party/claude-desktop/extensions>
- <https://claude.com/docs/third-party/claude-desktop/built-in-connectors>

### 4.5 Data shared between modes

When a device is not restricted to one deployment mode, the user may switch between standard
and 3P Desktop. Some data is shared, including Claude Code setup under `~/.claude` and
`~/.claude.json`, and Code session transcripts under `~/.claude/projects/`.

Standard Desktop does not load 3P user-added connectors, plugins, or extensions outside Code.
Conversely, the 3P identity does not continuously synchronize the user's Claude.ai plugin and
skill inventory.

Source: <https://claude.com/docs/third-party/claude-desktop/data-storage#data-shared-with-standard-claude-desktop>

### 4.6 `hybridPointer` is not publicly documented

`hybridPointer` does not appear in the reviewed public configuration reference or extension
documentation. It is an internal value in the `configLibrary/_meta.json` structure used by
the current FCC implementation.

Consequently:

- FCC must not synthesize an undocumented pointer value;
- the safest change is to preserve the existing value byte-for-byte;
- if the pointer is absent, the implementation must remain valid;
- compatibility must be verified against live Desktop releases and diagnostic logs.

---

## 5. Feasibility Assessment

### 5.1 Goal A — Claude.ai login and gateway simultaneously

**Not supported by Claude Desktop's documented deployment model.**

The standard identity and the 3P provider identity are alternative session contexts. A
Claude.ai login does not become the identity of a 3P gateway session, and Anthropic-hosted
connectors remain unavailable in 3P.

No FCC-only configuration can make these two deployment identities simultaneous in the same
Desktop session without relying on unsupported private behavior.

### 5.2 Goal B — Gateway with the complete local 3P feature set

**Supported.**

Claude Desktop on 3P supports connectors, skills, plugins, Chat, Cowork, and Code. FCC may
therefore use the gateway without disabling those capabilities. Users may need to install or
provision local equivalents of account-backed extensions.

### 5.3 Goal C — Preserve normal login and allow a user-selected gateway

**Supported and recommended.**

FCC can:

- leave the deployment chooser available by using `deploymentMode: "any"`;
- preserve `hybridPointer`;
- select the FCC gateway profile when the user chooses the provider configuration;
- restore the previously applied profile and native login state when the user disconnects.

This does not make standard and 3P identities simultaneous. It makes the transition safe,
reversible, and non-destructive.

---

## 6. Recommended Design

### 6.1 Make the integration reversible

The FCC-owned profile should be treated as an additional saved Desktop configuration, not as
a replacement for the native login state.

Recommended invariants:

1. Connect never removes `hybridPointer`.
2. Connect uses `deploymentMode: "any"` unless the user explicitly opts into gateway-only mode.
3. Connect records enough state to identify the profile that was selected before FCC applied
   its own profile.
4. Disconnect restores the previous profile, `hybridPointer`, and deployment mode.
5. If the previous state cannot be restored safely, leave the Desktop configuration valid and
   report that standard sign-in remains available.
6. Refresh only updates the FCC-owned gateway fields and never changes login-related state.

### 6.2 Preserve backward compatibility

The repository may be used with Claude Desktop versions predating `deploymentMode`. The
implementation should therefore consider:

- `disableDeploymentModeChooser`;
- `deploymentMode: "any"` on newer releases;
- the absence of either key on older releases.

The implementation must not assume that a version-specific key was read successfully without
observing the effective Desktop behavior.

### 6.3 Keep the scope explicit

The implementation should not attempt to:

- proxy or replicate Anthropic-hosted connector traffic;
- manufacture account synchronization between standard and 3P modes;
- patch private Claude Desktop binaries;
- store or proxy Anthropic OAuth credentials;
- change Claude Desktop's local credential store.

### 6.4 Preserve existing safety and ownership properties

The redesign must keep:

- the dedicated FCC profile ID;
- merge-based profile updates;
- preservation of unrelated profile fields;
- loopback-or-HTTPS gateway validation;
- bounded local proxy authentication;
- idempotent refresh;
- the pending-disconnect recovery marker;
- rollback and retry safety;
- conservative behavior for MDM-managed installations.

---

## 7. Expected User Experience

After implementation:

1. The user connects FCC from the Admin UI.
2. FCC saves a gateway profile but leaves the standard Claude Desktop login available.
3. On the next Claude Desktop launch, the user can choose:
   - the configured FCC gateway, or
   - normal Claude.ai sign-in.
4. Choosing the gateway routes inference through FCC and exposes the 3P-local connector,
   skill, and plugin environment.
5. Choosing Claude.ai restores the normal account-backed experience without FCC having
   removed or rewritten native credentials.
6. Disconnecting FCC restores the profile that was previously selected and leaves the Desktop
   application in a valid chooser-enabled state.

---

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| `hybridPointer` has undocumented version-specific semantics | Login or 3P selection may fail after upgrade | Preserve rather than synthesize it; test multiple Desktop versions and inspect diagnostic reports |
| `deploymentMode: "any"` is not recognized by older Desktop releases | Chooser may still be disabled | Detect effective mode from the app or provide a compatibility fallback |
| Users expect Claude.ai account content to sync into 3P | Missing skills, plugins, or connectors | Document the distinction and offer managed/local provisioning |
| Disconnect cannot identify the previous profile | Loss of the user's active Desktop configuration | Persist a disconnect journal before mutation and restore the recorded profile atomically |
| A user changes `_meta.json` while FCC is running | Stale restore state | Revalidate ownership and current metadata before every restore; never overwrite a newer user-owned selection |
| Existing tests encode the old `3p` contract | Behavioral regression or false failures | Update tests deliberately and add compatibility tests for both `any` and explicit `3p` |
| Admin-managed Desktop installations reject local changes | Connect fails | Preserve the existing managed-policy guard and surface a clear error |

---

## 9. Success Criteria

The analysis is implemented successfully when:

- FCC no longer deletes or removes `hybridPointer` during a normal connection;
- the default Desktop integration leaves the Claude.ai sign-in choice available;
- the FCC gateway remains selectable and routes inference to the configured provider;
- disconnect restores the previously selected Desktop profile;
- a Claude.ai sign-in remains possible after an FCC connection;
- skills, plugins, and connectors are not explicitly disabled by FCC;
- documentation clearly states that Anthropic-hosted account connectors remain exclusive to
  standard Claude Desktop;
- unit, API, runtime, cleanup, and end-to-end tests cover the new reversible lifecycle;
- the implementation passes the repository's lint, type-check, and focused test commands.

---

## 10. Open Decisions

The implementation plan identifies the following decisions for maintainers:

1. **Default deployment policy.** Recommended: `any`, preserving normal login. An explicit
   gateway-only option may be added later as a separate opt-in.
2. **Restore policy.** Recommended: restore the exact previous profile. Fallback: select the
   native/default profile without rewriting unknown state.
3. **Compatibility policy.** Recommended: preserve `hybridPointer` and treat `any` as the
   default, without synthesizing undocumented values.
4. **Opt-in gateway-only mode.** Recommended: defer it until the reversible lifecycle is
   stable, then expose it separately from the normal Connect action.
5. **Minimum supported Desktop version.** Must be established from the installed release and
   the version requirements of `deploymentMode: "any"`.
