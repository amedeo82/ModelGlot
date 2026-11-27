# Releasing ModelGlot

This runbook is for repository maintainers and authorized release operators. It
covers the first ModelGlot release, ordinary releases, retries, and recovery.
Coding agents must not execute the external release steps unless the user
explicitly authorizes them.

## Release ownership

- Repository: `amedeo82/ModelGlot`
- Publishing workflow: `.github/workflows/post-merge.yml`
- GitHub environment: `pypi`
- PyPI distribution: `modelglot`
- Release-intent check: `.github/workflows/version-policy.yml`
- Publisher implementation: `scripts/publish_release.py`
- Artifact validator: `scripts/validate_release.py`
- Version policy: `scripts/check_version_policy.py`

`origin` is the ModelGlot repository. `upstream` is read-only integration
history and must never be pushed to. The ModelGlot publisher, GitHub Releases,
tags, and PyPI publisher must all identify `amedeo82/ModelGlot`; never reuse
upstream publishing identities or release identifiers.

## What the publisher does

A successful release performs these operations in order:

1. Validates the release target as a full commit SHA on `main`'s first-parent
   history.
2. Determines the release intent from the commit title and changed paths.
3. Finds the previous published ModelGlot release tag.
4. Calculates the next semantic version.
5. Creates and pushes the `vX.Y.Z` tag.
6. Creates a draft GitHub Release with generated notes.
7. Builds the wheel and source distribution from a clean detached worktree at
   the release commit.
8. Validates metadata, entry points, package contents, and native templates.
9. Uploads the wheel and source distribution as GitHub Release assets and
    verifies their digests.
10. Publishes the same artifacts to PyPI using OIDC trusted publishing.
11. Makes the GitHub Release public and marks it as the latest release.

The publisher is intentionally serial. It refuses to skip an unfinished
earlier release and supports retrying the same release commit.

## Prerequisites

Complete these checks before enabling or triggering the publishing workflow.

### 1. Protect `main`

`main` must require pull requests and the stable CI checks. Require the
following check contexts rather than individual shard jobs:

- `Ban suppressions and legacy annotations`
- `ruff-format`
- `ruff-check`
- `pyrefly`
- `Version policy`
- `pytest`
- `playwright`

GitHub may display these names with the workflow prefix. Configure the names
shown by the branch-protection interface. Also require the branch to be up to
date before merging when practical.

The post-merge publisher does not wait for PR CI, so branch protection is the
primary guard against publishing an unverified commit.

### 2. Configure the GitHub `pypi` environment

The environment should:

- restrict deployments to `main`;
- require an authorized reviewer;
- avoid self-review restrictions only if the repository owner is intentionally
  the sole approver;
- contain no long-lived PyPI token because publishing uses OIDC.

Verify the environment and branch policy without changing them:

```powershell
gh api repos/amedeo82/ModelGlot/environments
gh api repos/amedeo82/ModelGlot/environments/pypi/deployment-branch-policies
```

### 3. Configure PyPI Trusted Publishing

The `modelglot` project may not exist yet. In that case, create a pending
publisher from the PyPI account's **Publishing** page with these values:

| Field | Value |
|---|---|
| Distribution/project name | `modelglot` |
| GitHub owner | `amedeo82` |
| GitHub repository | `ModelGlot` |
| GitHub Actions workflow | `post-merge.yml` |
| GitHub environment | `pypi` |

The workflow filename is the basename, not the full path. The pending publisher
must match the distribution name in `pyproject.toml` exactly.

A pending publisher does not reserve the project name until its first
successful upload. Configure it and complete the first release promptly.

### 4. Verify the workflow and tools

```powershell
gh auth status
gh workflow list --repo amedeo82/ModelGlot --all
uv --version
```

`Post merge` must be active before dispatching it. Enabling or disabling a
workflow is a repository-settings change and requires explicit maintainer
authorization.

```powershell
gh workflow enable post-merge.yml --repo amedeo82/ModelGlot
```

## Release intent

