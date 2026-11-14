"""Optional models.dev catalog access with a reduced local cache."""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from free_claude_code.config.model_catalog_mapping import (
    MODEL_CATALOG_PROVIDER_MAPPING,
)
from free_claude_code.config.settings import Settings

MODEL_CATALOG_CACHE_TTL_SECONDS = 24 * 60 * 60
MODEL_CATALOG_FETCH_TIMEOUT_SECONDS = 15.0


class ModelCatalogSourceError(ValueError):
    """Raised when an external model catalog payload is malformed."""


@dataclass(frozen=True, slots=True)
class ModelCatalogCache:
    """Reduced presentation-only model titles and their cache metadata."""

    entries: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    fetched_at: float | None = None
    last_error: str | None = None

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
        """Read a valid reduced cache without network access."""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return ModelCatalogCache()
        if not isinstance(payload, dict):
            return ModelCatalogCache()
        entries: dict[tuple[str, str], tuple[str, str]] = {}
        raw_entries = payload.get("entries")
        if isinstance(raw_entries, dict):
            for provider_id, models in raw_entries.items():
                if not isinstance(provider_id, str) or not isinstance(models, dict):
                    continue
                for model_id, title in models.items():
                    if not isinstance(model_id, str):
                        continue
                    if isinstance(title, str):
                        entries[(provider_id, model_id)] = (title, "")
                    elif isinstance(title, dict):
                        name = title.get("name")
                        description = title.get("description")
                        if isinstance(name, str):
                            entries[(provider_id, model_id)] = (
                                name,
                                description if isinstance(description, str) else "",
                            )
        fetched_at = payload.get("fetched_at")
        last_error = payload.get("last_error")
        return ModelCatalogCache(
            entries=entries,
            fetched_at=float(fetched_at)
            if isinstance(fetched_at, int | float)
            else None,
            last_error=last_error if isinstance(last_error, str) else None,
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
            payload = response.json()
        entries = reduce_model_catalog(payload)
        cache = ModelCatalogCache(entries=entries, fetched_at=time.time())
        self.write(cache)
        return cache

    def write(self, cache: ModelCatalogCache) -> None:
        """Publish the reduced cache atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        reduced: dict[str, dict[str, dict[str, str]]] = {}
        for (provider_id, model_id), (title, description) in cache.entries.items():
            reduced.setdefault(provider_id, {})[model_id] = {
                "name": title,
                "description": description,
            }
        payload = {
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


def reduce_model_catalog(payload: Any) -> dict[tuple[str, str], tuple[str, str]]:
    """Validate a models.dev payload and retain only mapped presentation data."""
    if not isinstance(payload, dict):
        raise ModelCatalogSourceError("model catalog payload is not an object")
    wanted = frozenset(MODEL_CATALOG_PROVIDER_MAPPING.values())
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for provider_id in wanted:
        provider = payload.get(provider_id)
        if provider is None:
            continue
        if not isinstance(provider, dict):
            raise ModelCatalogSourceError(
                f"model catalog provider {provider_id!r} is not an object"
            )
        models = provider.get("models")
        if not isinstance(models, dict):
            raise ModelCatalogSourceError(
                f"model catalog provider {provider_id!r} has no models object"
            )
        for model_id, model in models.items():
            if not isinstance(model_id, str) or not isinstance(model, dict):
                continue
            name = model.get("name")
            description = model.get("description")
            if not isinstance(name, str) or not name.strip():
                continue
            result[(provider_id, model_id)] = (
                name.strip(),
                description.strip() if isinstance(description, str) else "",
            )
    return result
