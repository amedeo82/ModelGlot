"""Connect native Codex clients through their shared TOML configuration."""

import json
import os
from pathlib import Path

import tomlkit
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.exceptions import ParseError
from tomlkit.items import InlineTable, Table
from tomlkit.toml_document import TOMLDocument

from free_claude_code.config.server_urls import proxy_v1_url, same_proxy_url
from free_claude_code.core.json_types import JsonObject
from free_claude_code.harnesses.codex import (
    PRINT_PROXY_AUTH_TOKEN_FLAG,
    codex_config_values,
)
from free_claude_code.harnesses.codex_model_catalog import (
    CODEX_CATALOG_SCHEMA_VERSION,
    validate_codex_model_catalog,
)
from free_claude_code.harnesses.config_file import atomic_write_text

CODEX_SUPPORTED_SURFACES = (
    "codex_cli",
    "codex_ide_extension",
    "chatgpt_desktop_codex",
)


def config_path() -> Path:
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return root / "config.toml"


def _child_table(
    parent: TOMLDocument | Table | InlineTable | OutOfOrderTableProxy,
    key: str,
    *,
    create: bool = False,
) -> Table | InlineTable | OutOfOrderTableProxy:
    if key not in parent:
        child = (
            tomlkit.inline_table()
            if isinstance(parent, InlineTable)
            else tomlkit.table()
        )
        if create:
            parent[key] = child
        return child
    child = parent[key]
    if not isinstance(child, Table | InlineTable | OutOfOrderTableProxy):
        raise ValueError("Codex provider configuration must use TOML tables")
    return child


def _read(path: Path) -> TOMLDocument:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return tomlkit.document()
    try:
        document = tomlkit.parse(content)
    except ParseError:
        raise ValueError("Invalid Codex TOML") from None
    providers = _child_table(document, "model_providers")
    provider = _child_table(providers, "fcc")
    _child_table(provider, "auth")
    return document


def _same_catalog(value: object, catalog_path: Path) -> bool:
    return (
        isinstance(value, str)
        and Path(value).is_absolute()
        and Path(value).resolve() == catalog_path
    )


def _recognizes_connection(document: TOMLDocument, proxy_root_url: str) -> bool:
    provider = _child_table(_child_table(document, "model_providers"), "fcc")
    return document.get("model_provider") == "fcc" and same_proxy_url(
        provider.get("base_url"), proxy_v1_url(proxy_root_url)
    )


def recognizes_connection(path: Path, proxy_root_url: str) -> bool:
    """Identify FCC independently of newly introduced managed settings."""
    return _recognizes_connection(_read(path.resolve()), proxy_root_url)


def _connected(document: TOMLDocument, catalog_path: Path, proxy_root_url: str) -> bool:
    provider = _child_table(_child_table(document, "model_providers"), "fcc")
    auth = _child_table(provider, "auth")
    return (
        _recognizes_connection(document, proxy_root_url)
        and _same_catalog(document.get("model_catalog_json"), catalog_path)
        and provider.get("wire_api") == "responses"
        and auth.get("command") == "fcc-codex"
        and auth.get("args") == [PRINT_PROXY_AUTH_TOKEN_FLAG]
    )


def _connect(
    path: Path, document: TOMLDocument, catalog_path: Path, proxy_root_url: str
) -> bool:
    before = tomlkit.dumps(document)
    values = codex_config_values(api_url=proxy_root_url)
    values["model_catalog_json"] = str(catalog_path)
    for dotted_key, value in values.items():
        *parents, key = dotted_key.split(".")
        parent: TOMLDocument | Table | InlineTable | OutOfOrderTableProxy = document
        for name in parents:
            parent = _child_table(parent, name, create=True)
        if parent.get(key) != value:
            parent[key] = value
    content = tomlkit.dumps(document)
    if content == before:
        return False
    atomic_write_text(path, content)
    return True


def refresh_connected(path: Path, catalog_path: Path, proxy_root_url: str) -> bool:
    """Refresh an existing FCC connection without selecting a provider or model."""
    path = path.resolve()
    document = _read(path)
    if not _recognizes_connection(document, proxy_root_url):
        return False
    return _connect(path, document, catalog_path.resolve(), proxy_root_url)


def _catalog_models(catalog_path: Path) -> tuple[bool, int, frozenset[str]]:
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return False, 0, frozenset()
    if not isinstance(payload, dict):
        return False, 0, frozenset()
    models = payload.get("models")
    if not isinstance(models, list):
        return False, 0, frozenset()
    try:
        validate_codex_model_catalog(payload)
    except ValueError:
        return False, 0, frozenset()
    slugs = frozenset(
        model["slug"]
        for model in models
        if isinstance(model, dict) and isinstance(model.get("slug"), str)
    )
    return True, len(slugs), slugs


def _diagnostics(
    document: TOMLDocument, catalog_path: Path, *, connected: bool
) -> JsonObject:
    provider_value = document.get("model_provider")
    provider = provider_value if isinstance(provider_value, str) else None
    model_value = document.get("model")
    selected_model = model_value if isinstance(model_value, str) else None
    catalog_available, model_count, catalog_slugs = _catalog_models(catalog_path)
    selected_model_available: bool | None = None
    if selected_model is not None and catalog_available:
        selected_model_available = selected_model in catalog_slugs

    warnings: list[str] = []
    if connected:
        if not catalog_available:
            warnings.append(
                "The FCC model catalog is unavailable. Refresh models, reconnect Codex, then restart Codex or ChatGPT Desktop."
            )
        if selected_model is None:
            warnings.append(
                "No Codex model is selected. Restart Codex or ChatGPT Desktop and choose an FCC model in the Codex model picker."
            )
        elif catalog_available and not selected_model_available:
            warnings.append(
                "The selected Codex model is not in the FCC catalog. Restart Codex or ChatGPT Desktop and choose an FCC model in the Codex model picker."
            )
        if provider != "fcc":
            warnings.append(
                "FCC is not the selected Codex provider. Reconnect Codex to select it."
            )

    return {
        "provider": provider,
        "selected_model": selected_model,
        "catalog_path": str(catalog_path),
        "catalog_available": catalog_available,
        "catalog_schema_version": CODEX_CATALOG_SCHEMA_VERSION,
        "selected_model_available": selected_model_available,
        "model_count": model_count,
        "supported_surfaces": list(CODEX_SUPPORTED_SURFACES),
        "warnings": warnings,
    }


def configure(
    path: Path, catalog_path: Path, proxy_root_url: str, connected: bool | None = None
) -> JsonObject:
    """Inspect or edit FCC's entries without changing the user's selected model."""
    path = path.resolve()
    catalog_path = catalog_path.resolve()
    document = _read(path)
    if connected is True:
        _connect(path, document, catalog_path, proxy_root_url)
    elif connected is False:
        before = tomlkit.dumps(document)
        _child_table(document, "model_providers").pop("fcc", None)
        if document.get("model_provider") == "fcc":
            document.pop("model_provider")
        if _same_catalog(document.get("model_catalog_json"), catalog_path):
            document.pop("model_catalog_json")
        content = tomlkit.dumps(document)
        if content != before:
            atomic_write_text(path, content)
    if connected is not None:
        document = _read(path)
    is_connected = _connected(document, catalog_path, proxy_root_url)
    return {
        "connected": is_connected,
        "paths": {"codex_config": str(path)},
        **_diagnostics(document, catalog_path, connected=is_connected),
    }