The title of a merged pull request determines the version increment.

| Changed release paths | Title | Result |
|---|---|---|
| Yes | `patch: <description>` | Patch increment |
| Yes | `minor: <description>` | Minor increment |
| Yes | `major: <description>` | Major increment |
| No | No release prefix | No release |

A change touches release paths when it modifies any of:

- `assets/`
- `scripts/`
- `src/`
- `pyproject.toml`
- `uv.lock`

Use exactly one space after the colon. Documentation-only and tests-only pull
requests must not use a release prefix. Never edit a version number in
`pyproject.toml`; the version comes from the Git tag through `hatch-vcs`.

A backwards-compatible feature normally uses `minor:`. A corrective change
normally uses `patch:`. Use `major:` for an incompatible public-contract,
migration, packaging-identity, or runtime-isolation change.

## Ordinary release procedure

1. Implement and verify the change on a branch.
2. Open a pull request with the correct release-intent title.
3. Wait for CI and `Release intent` to pass.
4. Merge the approved pull request into `main`.
5. The `push` trigger starts `Post merge` automatically.
6. Review the `Publish to PyPI` deployment and approve it if the environment
   requests approval.
7. Confirm that the run created the expected tag, GitHub Release, wheel, source
   distribution, and PyPI release.
8. Install the published version in a clean environment as a smoke test.

Useful commands:

```powershell
gh run list --repo amedeo82/ModelGlot --workflow post-merge.yml --limit 10
gh run view <run-id> --repo amedeo82/ModelGlot --log-failed
gh release list --repo amedeo82/ModelGlot
gh release view vX.Y.Z --repo amedeo82/ModelGlot
```

A PyPI release is available at:

```text
https://pypi.org/project/modelglot/
```

Allow for normal PyPI index propagation before diagnosing a missing version.

## Initial ModelGlot bootstrap

The bootstrap exists because the rebranded ModelGlot history does not have a
published ModelGlot baseline tag. It is a one-time operation for version
`7.0.0` and must not be repeated after that version exists.

### Preconditions

Do not bootstrap if `v7.0.0` already exists locally, on `origin`, as a GitHub
Release, or on PyPI. Check all relevant state first:

```powershell
git ls-remote --tags origin refs/tags/v7.0.0
gh release view v7.0.0 --repo amedeo82/ModelGlot
```

Also verify that `modelglot` is not already published on PyPI. If any part of
the `7.0.0` release already exists, inspect it instead of starting another
release. A matching tag and draft can be resumed with the same bootstrap
command; an already published matching release is a no-op. Stop for maintainer
review if the tag points to another commit or a release has no matching tag.

### Required order

The rebranding and subsequent runtime changes must be released in this order:

| Release commit | Intent | Version |
|---|---|---|
| `a8fa836e344e35e697c6114872c59b6bcccf181d` | `major: Rename Python namespace to ModelGlot (#8)` | `7.0.0` |
| `62cd58fe90468ac4f7712d70661fd6ecba59d51c` | `patch: Integrate upstream request hints and search fixes (#9)` | `7.0.1` |
| `553c3a10e63acda1ee1cd647d7bbe7b534653bc7` | `patch: Integrate upstream unsigned thinking stream recovery` | `7.0.2` |

Documentation-only commits between these commits do not receive releases.

### Publish `7.0.0`

Dispatch `Post merge` with the exact bootstrap commit and the fixed bootstrap
version:

```powershell
gh workflow run post-merge.yml `
  --repo amedeo82/ModelGlot `
  --ref main `
  -f release_commit=a8fa836e344e35e697c6114872c59b6bcccf181d `
  -f bootstrap_version=7.0.0
```

The bootstrap accepts only `7.0.0` and only a major release commit. It skips
legacy upstream release history and creates the first ModelGlot tag.

### Publish `7.0.1` and `7.0.2`

After `7.0.0` completes successfully, dispatch the next release commit without
`bootstrap_version`:

