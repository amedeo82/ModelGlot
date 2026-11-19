import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from free_claude_code.config.settings import Settings
from free_claude_code.providers.model_catalog_source import (
    ModelCatalogCache,
    ModelCatalogSource,
    ModelCatalogSourceError,
    reduce_model_catalog,
)


def test_valid_payload_is_reduced_to_mapped_provider_models() -> None:
    payload = {
        "nvidia": {
            "models": {
                "nvidia/nemotron-3-ultra-550b-a55b": {
                    "name": "Nemotron 3 Ultra 550B A55B",
                    "description": "Reasoning model",
                }
            }
        },
        "openrouter": {
            "models": {"vendor/model": {"name": "Vendor Model", "description": ""}}
        },
    }

    assert reduce_model_catalog(payload) == {
        ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"): (
            "Nemotron 3 Ultra 550B A55B",
            "Reasoning model",
        ),
        ("openrouter", "vendor/model"): ("Vendor Model", ""),
    }


def test_unrelated_providers_are_dropped() -> None:
    payload = {
        "unrelated": {"models": {"model": {"name": "Unrelated"}}},
        "deepseek": {"models": {"deepseek-chat": {"name": "DeepSeek Chat"}}},
    }

    assert reduce_model_catalog(payload) == {
        ("deepseek", "deepseek-chat"): ("DeepSeek Chat", "")
    }


def test_malformed_mapped_provider_raises_a_typed_error() -> None:
    with pytest.raises(ModelCatalogSourceError):
        reduce_model_catalog({"deepseek": {"models": "invalid"}})


def test_non_object_payload_raises_a_typed_error() -> None:
    with pytest.raises(ModelCatalogSourceError):
        reduce_model_catalog([])


@pytest.mark.asyncio
async def test_refresh_fetches_reduces_and_publishes_the_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "deepseek": {
                    "models": {
                        "deepseek-chat": {
                            "name": "DeepSeek Chat",
                            "description": "Description",
                        }
                    }
                },
                "unrelated": {"models": {"model": {"name": "Unrelated"}}},
            }

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, _url: str) -> Response:
            return Response()

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_source.httpx.AsyncClient",
        lambda **_kwargs: Client(),
    )
    path = tmp_path / "catalog.json"

    cache = await ModelCatalogSource(path).refresh(Settings())

    assert cache.entries == {
        ("deepseek", "deepseek-chat"): ("DeepSeek Chat", "Description")
    }
    assert json.loads(path.read_text(encoding="utf-8"))["entries"] == {
        "deepseek": {
            "deepseek-chat": {
                "name": "DeepSeek Chat",
                "description": "Description",
            }
        }
    }


def test_cache_round_trip_preserves_name_and_description(tmp_path: Path) -> None:
    source = ModelCatalogSource(tmp_path / "catalog.json")
    source.write(
        ModelCatalogCache(
            entries={("deepseek", "deepseek-chat"): ("DeepSeek Chat", "Description")}
        )
    )

    assert source.load().entries == {
        ("deepseek", "deepseek-chat"): ("DeepSeek Chat", "Description")
    }


def test_legacy_title_only_cache_entries_remain_readable(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps({"entries": {"deepseek": {"deepseek-chat": "DeepSeek Chat"}}}),
        encoding="utf-8",
    )

    assert ModelCatalogSource(path).load().entries == {
        ("deepseek", "deepseek-chat"): ("DeepSeek Chat", "")
    }


def test_source_none_does_not_make_a_network_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("disabled catalog source must not make a network request")

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_source.httpx.AsyncClient", forbidden
    )
    source = ModelCatalogSource(Path("unused.json"))

    result = asyncio.run(source.refresh(Settings(model_catalog_source="none")))

    assert result.entries == {}
