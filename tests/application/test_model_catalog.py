from dataclasses import replace

from free_claude_code.application.model_catalog import (
    CatalogModel,
    catalog_wire_slug_for_ref,
    read_model_catalog,
)
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.application.ports import ModelCatalogSnapshot
from free_claude_code.config.custom_providers import CustomProviderDefinition
from free_claude_code.config.model_refs import ModelFallback
from free_claude_code.config.settings import Settings


def test_custom_display_names_sort_as_labels_without_changing_model_identity():
    names = ["Team/West", "/Gateway", "Team", "z"]
    definitions = tuple(
        CustomProviderDefinition(
            provider_id=f"custom_{index:032x}",
            display_name=name,
            base_url="https://gateway.example/v1",
        )
        for index, name in enumerate(names)
    )
    settings = Settings(
        custom_providers=definitions, model=f"{definitions[0].provider_id}/Z"
    )
    infos = tuple(
        ProviderModelInfo(f"{definition.provider_id}/{model}")
        for definition in definitions
        for model in ("Z", "org/m")
    )
    snapshot = ModelCatalogSnapshot(settings, infos)
    catalog = read_model_catalog(snapshot)
    assert [model.display_name for model in catalog.models] == [
        f"{name}/{model}"
        for name in ("/Gateway", "Team", "Team/West", "z")
        for model in ("org/m", "Z")
    ]
    assert {model.provider_model_ref for model in catalog.models} == {
        info.model_id for info in infos
    }
    assert catalog.default_model_id == settings.model
    assert (
        read_model_catalog(replace(snapshot, model_infos=tuple(reversed(infos))))
        == catalog
    )


def test_catalog_sorts_components_and_preserves_exact_identity_and_default():
    settings = Settings.model_construct(
        model="open_router/Zulu",
        model_fable=None,
        model_opus=None,
        model_sonnet=None,
        model_haiku=None,
        model_fallbacks=(
            ModelFallback(model="wafer/z"),
            ModelFallback(model="deepseek/a"),
        ),
    )
    infos = (
        ProviderModelInfo("alpha-2/model"),
        ProviderModelInfo("alpha/z"),
        ProviderModelInfo("alpha/ß"),
        ProviderModelInfo("alpha/ss"),
        ProviderModelInfo("alpha/Apple"),
        ProviderModelInfo("alpha/apple"),
        ProviderModelInfo("alpha/vendor/nested"),
        ProviderModelInfo(
            "open_router/Zulu", supports_thinking=False, context_window_tokens=32000
        ),
    )
    snapshot = ModelCatalogSnapshot(settings, infos)
    catalog = read_model_catalog(snapshot)
    assert [model.provider_model_ref for model in catalog.models] == [
        "alpha/Apple",
        "alpha/apple",
        "alpha/ss",
        "alpha/ß",
        "alpha/vendor/nested",
        "alpha/z",
        "alpha-2/model",
        "deepseek/a",
        "open_router/Zulu",
        "wafer/z",
    ]
    assert (
        read_model_catalog(replace(snapshot, model_infos=tuple(reversed(infos))))
        == catalog
    )
    assert catalog.default_model_id == "claude-3-freecc-no-thinking/open_router/Zulu"
    selected = next(
        model for model in catalog.models if model.wire_slug == catalog.default_model_id
    )
    assert selected.context_window_tokens == 32000
    assert settings.model_fallbacks == (
        ModelFallback(model="wafer/z"),
        ModelFallback(model="deepseek/a"),
    )


def test_catalog_retains_configured_models_and_enriches_each_reference_once():
    settings = Settings.model_construct(
        model="open_router/shared",
        model_opus="open_router/shared",
        model_fable=None,
        model_sonnet=None,
        model_haiku="deepseek/undiscovered",
        model_fallbacks=(ModelFallback(model="open_router/shared"),),
    )
    info = ProviderModelInfo("open_router/shared", context_window_tokens=65536)
    catalog = read_model_catalog(ModelCatalogSnapshot(settings, (info,)))
    assert [model.provider_model_ref for model in catalog.models] == [
        "deepseek/undiscovered",
        "open_router/shared",
    ]
    assert catalog.models[0].supports_reasoning is None
    assert catalog.models[0].context_window_tokens is None
    assert catalog.models[1].context_window_tokens == 65536


def test_descriptive_titles_preserve_identity_and_carry_provider_description() -> None:
    ref = "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b"
    settings = Settings(model=ref)
    snapshot = ModelCatalogSnapshot(settings, (ProviderModelInfo(ref),))

    model = read_model_catalog(snapshot).models[0]

    assert model.display_name == "Nemotron 3 Ultra 550B A55B"
    assert model.description == "NVIDIA NIM"
    assert model.provider_model_ref == ref
    assert model.wire_slug == ref


