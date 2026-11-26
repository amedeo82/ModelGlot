import pytest
from pydantic import ValidationError

from free_claude_code.config.loader import compose_settings_snapshot
from free_claude_code.config.settings import Settings


def test_model_catalog_settings_have_safe_defaults() -> None:
    settings = Settings()

    assert settings.model_catalog_source == "models.dev"
    assert settings.model_catalog_url == "https://models.dev/api.json"


def test_model_catalog_settings_parse_from_managed_and_process_sources() -> None:
    managed = compose_settings_snapshot(
        {
            "MODELGLOT_MODEL_CATALOG_SOURCE": "none",
            "MODELGLOT_MODEL_CATALOG_URL": "https://catalog.example/models.json",
        },
        {},
    )
    process = compose_settings_snapshot(
        {},
        {
            "MODELGLOT_MODEL_CATALOG_SOURCE": "none",
            "MODELGLOT_MODEL_CATALOG_URL": "https://catalog.example/models.json",
        },
    )

    for snapshot in (managed, process):
        assert snapshot.settings.model_catalog_source == "none"
        assert (
            snapshot.settings.model_catalog_url == "https://catalog.example/models.json"
        )


def test_invalid_model_catalog_source_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"MODELGLOT_MODEL_CATALOG_SOURCE": "invalid"})


def test_blank_model_catalog_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"MODELGLOT_MODEL_CATALOG_URL": " "})
