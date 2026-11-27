# ModelGlot agent rules

These rules apply to the entire repository. A more specific `AGENTS.md` in a
subdirectory overrides these rules only for that subtree.

## Project identity

ModelGlot is an independent project maintained in
`https://github.com/amedeo82/ModelGlot`. It is based on an upstream codebase but
must not depend on upstream runtime identity, state, commands, environment
variables, releases, or publishing infrastructure.

- Use the `modelglot` package, `modelglot-*` commands, `MODELGLOT_*` settings,
  and `src/modelglot/` paths.
- Do not restore legacy aliases, compatibility imports, shared state, or
  upstream release identifiers unless a documented, tested public contract
  explicitly requires one.
- Preserve the isolation contracts in
  `tests/contracts/test_modelglot_isolation.py`.
- `origin` is `amedeo82/ModelGlot`. `upstream` is read-only integration
  history. Never push to `upstream`.
- Do not publish, tag, release, change GitHub settings, or push to `origin`
  unless the user explicitly requests that action.

## Source of truth

Read the relevant documents before changing a subsystem:

- `CONTRIBUTING.md` for contribution and release-intent rules.
- `docs/architecture-analysis.md` for the architecture and known quality gaps.
- `docs/implementation-plan.md` for tracked implementation work.
- `docs/releasing.md` for maintainer release, bootstrap, retry, and recovery
  procedures.
- `docs/local-ci-troubleshooting.md` for the fast diagnosis of known local CI
  and Playwright startup failures.
- `README.md` for user-visible behavior and installation.
- A subtree `AGENTS.md`, when present, for subsystem-specific rules.

Prefer existing project utilities and patterns over new parallel abstractions.
Keep changes focused and do not overwrite unrelated work.

## Development workflow

1. Inspect the current branch, working tree, relevant tests, and relevant
   documentation before editing.
2. Classify the change and select the correct pull-request title using the
   release-intent rules below.
3. Implement the smallest coherent change.
4. Add or update focused tests, including relevant failure and edge cases.
5. Update user-facing documentation in the same change when behavior changes.
6. Run focused checks, then the complete local CI sequence.
7. Review the final diff for secrets, generated files, unrelated changes, and
   release metadata before committing.

Use `uv` for every Python command. The project requires the exact Python
version declared in `pyproject.toml`; do not use a global interpreter.

```bash
uv run --locked pytest tests/path/to/relevant_test.py
uv run --locked ruff format --check
uv run --locked ruff check
uv run --locked pyrefly check
```

Run the complete CI-equivalent sequence before proposing a pull request:

```bash
./scripts/ci.sh
```

```powershell
.\scripts\ci.ps1
```

The local scripts repair formatting and autofixable lint issues. Re-run them
and inspect the diff after any automatic modification.

## Change classification and pull-request titles

The release policy is implemented in `scripts/check_version_policy.py`.

| Change | Title | Release |
|---|---|---|
| Bug fix or corrective maintenance that changes release paths | `patch: <description>` | Patch |
| Backwards-compatible feature or new capability | `minor: <description>` | Minor |
| Breaking change, migration, packaging identity change, or incompatible contract change | `major: <description>` | Major |
| Documentation or tests only, with no release-path change | No release prefix | None |

Use exactly one space after the colon and write a useful description.

A pull request changes release paths when it modifies any of:

- `assets/`
- `scripts/`
- `src/`
- `pyproject.toml`
- `uv.lock`

Do not use a release prefix for a pull request that changes none of those
paths. Do not use a release prefix on a documentation-only change, and do not
edit version numbers manually. Publishing calculates the version from the
previous published tag and the pull-request title.

Standalone documentation pull requests are reserved for the repository owner.
Accompany documentation changes with production changes whenever possible.

## New functionality

- Define the user-visible or operator-visible outcome before implementation.
- Keep the change within the owning provider, subsystem, or runtime boundary.
- Preserve public model identifiers, routing behavior, capability claims, and
  persistence semantics unless the change is explicitly a breaking migration.
- Add the feature to the appropriate manifest or capability contract when the
  repository already requires one.
- Add deterministic tests for the behavior and its relevant edge cases.
- Update README or the relevant `docs/` page in the same change.
- Prefer `minor:` for a backwards-compatible feature and `major:` for an
  incompatible change.

## Bug fixes

- Reproduce the failure and identify its actual owner before changing code.
- Add a regression test that fails before the fix and passes after it.
- Preserve the failing input, error, affected model/provider, and relevant
  environment details in the bug report.
- Fix the root cause rather than suppressing the symptom.
- Use `patch:` when the fix changes release paths. Avoid unrelated refactors
  in the same pull request.

## Release-path changes

Changes under `assets/`, `scripts/`, `src/`, `pyproject.toml`, or `uv.lock`
participate in versioning. In addition to application tests, run the release
contract suite before handing off such a change:

```bash
uv run --locked pytest \
  tests/scripts/test_version_policy.py \
  tests/scripts/test_release_workflow.py \
  tests/scripts/test_publish_release.py \
  tests/scripts/test_release_package.py
```

Never edit a version string, create a release tag manually, or publish a wheel
or sdist by hand as part of normal development. The release publisher owns
version calculation, tagging, artifact validation, GitHub Releases, and PyPI.

Release execution is a separate, explicitly authorized maintainer operation.
Follow `docs/releasing.md`; do not enable the publishing workflow, trigger a
release, approve the `pypi` environment, or publish to PyPI merely because
release-path files changed.

## Engineering invariants

- Target Python 3.14 and use native lazy annotations. Do not add
  `from __future__ import annotations`.
- Do not add `# type: ignore`, `# ty: ignore`, or `# pyrefly: ignore`.
  Resolve the underlying typing or import-boundary problem.
- Keep shared Anthropic protocol behavior in
  `src/modelglot/core/anthropic/`.
- Keep provider-specific configuration in the provider that owns it.
- Preserve import boundaries and acyclicity enforced by
  `tests/contracts/test_import_boundaries.py`.
- Keep provider catalog metadata honest: do not invent model IDs,
  capabilities, limits, prices, modalities, or release state.
- Never log, serialize, or commit credentials, tokens, proxy secrets, or
  private provider configuration.
- Remove dead compatibility code when completing a migration unless preserving
  a published interface is explicitly required.
- Do not weaken tests, delete coverage, or change assertions merely to make a
  change pass.

## Git and external-system safety

- Do not commit or push unless explicitly requested.
- Before committing, inspect `git status`, `git diff`, and recent history, and
  stage only intended files.
- Do not force-push, rewrite published history, or alter tags already pushed
  to `origin`.
- Do not change branch protection, GitHub environments, workflow state, PyPI
  publishers, or repository secrets without explicit authorization.
- Treat GitHub Actions, PyPI, GitHub Releases, and the upstream repository as
  external side effects. A request to implement or test code is not permission
  to publish it.
- Use redacted diagnostics in reports. Never expose secret values while
  debugging CI or release failures.

## Completion criteria

A coding task is complete only when the implementation is present, relevant
tests and documentation are updated, the required quality checks pass, and the
final diff contains only intended changes. Report verification results and any
remaining external release step separately.
