"""Optional models.dev catalog access with a reduced local cache."""

import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import httpx

from modelglot.config.model_catalog_mapping import (
    MODEL_CATALOG_CACHE_TTL_SECONDS,
    MODEL_CATALOG_PROVIDER_MAPPING,
)
from modelglot.config.model_catalog_metadata import ModelCatalogMetadata
from modelglot.config.settings import Settings
from modelglot.core.json_types import JsonObject, JsonValue, load_json_value

MODEL_CATALOG_FETCH_TIMEOUT_SECONDS = 15.0
_MODEL_CATALOG_CACHE_SCHEMA_VERSION = 2
_MAX_MODEL_NAME_LENGTH = 512
_MAX_MODEL_DESCRIPTION_LENGTH = 4096
_MAX_METADATA_STRING_LENGTH = 256
_MAX_MODALITIES = 8
_MAX_LIMIT = 1_000_000_000
_CANONICAL_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}/[^/\s]{1,192}$")
_MODALITIES = frozenset({"text", "image", "audio", "video", "pdf"})
CatalogEntryMap = dict[tuple[str, str], tuple[str, str]]
CatalogMetadataMap = dict[tuple[str, str], ModelCatalogMetadata]


class ModelCatalogSourceError(ValueError):
    """Raised when an external model catalog payload is malformed."""


@dataclass(frozen=True, slots=True)
class ModelCatalogCache:
    """Reduced presentation metadata and its cache freshness information."""

    entries: CatalogEntryMap = field(default_factory=dict)
    fetched_at: float | None = None
    last_error: str | None = None
    metadata: CatalogMetadataMap = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        if self.fetched_at is None:
            return True
        return time.time() - self.fetched_at >= MODEL_CATALOG_CACHE_TTL_SECONDS


class ModelCatalogSource:
    """Own external catalog reads, validation, and atomic cache publication."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ModelCatalogCache:
        """Read current and legacy reduced caches without network access."""
        try:
            payload = load_json_value(self.path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return ModelCatalogCache()
        if not isinstance(payload, dict):
            return ModelCatalogCache()
        cache_payload = cast(JsonObject, payload)
        raw_fetched_at = cache_payload.get("fetched_at")
        fetched_at = (
            float(raw_fetched_at)
            if isinstance(raw_fetched_at, int | float)
            and not isinstance(raw_fetched_at, bool)
            and math.isfinite(raw_fetched_at)
            else None
        )
        entries: CatalogEntryMap = {}
        metadata: CatalogMetadataMap = {}
        raw_entries = cache_payload.get("entries")
        if isinstance(raw_entries, dict):
            entries_payload = cast(JsonObject, raw_entries)
            for provider_id, models in entries_payload.items():
                if not isinstance(models, dict):
                    continue
                models_payload = cast(JsonObject, models)
                for model_id, title in models_payload.items():
                    if isinstance(title, str):
                        entries[(provider_id, model_id)] = (title, "")
                        continue
                    if not isinstance(title, dict):
                        continue
                    title_payload = cast(JsonObject, title)
                    name = title_payload.get("name")
                    description = title_payload.get("description")
                    if not isinstance(name, str):
                        continue
                    key = (provider_id, model_id)
                    entries[key] = (
                        name,
                        description if isinstance(description, str) else "",
                    )
                    raw_metadata = title_payload.get("metadata")
                    if isinstance(raw_metadata, dict):
                        parsed = _metadata_from_mapping(
                            cast(JsonObject, raw_metadata), fetched_at
                        )
                        if parsed is not None:
                            metadata[key] = parsed
        last_error = cache_payload.get("last_error")
        return ModelCatalogCache(
            entries=entries,
            fetched_at=fetched_at,
            last_error=last_error if isinstance(last_error, str) else None,
            metadata=metadata,
        )

    async def refresh(self, settings: Settings) -> ModelCatalogCache:
        """Fetch and atomically publish the reduced catalog when enabled."""
        if settings.model_catalog_source == "none":
            return ModelCatalogCache()
        async with httpx.AsyncClient(
            timeout=MODEL_CATALOG_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            response = await client.get(settings.model_catalog_url)
            response.raise_for_status()
            payload = cast(JsonValue, response.json())
        entries, metadata = _reduce_catalog(payload)
        fetched_at = time.time()
        metadata = {
            key: replace(value, fetched_at=fetched_at)
            for key, value in metadata.items()
        }
        cache = ModelCatalogCache(
            entries=entries, fetched_at=fetched_at, metadata=metadata
        )
        self.write(cache)
        return cache

    def write(self, cache: ModelCatalogCache) -> None:
        """Publish the reduced cache atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        reduced: dict[str, dict[str, JsonObject]] = {}
        for (provider_id, model_id), (title, description) in cache.entries.items():
            record: JsonObject = {
                "name": title,
                "description": description,
            }
            metadata = cache.metadata.get((provider_id, model_id))
            metadata_payload = (
                _metadata_to_mapping(metadata) if metadata is not None else {}
            )
            if metadata_payload:
                record["metadata"] = metadata_payload
            reduced.setdefault(provider_id, {})[model_id] = record
        payload = {
            "schema_version": _MODEL_CATALOG_CACHE_SCHEMA_VERSION,
            "entries": reduced,
            "fetched_at": cache.fetched_at,
            "last_error": cache.last_error,
        }
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def reduce_model_catalog(payload: object) -> CatalogEntryMap:
    """Retain the legacy name/description projection without network access."""
    entries, _ = _reduce_catalog(payload)
    return entries