```powershell
gh workflow run post-merge.yml `
  --repo amedeo82/ModelGlot `
  --ref main `
  -f release_commit=62cd58fe90468ac4f7712d70661fd6ecba59d51c
```

```powershell
gh workflow run post-merge.yml `
  --repo amedeo82/ModelGlot `
  --ref main `
  -f release_commit=553c3a10e63acda1ee1cd647d7bbe7b534653bc7
```

Do not dispatch `7.0.2` until `7.0.1` is complete. The publisher intentionally
rejects a later release when an earlier release is unfinished.

## Retry and recovery

A failed ordinary publication must be retried with the same full release
commit. Do not create a replacement tag manually and do not change the requested
version.

```powershell
gh workflow run post-merge.yml `
  --repo amedeo82/ModelGlot `
  --ref main `
  -f release_commit=<full-release-commit-sha>
```

Do not supply `bootstrap_version` during an ordinary retry. For an interrupted
initial `7.0.0` bootstrap, rerun the same bootstrap command with
`bootstrap_version=7.0.0`. The publisher resumes a matching tag and draft;
it rejects a tag for another commit and does not rebuild an already published
matching release.

Inspect the failed step before retrying:

```powershell
gh run view <run-id> --repo amedeo82/ModelGlot --log-failed
```

Common failures and responses:

| Failure | Meaning | Response |
|---|---|---|
| `No baseline release tag found` | The initial ModelGlot baseline has not been published | Complete the `7.0.0` bootstrap first |
| `Earlier release ... is unfinished` | A prior release in the sequence failed | Retry the prior full commit and wait for completion |
| `ModelGlot bootstrap version must be 7.0.0` | An invalid bootstrap value was supplied | Use `7.0.0` only for the initial bootstrap |
| `ModelGlot bootstrap requires a major release` | The bootstrap target is not a major release commit | Select the recorded major rebranding commit |
| `Tag v7.0.0 belongs to a different commit` | Existing bootstrap state does not match the requested target | Stop and inspect the tag and release before any mutation |
| `Release v7.0.0 has no matching remote tag` | The draft and remote tag are inconsistent | Stop; do not create or delete tags by hand while investigating the inconsistent state |
| PyPI rejects the publisher identity | PyPI trusted-publisher values do not match the workflow | Recreate the pending publisher with owner, repository, workflow, and environment matching this runbook |
| The deployment waits for approval | The `pypi` environment requires review | An authorized maintainer must approve the deployment |
| No workflow run starts | `Post merge` is disabled or the event did not match | Verify workflow state and the `main` trigger |

PyPI versions are immutable. Never attempt to replace an already published
`modelglot` version with different bytes. If a published release is defective,
publish a corrective patch with a new version.

If a release was pushed to PyPI but the GitHub Release was not finalized, retry
the same commit. The publisher recognizes the existing release and staged
assets and completes the remaining finalization safely.

## Verification checklist

After each release, verify all of the following:

- The GitHub Actions run completed successfully.
- The expected `vX.Y.Z` tag points to the requested full commit SHA.
- The GitHub Release is public, is the latest release, and is not a prerelease.
- The release contains exactly one wheel and one source distribution.
- The wheel and source distribution have the expected `modelglot-X.Y.Z` names.
- The GitHub release assets have matching digests and sizes.
- PyPI exposes the same version and distribution metadata.
- A clean installation can import `modelglot` and run `modelglot-server
  --version`.
- The installable version matches the GitHub release version.

Example installation check:

```powershell
uvx --from "modelglot==X.Y.Z" modelglot-server --version
```

## Release changes to the pipeline

Changes to the release system require focused contract tests and the complete
local CI sequence:

```bash
uv run --locked pytest \
  tests/scripts/test_version_policy.py \
  tests/scripts/test_release_workflow.py \
  tests/scripts/test_publish_release.py \
  tests/scripts/test_release_package.py
```

Then run:

```bash
./scripts/ci.sh
```

```powershell
.\scripts\ci.ps1
```

Do not publish while validating a release-system change. Merge and test the
pipeline change first, then perform the separately authorized release.
