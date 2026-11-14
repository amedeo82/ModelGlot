from collections.abc import MutableMapping
from typing import cast

from free_claude_code.config.model_refs import split_provider_model_ref
from free_claude_code.config.model_title_overrides import (
    MODEL_TITLE_OVERRIDES,
    ModelTitleOverride,
)
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG


def test_override_keys_are_valid_provider_model_pairs() -> None:
    for provider_id, model_id in MODEL_TITLE_OVERRIDES:
        assert provider_id in PROVIDER_CATALOG
        assert model_id
        assert split_provider_model_ref(f"{provider_id}/{model_id}") == (
            provider_id,
            model_id,
        )


def test_override_titles_are_nonempty_and_trimmed() -> None:
    for override in MODEL_TITLE_OVERRIDES.values():
        assert override.title
        assert override.title == override.title.strip()
        if override.description is not None:
            assert override.description == override.description.strip()


def test_override_mapping_is_immutable() -> None:
    key = next(iter(MODEL_TITLE_OVERRIDES))
    mutable = cast(
        MutableMapping[tuple[str, str], ModelTitleOverride],
        MODEL_TITLE_OVERRIDES,
    )
    try:
        mutable[key] = mutable[key]
    except TypeError:
        return
    raise AssertionError("curated title overrides must be immutable")
