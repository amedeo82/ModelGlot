from typing import cast

import pytest

from modelglot.application.model_titles import (
    CatalogTitleMap,
    disambiguate_duplicate_titles,
    heuristic_model_title,
    lookup_model_catalog_entry,
    resolve_model_title,
)


def test_curated_override_wins_over_catalog_and_heuristic() -> None:
    catalog = {("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"): ("Catalog", "")}

    assert (
        resolve_model_title(
            "nvidia_nim",
            "nvidia/nemotron-3-ultra-550b-a55b",
            "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b",
            catalog,
        )
        == "Nemotron 3 Ultra 550B A55B"
    )


def test_catalog_title_is_selected_with_the_explicit_provider_mapping() -> None:
    catalog = {("openrouter", "vendor/model"): ("Vendor Model", "Description")}

    assert (
        resolve_model_title(
            "open_router",
            "vendor/model",
            "open_router/vendor/model",
            catalog,
        )
        == "Vendor Model"
    )


def test_catalog_lookup_exposes_the_same_title_and_normalized_description() -> None:
    catalog = {("openrouter", "vendor/model"): (" Vendor Model ", " Description ")}

    assert lookup_model_catalog_entry("open_router", "vendor/model", catalog) == (
        "Vendor Model",
        "Description",
    )
    assert (
        resolve_model_title(
            "open_router", "vendor/model", "open_router/vendor/model", catalog
        )
        == "Vendor Model"
    )


@pytest.mark.parametrize("description", ["", "   ", None, 42])
def test_catalog_lookup_discards_missing_blank_or_malformed_descriptions(
    description: object,
) -> None:
    catalog = cast(
        CatalogTitleMap,
        {("openrouter", "vendor/model"): ("Vendor Model", description)},
    )

    assert lookup_model_catalog_entry("open_router", "vendor/model", catalog) == (
        "Vendor Model",
        None,
    )


def test_catalog_lookup_returns_absent_for_missing_or_blank_titles() -> None:
    assert lookup_model_catalog_entry("open_router", "missing", {}) is None
    assert (
        lookup_model_catalog_entry(
            "open_router",
            "vendor/model",
            {("openrouter", "vendor/model"): (" ", "text")},
        )
        is None
    )


def test_catalog_entries_cannot_cross_provider_boundaries() -> None:
    catalog = {("openrouter", "shared"): ("OpenRouter Shared", "")}

    assert (
        resolve_model_title(
            "deepseek",
            "shared",
            "deepseek/shared",
            catalog,
        )
        == "Shared"
    )


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra 550B A55B"),
        ("openai/plain-model", "Plain Model"),
        ("gpt-4.1", "GPT 4.1"),
        ("model_name", "Model Name"),
        ("MiniMax-M3.1-Flash", "MiniMax M3.1 Flash"),
        ("mixedCaseModel", "MixedCaseModel"),
        ("unknown", "Unknown"),
    ],
)
def test_heuristic_title_derivation_is_deterministic(
    model_id: str, expected: str
) -> None:
    assert heuristic_model_title(model_id) == expected
    assert heuristic_model_title(model_id) == expected


def test_heuristic_keeps_a_vendor_prefix_when_it_is_the_only_segment() -> None:
    assert heuristic_model_title("nvidia") == "Nvidia"


def test_empty_model_id_falls_back_to_the_exact_reference() -> None:
    assert resolve_model_title("open_router", "", "open_router/") == "open_router/"
    assert heuristic_model_title("") == ""
    assert heuristic_model_title("---") == ""


def test_duplicate_titles_receive_a_unique_model_suffix() -> None:
    resolved = disambiguate_duplicate_titles(
        [
            ("open_router", "vendor/model", "Model"),
            ("open_router", "other/model", "Model"),
        ]
    )

    assert resolved == {("open_router", "vendor/model"): "Model (vendor/model)"}


def test_duplicate_disambiguation_is_stable_across_input_order() -> None:
    titles = [
        ("open_router", "vendor/model", "Model"),
        ("open_router", "other/model", "Model"),
    ]

    assert disambiguate_duplicate_titles(titles) == disambiguate_duplicate_titles(
        tuple(reversed(titles))
    )
