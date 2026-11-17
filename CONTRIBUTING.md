# Contributing

Thanks for helping improve Free Claude Code. Keep changes focused, test the behavior you change, and preserve the public Claude Code and Codex workflows.

## Before Opening A Pull Request

- Standalone documentation PRs are reserved for the repository owner.
- Include relevant README and other documentation updates with production code changes. These accompanying updates do not require a separate issue.
- Do not open Docker integration pull requests.
- For bugs, include every model mapping, the active model when the failure occurred, the complete error, and reproducible steps.
- Add focused tests for behavior changes and relevant edge cases.

## Pull Request Titles

Changes to `assets/`, `scripts/`, `src/`, `pyproject.toml`, or `uv.lock` require a title starting with `patch: `, `minor: `, or `major: ` followed by a description. Use exactly one space after the colon.

PRs without changes to those paths must not use a release prefix. Do not edit version numbers. Publishing calculates the version after merge, creates its Git tag, and publishes to PyPI and GitHub Releases.

## Development Setup

Install [uv](https://docs.astral.sh/uv/), then run directly from the checkout. uv automatically installs the Python version required by the project.

```bash
git clone --branch custom/main https://github.com/amedeo82/free-claude-code.git
cd free-claude-code
uv run fcc-server
```

Use `uv run` for Python commands. Do not run the project with a global Python interpreter.

## Quality Checks

Run the complete local CI sequence before opening a pull request:

```bash
./scripts/ci.sh
```

```powershell
.\scripts\ci.ps1
```

Useful iteration flags are `--only`, `--skip`, and `--dry-run` on macOS/Linux, or `-Only`, `-Skip`, and `-DryRun` in PowerShell.

Individual repair and test commands:

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest -v --tb=short
```

GitHub CI runs Ruff in check-only mode and also bans `# type: ignore`, `# ty: ignore`, and legacy annotation workarounds. Fix underlying typing and import-boundary problems instead of suppressing them.

## Project Documentation

### Architecture and backlog

- [`docs/architecture-analysis.md`](docs/architecture-analysis.md) records the architecture map, quality findings, and the measurement snapshot.
- [`docs/implementation-plan.md`](docs/implementation-plan.md) converts those findings into ordered implementation steps with current status, acceptance criteria, and traceability.

### Model discovery and pickers

- [`docs/model-display-names-analysis.md`](docs/model-display-names-analysis.md) and [`docs/model-display-names-implementation-plan.md`](docs/model-display-names-implementation-plan.md) document the implemented shared Terminal/Desktop descriptive-title path.
- [`docs/claude-terminal-model-display-names-analysis.md`](docs/claude-terminal-model-display-names-analysis.md) and [`docs/claude-terminal-model-display-names-implementation-plan.md`](docs/claude-terminal-model-display-names-implementation-plan.md) cover the remaining Terminal discovery compatibility and verification work.
- [`docs/model-picker-metadata-research.md`](docs/model-picker-metadata-research.md) records the proposed picker metadata enrichment.
- [`docs/model-picker-info-enrichments.md`](docs/model-picker-info-enrichments.md) summarizes the candidate model information and its presentation constraints.
- [`docs/admin-model-picker-enrichment-analysis.md`](docs/admin-model-picker-enrichment-analysis.md) records the proposed Admin model-picker enrichment design.
- [`docs/hot-to-use-models.dev.md`](docs/hot-to-use-models.dev.md) documents the models.dev endpoints and usage.

### Desktop integrations

- [`docs/claude-desktop-fcc-profile.md`](docs/claude-desktop-fcc-profile.md) documents the implemented FCC-owned Claude Desktop 3P profile and its user-visible improvements.
- [`docs/claude-desktop-gateway-login-analysis.md`](docs/claude-desktop-gateway-login-analysis.md) and [`docs/claude-desktop-gateway-login-implementation-plan.md`](docs/claude-desktop-gateway-login-implementation-plan.md) cover the proposed reversible Claude Desktop gateway/login lifecycle.
- [`docs/claude-desktop-1m-context-and-official-marketplace.md`](docs/claude-desktop-1m-context-and-official-marketplace.md) records the implemented Desktop 3P 1M-context preference and official marketplace configuration.
- [`docs/desktop-branded-notifications-analysis.md`](docs/desktop-branded-notifications-analysis.md) records the implemented Windows notification path and the remaining macOS native work.
- [`docs/windows-launcher-interrupt-cleanup.md`](docs/windows-launcher-interrupt-cleanup.md) records the resolved Windows native-client `Ctrl+C` cleanup contract.

Read the relevant project documents before proposing changes to the request path, provider layer, desktop integrations, model pickers, or CI configuration.

## Project Standards

- Target Python 3.14 and rely on native lazy annotations; do not add `from __future__ import annotations`.
- Python 3.14 supports multiple exception types without parentheses, such as `except TypeError, ValueError:`.
- Keep shared Anthropic protocol behavior under `src/free_claude_code/core/anthropic/` rather than importing utilities from another provider.
- Keep provider-specific configuration in the provider that owns it.
- Remove dead compatibility code when completing migrations unless preserving a published interface is explicitly required.
