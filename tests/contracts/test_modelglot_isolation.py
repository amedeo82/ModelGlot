"""Runtime identity and isolation contracts for ModelGlot."""

import re
import tomllib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from free_claude_code.config import env_migrations, paths
from free_claude_code.config.loader import compose_settings_snapshot
from free_claude_code.config.settings import ENV_KEY_BY_SETTING, Settings
from free_claude_code.harnesses import claude_desktop_integration
from tests.wire_payload import object_payload

_ROOT = Path(__file__).resolve().parents[2]


def _runtime_texts() -> list[tuple[str, str]]:
    package = _ROOT / "src" / "free_claude_code"
    return [
        (path.relative_to(package).as_posix(), path.read_text(encoding="utf-8"))
        for path in package.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".js", ".ts", ".html", ".md", ".json", ".txt"}
    ]


def _repository_files() -> list[tuple[str, Path]]:
    ignored = {
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".smoke-results",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "test-results",
        "untracked",
    }
    files: list[tuple[str, Path]] = []
    for path in _ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(_ROOT)
        if relative.parts[0] in ignored or "__pycache__" in relative.parts:
            continue
        if relative.as_posix() == "uv.lock":
            continue
        files.append((relative.as_posix(), path))
    return files


def test_repository_has_no_legacy_identity_in_paths_or_text() -> None:
    legacy_prefix = "f" + "cc"
    forbidden = (
        legacy_prefix,
        "Free " + "Claude Code",
        "free-" + "claude-code",
        "Claude Code " + "Proxy",
    )
    offenders: list[tuple[str, str]] = []
    for relative, path in _repository_files():
        offenders.extend(
            (relative, marker)
            for marker in forbidden
            if marker.casefold() in relative.casefold()
        )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        offenders.extend(
            (relative, marker)
            for marker in forbidden
            if marker.casefold() in text.casefold()
        )

    assert offenders == []


def test_runtime_and_packaging_have_no_legacy_identity() -> None:
    legacy_prefix = "f" + "cc"
    forbidden = (
        legacy_prefix,
        "Free " + "Claude Code",
        "free-" + "claude-code",
        "Claude Code " + "Proxy",
    )
    offenders = [
        (name, marker)
        for name, text in [*_runtime_texts(), ("pyproject.toml", _pyproject_text())]
        for marker in forbidden
        if marker.casefold() in text.casefold()
    ]

    assert offenders == []


def test_legacy_port_8082_does_not_return() -> None:
    offenders = [
        name
        for name, text in [*_runtime_texts(), ("pyproject.toml", _pyproject_text())]
        if re.search(r"(?<!\d)8082(?!\d)", text)
    ]

    assert offenders == []
    assert Settings().port == 16969


def _pyproject_text() -> str:
    return (_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_packaging_exposes_only_modelglot_update_scripts() -> None:
    project = object_payload(tomllib.loads(_pyproject_text()))
    tool = object_payload(project["tool"])
    hatch = object_payload(tool["hatch"])
    build = object_payload(hatch["build"])
    metadata = object_payload(project["project"])
    targets = object_payload(build["targets"])
    wheel = object_payload(targets["wheel"])

    assert set(object_payload(metadata["scripts"])) == {
        "modelglot-server",
        "modelglot-doctor",
        "modelglot-claude",
        "modelglot-codex",
        "modelglot-pi",
        "modelglot-opencode",
        "modelglot-cline",
        "modelglot-hermes",
        "modelglot-dsh",
        "modelglot-grok",
        "modelglot-muse",
        "modelglot-agy",
        "modelglot-aider",
    }
    assert object_payload(metadata["gui-scripts"]) == {
        "modelglot-desktop": "free_claude_code.cli.desktop_entrypoint:launch"
    }
    assert object_payload(wheel["shared-scripts"]) == {
        "scripts/update/modelglot-update": "modelglot-update",
        "scripts/update/modelglot-update.cmd": "modelglot-update.cmd",
    }


def test_modelglot_environment_has_no_legacy_or_unscoped_server_fallback() -> None:
    legacy_prefix = "f" + "cc"
    snapshot = compose_settings_snapshot(
        {},
        {
            f"{legacy_prefix.upper()}_HOST": "192.0.2.1",
            f"{legacy_prefix.upper()}_PORT": "8082",
            f"{legacy_prefix.upper()}_OPEN_BROWSER": "false",
            f"{legacy_prefix.upper()}_CUSTOM_PROVIDERS": "[]",
            "HOST": "192.0.2.2",
            "PORT": "8082",
            "MODELGLOT_HOST": "127.0.0.1",
            "MODELGLOT_PORT": "16969",
            "MODELGLOT_OPEN_BROWSER": "false",
        },
    )

    assert snapshot.settings.host == "127.0.0.1"
    assert snapshot.settings.port == 16969
    assert snapshot.settings.open_admin_browser is False
    assert not any(
        key.casefold().startswith(f"{legacy_prefix}_")
        for key in ENV_KEY_BY_SETTING.values()
    )
    assert ENV_KEY_BY_SETTING["host"] == "MODELGLOT_HOST"
    assert ENV_KEY_BY_SETTING["port"] == "MODELGLOT_PORT"


def test_state_paths_use_only_modelglot_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert paths.config_dir_path() == tmp_path / ".modelglot"
    assert paths.managed_env_path() == tmp_path / ".modelglot" / ".env"
    assert paths.modelglot_database_path() == (tmp_path / ".modelglot" / "modelglot.db")
    assert paths.server_log_path() == (tmp_path / ".modelglot" / "logs" / "server.log")
    assert paths.launcher_temp_dir_path() == (
        tmp_path / ".modelglot" / "tmp" / "launchers"
    )
    assert paths.model_catalog_cache_path().is_relative_to(tmp_path / ".modelglot")


def test_legacy_files_and_environment_are_not_imported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    managed = tmp_path / ".modelglot" / ".env"
    monkeypatch.setattr(env_migrations, "managed_env_path", lambda: managed)
    legacy_prefix = "f" + "cc"
    legacy_files = (
        tmp_path / f".{legacy_prefix}" / ".env",
        tmp_path / ("free-" + "claude-code") / ".env",
        tmp_path / ".config" / ("free-" + "claude-code") / ".env",
        tmp_path / "checkout" / ".env",
    )
    for legacy in legacy_files:
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("MODEL=deepseek/legacy\n", encoding="utf-8")

    result = env_migrations.consolidate_managed_config(
        {
            f"{legacy_prefix.upper()}_ENV_FILE": str(legacy_files[0]),
            f"{legacy_prefix.upper()}_CONFIG_SCHEMA": "99",
        }
    )

    assert result.imported_from == ()
    assert set(env_migrations.dotenv_values_from_file(managed)) == {
        "MODELGLOT_CONFIG_SCHEMA"
    }


def test_claude_desktop_identity_is_derived_from_modelglot_url() -> None:
    identity = "https://github.com/amedeo82/ModelGlot/integrations/claude-desktop"

    assert identity == claude_desktop_integration._IDENTITY
    assert str(uuid5(NAMESPACE_URL, identity)) == (
        claude_desktop_integration.MODELGLOT_ID
    )
    assert str(uuid5(NAMESPACE_URL, identity + "/default")) == (
        claude_desktop_integration.DEFAULT_ID
    )
    assert claude_desktop_integration._VIEW_HEADER == "X-ModelGlot-Model-View"
