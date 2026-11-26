from free_claude_code.config.model_catalog_mapping import (
    MODEL_CATALOG_PROVIDER_MAPPING,
)
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG


def test_every_mapped_modelglot_provider_exists() -> None:
    assert set(MODEL_CATALOG_PROVIDER_MAPPING) <= set(PROVIDER_CATALOG)


def test_each_modelglot_provider_maps_to_one_models_dev_provider() -> None:
    assert all(
        provider_id and catalog_provider
        for provider_id, catalog_provider in MODEL_CATALOG_PROVIDER_MAPPING.items()
    )


def test_known_models_dev_provider_mappings_are_explicit() -> None:
    expected = {
        "nvidia_nim": "nvidia",
        "open_router": "openrouter",
        "together": "togetherai",
        "gemini": "google",
        "novita": "novita-ai",
        "fireworks": "fireworks-ai",
        "github_copilot": "github-copilot",
        "azure_openai": "azure",
        "alibaba_cloud": "alibaba",
        "opencode_zen": "opencode",
        "opencode_go": "opencode",
    }

    for provider_id, catalog_provider in expected.items():
        assert MODEL_CATALOG_PROVIDER_MAPPING[provider_id] == catalog_provider
