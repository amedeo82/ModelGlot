import asyncio
import json
from pathlib import Path

import pytest

from free_claude_code.config.model_catalog_metadata import ModelCatalogMetadata
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonValue
from free_claude_code.providers.model_catalog_source import (
    ModelCatalogCache,
    ModelCatalogSource,
    ModelCatalogSourceError,
    reduce_model_catalog,
    reduce_model_catalog_metadata,
)
from tests.wire_payload import decode_object, object_payload


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

        def json(self) -> JsonValue:
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

    def client_factory(**_kwargs: object) -> Client:
        return Client()

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_source.httpx.AsyncClient",
        client_factory,
    )
    path = tmp_path / "catalog.json"

    cache = await ModelCatalogSource(path).refresh(Settings())

    assert cache.entries == {
        ("deepseek", "deepseek-chat"): ("DeepSeek Chat", "Description")
    }
    assert cache.metadata == {}
    assert decode_object(path.read_text(encoding="utf-8"))["entries"] == {
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


def test_provider_scoped_minimax_and_gemma_facts_are_retained_exactly() -> None:
    payload = {
        "nvidia": {
            "models": {
                "minimaxai/minimax-m3.1-flash": {
                    "name": "MiniMax-M3.1-Flash",
                    "description": "1M context",
                    "canonical_model_id": "minimax/MiniMax-M3.1-Flash",
                    "reasoning": True,
                    "tool_call": True,
                    "structured_output": True,
                    "modalities": {
                        "input": ["text", "image", "video"],
                        "output": ["text"],
                    },
                    "limit": {"context": 262144, "input": 262144, "output": 262144},
                    "release_date": "2026-10-19",
                    "last_updated": "2026-11-01",
                    "open_weights": True,
                    "cost": {"input": 0},
                    "benchmarks": {"ignored": True},
                },
                "google/gemma-4-31b-it": {
                    "name": "Gemma 4 31B IT",
                    "canonical_model_id": "google/gemma-4-31b-it",
                    "reasoning": True,
                    "tool_call": True,
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "limit": {"context": 256000, "output": 16384},
                },
            }
        }
    }

    metadata = reduce_model_catalog_metadata(payload)
    minimax = metadata[("nvidia", "minimaxai/minimax-m3.1-flash")]
    gemma = metadata[("nvidia", "google/gemma-4-31b-it")]

    assert (minimax.context_limit, minimax.output_limit) == (262144, 262144)
    assert minimax.reasoning is True
    assert minimax.tool_call is True
    assert minimax.structured_output is True
    assert minimax.input_modalities == ("text", "image", "video")
    assert minimax.lab_id == "minimax"
    assert minimax.lab_label == "MiniMax"
    assert (gemma.context_limit, gemma.output_limit) == (256000, 16384)
    assert gemma.structured_output is None
    assert gemma.input_modalities == ("text", "image")
    assert reduce_model_catalog(payload)[
        ("nvidia", "minimaxai/minimax-m3.1-flash")
    ] == ("MiniMax-M3.1-Flash", "1M context")


def test_malformed_metadata_is_rejected_without_losing_legacy_title() -> None:
    payload = {
        "nvidia": {
            "models": {
                "vendor/model": {
                    "name": "Vendor Model",
                    "description": "Editorial text",
                    "reasoning": "true",
                    "limit": {"context": "262144"},
                }
            }
        }
    }

    assert reduce_model_catalog_metadata(payload) == {}
    assert reduce_model_catalog(payload) == {
        ("nvidia", "vendor/model"): ("Vendor Model", "Editorial text")
    }


def test_catalog_metadata_round_trip_preserves_facts_and_freshness(
    tmp_path: Path,
) -> None:
    source = ModelCatalogSource(tmp_path / "catalog.json")
    key = ("nvidia", "minimaxai/minimax-m3.1-flash")
    metadata = ModelCatalogMetadata(
        canonical_model_id="minimax/MiniMax-M3.1-Flash",
        reasoning=True,
        tool_call=True,
        structured_output=True,
        input_modalities=("text", "video"),
        output_modalities=("text",),
        context_limit=262144,
        output_limit=262144,
        last_updated="2026-11-01",
        open_weights=True,
        fetched_at=1000.0,
    )
    source.write(
        ModelCatalogCache(
            entries={key: ("MiniMax-M3.1-Flash", "1M context")},
            metadata={key: metadata},
            fetched_at=1000.0,
        )
    )

    loaded = source.load()
    assert loaded.entries[key] == ("MiniMax-M3.1-Flash", "1M context")
    assert loaded.metadata == {key: metadata}
    payload = decode_object((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    entries = object_payload(payload["entries"])
    nvidia = object_payload(entries["nvidia"])
    model = object_payload(nvidia[key[1]])
    metadata = object_payload(model["metadata"])
    assert "cost" not in metadata


def test_source_none_does_not_make_a_network_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("disabled catalog source must not make a network request")

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_source.httpx.AsyncClient", forbidden
    )
    source = ModelCatalogSource(Path("unused.json"))

    result = asyncio.run(source.refresh(Settings(model_catalog_source="none")))

    assert result.entries == {}
