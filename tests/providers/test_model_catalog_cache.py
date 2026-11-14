import json
import time
from pathlib import Path

import pytest

from free_claude_code.providers.model_catalog_source import (
    MODEL_CATALOG_CACHE_TTL_SECONDS,
    ModelCatalogCache,
    ModelCatalogSource,
)


def test_fresh_cache_is_read_without_network_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("cache reads must not make a network request")

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_source.httpx.AsyncClient",
        forbidden,
    )
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "entries": {"deepseek": {"deepseek-chat": {"name": "DeepSeek Chat"}}},
                "fetched_at": time.time(),
            }
        ),
        encoding="utf-8",
    )

    cache = ModelCatalogSource(path).load()

    assert cache.entries == {("deepseek", "deepseek-chat"): ("DeepSeek Chat", "")}
    assert cache.stale is False


def test_expired_cache_is_still_readable_and_marked_stale(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "entries": {"deepseek": {"deepseek-chat": {"name": "DeepSeek Chat"}}},
                "fetched_at": time.time() - MODEL_CATALOG_CACHE_TTL_SECONDS,
            }
        ),
        encoding="utf-8",
    )

    cache = ModelCatalogSource(path).load()

    assert cache.entries == {("deepseek", "deepseek-chat"): ("DeepSeek Chat", "")}
    assert cache.stale is True


def test_invalid_cache_is_ignored_without_partial_data(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text("not json", encoding="utf-8")

    cache = ModelCatalogSource(path).load()

    assert cache.entries == {}
    assert cache.fetched_at is None


def test_cache_file_contains_only_the_reduced_map(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    source = ModelCatalogSource(path)

    source.write(
        ModelCatalogCache(
            entries={("deepseek", "deepseek-chat"): ("DeepSeek Chat", "Description")},
            fetched_at=123.0,
        )
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "entries": {
            "deepseek": {
                "deepseek-chat": {
                    "name": "DeepSeek Chat",
                    "description": "Description",
                }
            }
        },
        "fetched_at": 123.0,
        "last_error": None,
    }


def test_failed_atomic_write_leaves_the_previous_cache_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "catalog.json"
    path.write_text("previous", encoding="utf-8")
    source = ModelCatalogSource(path)

    def fail_replace(_source: str, _destination: str) -> None:
        raise PermissionError("destination is locked")

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_source.os.replace",
        fail_replace,
    )

    with pytest.raises(PermissionError):
        source.write(ModelCatalogCache(entries={("deepseek", "chat"): ("Chat", "")}))

    assert path.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.glob(".catalog.json.*.tmp")) == []