def test_catalog_title_is_used_between_curated_and_heuristic_titles() -> None:
    ref = "open_router/vendor/model"
    settings = Settings(model=ref)
    snapshot = ModelCatalogSnapshot(
        settings,
        (ProviderModelInfo(ref),),
        title_catalog={("openrouter", "vendor/model"): ("Vendor Model", "Description")},
    )

    model = read_model_catalog(snapshot).models[0]

    assert model.display_name == "Vendor Model"
    assert model.description == "OpenRouter"
    assert model.model_description == "Description"
    assert model.model_description_source == "models.dev"
    assert model.provider_model_ref == ref


def test_minimax_metadata_separates_provider_attribution_from_purpose_text() -> None:
    ref = "nvidia_nim/minimaxai/minimax-m3.1-flash"
    snapshot = ModelCatalogSnapshot(
        Settings(model=ref),
        (ProviderModelInfo(ref),),
        title_catalog={
            ("nvidia", "minimaxai/minimax-m3.1-flash"): (
                "MiniMax-M3.1-Flash",
                "1M context",
            )
        },
    )

    model = read_model_catalog(snapshot).models[0]

    assert model.display_name == "MiniMax-M3.1-Flash"
    assert model.description == "NVIDIA NIM"
    assert model.model_description == "1M context"
    assert model.model_description_source == "models.dev"
    assert model.provider_model_ref == ref
    assert model.wire_slug == ref
    assert model.supports_reasoning is None
    assert model.input_modalities is None
    assert model.context_window_tokens is None
    assert model.max_output_tokens is None


def test_absent_catalog_metadata_keeps_existing_fallbacks() -> None:
    ref = "open_router/vendor/model"
    snapshot = ModelCatalogSnapshot(Settings(model=ref), ())

    model = read_model_catalog(snapshot).models[0]

    assert model.display_name == "Vendor Model"
    assert model.description == "OpenRouter"
    assert model.model_description is None
    assert model.model_description_source is None


def test_no_thinking_title_keeps_the_routing_suffix() -> None:
    ref = "open_router/vendor/model"
    settings = Settings(model=ref)
    snapshot = ModelCatalogSnapshot(
        settings,
        (ProviderModelInfo(ref, supports_thinking=False),),
    )

    model = read_model_catalog(snapshot).models[0]

    assert model.display_name == "Vendor Model (no thinking)"
    assert model.wire_slug == f"claude-3-freecc-no-thinking/{ref}"


def test_duplicate_provider_titles_are_disambiguated() -> None:
    settings = Settings(model="open_router/first/shared")
    snapshot = ModelCatalogSnapshot(
        settings,
        (
            ProviderModelInfo("open_router/first/shared"),
            ProviderModelInfo("open_router/second/shared"),
        ),
        title_catalog={
            ("openrouter", "first/shared"): ("Shared", ""),
            ("openrouter", "second/shared"): ("Shared", ""),
        },
    )

    models = read_model_catalog(snapshot).models

    assert [model.display_name for model in models] == [
        "Shared",
        "Shared (second/shared)",
    ]


def _client_model(wire_slug: str, provider_model_ref: str) -> CatalogModel:
    return CatalogModel(
        wire_slug=wire_slug,
        provider_model_ref=provider_model_ref,
        display_name=provider_model_ref,
        supports_reasoning=wire_slug == provider_model_ref,
    )


def test_catalog_wire_slug_prefers_the_advertised_no_thinking_slug() -> None:
    models = (
        _client_model(
            "claude-3-freecc-no-thinking/open_router/vendor/chat-model",
            "open_router/vendor/chat-model",
        ),
    )

    assert (
        catalog_wire_slug_for_ref(models, "open_router/vendor/chat-model")
        == "claude-3-freecc-no-thinking/open_router/vendor/chat-model"
    )


def test_catalog_wire_slug_keeps_a_directly_advertised_ref() -> None:
    models = (
        _client_model("open_router/vendor/chat-model", "open_router/vendor/chat-model"),
    )

    assert (
        catalog_wire_slug_for_ref(models, "open_router/vendor/chat-model")
        == "open_router/vendor/chat-model"
    )


def test_catalog_wire_slug_falls_back_when_the_catalog_omits_the_ref() -> None:
    models = (_client_model("open_router/vendor/other", "open_router/vendor/other"),)

    assert (
        catalog_wire_slug_for_ref(models, "open_router/vendor/chat-model")
        == "open_router/vendor/chat-model"
    )
    assert catalog_wire_slug_for_ref((), "open_router/vendor/chat-model") == (
        "open_router/vendor/chat-model"
    )


def test_catalog_wire_slug_passes_through_an_unset_model() -> None:
    assert catalog_wire_slug_for_ref((), None) is None
    assert catalog_wire_slug_for_ref((), "") == ""