def reduce_model_catalog_metadata(payload: object) -> CatalogMetadataMap:
    """Retain validated provider-scoped catalog facts for Admin presentation."""
    _, metadata = _reduce_catalog(payload)
    return metadata


def _reduce_catalog(payload: object) -> tuple[CatalogEntryMap, CatalogMetadataMap]:
    if not isinstance(payload, dict):
        raise ModelCatalogSourceError("model catalog payload is not an object")
    catalog_payload = cast(JsonObject, payload)
    wanted = frozenset(MODEL_CATALOG_PROVIDER_MAPPING.values())
    entries: CatalogEntryMap = {}
    metadata: CatalogMetadataMap = {}
    for provider_id in wanted:
        provider = catalog_payload.get(provider_id)
        if provider is None:
            continue
        if not isinstance(provider, dict):
            raise ModelCatalogSourceError(
                f"model catalog provider {provider_id!r} is not an object"
            )
        provider_payload = cast(JsonObject, provider)
        models = provider_payload.get("models")
        if not isinstance(models, dict):
            raise ModelCatalogSourceError(
                f"model catalog provider {provider_id!r} has no models object"
            )
        models_payload = cast(JsonObject, models)
        for model_id, model in models_payload.items():
            if not isinstance(model_id, str) or not isinstance(model, dict):
                continue
            model_payload = cast(JsonObject, model)
            name = model_payload.get("name")
            description = model_payload.get("description")
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name.strip()) > _MAX_MODEL_NAME_LENGTH
            ):
                continue
            clean_description = (
                description.strip()
                if isinstance(description, str)
                and len(description.strip()) <= _MAX_MODEL_DESCRIPTION_LENGTH
                else ""
            )
            key = (provider_id, model_id)
            entries[key] = (name.strip(), clean_description)
            parsed = _metadata_from_mapping(model_payload, None)
            if parsed is not None and _metadata_to_mapping(parsed):
                metadata[key] = parsed
    return entries, metadata


def _metadata_from_mapping(
    model: JsonObject, fetched_at: float | None
) -> ModelCatalogMetadata | None:
    strings: dict[str, str | None] = {}
    for key in (
        "canonical_model_id",
        "status",
        "release_date",
        "last_updated",
        "knowledge",
    ):
        value = model.get(key)
        if value is not None and (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > _MAX_METADATA_STRING_LENGTH
        ):
            return None
        strings[key] = value.strip() if isinstance(value, str) else None
    canonical = strings["canonical_model_id"]
    if canonical is not None and not _CANONICAL_MODEL_ID.fullmatch(canonical):
        return None

    booleans: dict[str, bool | None] = {}
    for key in ("reasoning", "tool_call", "structured_output", "open_weights"):
        value = model.get(key)
        if value is not None and not isinstance(value, bool):
            return None
        booleans[key] = value

    raw_modalities = model.get("modalities")
    if raw_modalities is not None and not isinstance(raw_modalities, dict):
        return None
    modalities: dict[str, tuple[str, ...] | None] = {"input": None, "output": None}
    if isinstance(raw_modalities, dict):
        modalities_payload = cast(JsonObject, raw_modalities)
        for direction in ("input", "output"):
            values = modalities_payload.get(direction)
            if values is None:
                continue
            if not isinstance(values, list) or len(values) > _MAX_MODALITIES:
                return None
            normalized_values: list[str] = []
            for value in values:
                if not isinstance(value, str) or value not in _MODALITIES:
                    return None
                normalized_values.append(value)
            modalities[direction] = tuple(dict.fromkeys(normalized_values))

    raw_limits = model.get("limit")
    if raw_limits is not None and not isinstance(raw_limits, dict):
        return None
    limits: dict[str, int | None] = {"context": None, "input": None, "output": None}
    if isinstance(raw_limits, dict):
        limits_payload = cast(JsonObject, raw_limits)
        for key in limits:
            value = limits_payload.get(key)
            if value is None:
                continue
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 < value <= _MAX_LIMIT
            ):
                return None
            limits[key] = value

    return ModelCatalogMetadata(
        canonical_model_id=canonical,
        reasoning=booleans["reasoning"],
        tool_call=booleans["tool_call"],
        structured_output=booleans["structured_output"],
        input_modalities=modalities["input"],
        output_modalities=modalities["output"],
        context_limit=limits["context"],
        input_limit=limits["input"],
        output_limit=limits["output"],
        status=strings["status"],
        release_date=strings["release_date"],
        last_updated=strings["last_updated"],
        knowledge=strings["knowledge"],
        open_weights=booleans["open_weights"],
        fetched_at=fetched_at,
    )


def _metadata_to_mapping(metadata: ModelCatalogMetadata) -> JsonObject:
    result: JsonObject = {}
    for key, value in (
        ("canonical_model_id", metadata.canonical_model_id),
        ("reasoning", metadata.reasoning),
        ("tool_call", metadata.tool_call),
        ("structured_output", metadata.structured_output),
        ("status", metadata.status),
        ("release_date", metadata.release_date),
        ("last_updated", metadata.last_updated),
        ("knowledge", metadata.knowledge),
        ("open_weights", metadata.open_weights),
    ):
        if value is not None:
            result[key] = value
    modalities = {
        direction: list(values)
        for direction, values in (
            ("input", metadata.input_modalities),
            ("output", metadata.output_modalities),
        )
        if values is not None
    }
    if modalities:
        result["modalities"] = modalities
    limits = {
        key: value
        for key, value in (
            ("context", metadata.context_limit),
            ("input", metadata.input_limit),
            ("output", metadata.output_limit),
        )
        if value is not None
    }
    if limits:
        result["limit"] = limits
    return result
