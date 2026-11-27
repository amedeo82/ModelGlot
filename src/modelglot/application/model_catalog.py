"""Application model inventory and presentation order, independent of clients."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from modelglot.config.constants import DEFAULT_MODEL_CONTEXT_TOKENS
from modelglot.config.model_catalog_mapping import (
    MODEL_CATALOG_PROVIDER_MAPPING,
)
from modelglot.config.model_catalog_metadata import ModelCatalogMetadata
from modelglot.config.model_refs import (
    configured_chat_model_refs,
    split_provider_model_ref,
)
from modelglot.config.model_title_overrides import MODEL_TITLE_OVERRIDES
from modelglot.config.provider_catalog import PROVIDER_CATALOG
from modelglot.core.gateway_model_ids import no_thinking_gateway_model_id
from modelglot.core.model_capabilities import ModelInputModality

from .model_metadata import ProviderModelInfo
from .model_titles import (
    CatalogTitleMap,
    disambiguate_duplicate_titles,
    lookup_model_catalog_entry,
    resolve_model_title,
)
from .ports import ModelCatalogMetadataPort, ModelTitleCatalogPort

if TYPE_CHECKING:
    from modelglot.config.settings import Settings

    from .ports import ModelCatalogPort


@dataclass(frozen=True, slots=True)
class CatalogModel:
    """One exact ModelGlot model identity and its reported capabilities."""

    wire_slug: str
    provider_model_ref: str
    display_name: str
    description: str | None = field(default=None, kw_only=True)
    supports_reasoning: bool | None
    input_modalities: frozenset[ModelInputModality] | None = None
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    model_description: str | None = field(default=None, kw_only=True)
    model_description_source: str | None = field(default=None, kw_only=True)
    catalog_metadata: ModelCatalogMetadata | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """An ordered inventory with selection independent of list position."""

    models: tuple[CatalogModel, ...]
    default_model_id: str


def context_window_for_client(model: CatalogModel) -> int:
    """Resolve client capacity without changing reported provider metadata."""
    context = model.context_window_tokens
    return (
        context if context is not None and context > 0 else DEFAULT_MODEL_CONTEXT_TOKENS
    )


def model_order_key(provider_model_ref: str) -> tuple[str, str, str, str]:
    provider, model = split_provider_model_ref(provider_model_ref)
    return provider.casefold(), model.casefold(), provider, model


def read_model_catalog(
    runtime: ModelCatalogPort, settings: Settings | None = None
) -> ModelCatalog:
    """Merge configured and cached models without discovery or provider leases."""
    settings = settings if settings is not None else runtime.current_settings()
    title_catalog = (
        runtime.model_title_catalog()
        if isinstance(runtime, ModelTitleCatalogPort)
        else {}
    )
    catalog_metadata = (
        runtime.model_catalog_metadata()
        if isinstance(runtime, ModelCatalogMetadataPort)
        else {}
    )
    models: dict[str, CatalogModel] = {}
    for ref in configured_chat_model_refs(settings):
        models[ref.model_ref] = _catalog_model(
            ref.model_ref,
            runtime.cached_model_info(ref.provider_id, ref.model_id),
            title_catalog,
            catalog_metadata,
        )
    for info in runtime.cached_prefixed_model_infos():
        if info.model_id not in models:
            models[info.model_id] = _catalog_model(
                info.model_id, info, title_catalog, catalog_metadata
            )
    for ref, model in tuple(models.items()):
        provider_id, model_id = split_provider_model_ref(ref)
        definition = settings.custom_provider(provider_id)
        if definition is None:
            continue
        override = MODEL_TITLE_OVERRIDES.get((provider_id, model_id))
        title = (
            override.title
            if override is not None
            else f"{definition.display_name}/{model_id}"
        )
        models[ref] = replace(
            model,
            display_name=title
            + (" (no thinking)" if model.supports_reasoning is False else ""),
            description=definition.display_name,
        )
    duplicates = disambiguate_duplicate_titles(
        [
            (
                *split_provider_model_ref(model.provider_model_ref),
                model.display_name.removesuffix(" (no thinking)"),
            )
            for model in models.values()
        ]
    )
    for ref, model in tuple(models.items()):
        provider_id, model_id = split_provider_model_ref(ref)
        duplicate_title = duplicates.get((provider_id, model_id))
        if duplicate_title is not None:
            models[ref] = replace(
                model,
                display_name=duplicate_title
                + (" (no thinking)" if model.supports_reasoning is False else ""),
            )

    def order(model: CatalogModel):
        provider_id, model_id = split_provider_model_ref(model.provider_model_ref)
        definition = settings.custom_provider(provider_id)
        name = definition.display_name if definition else provider_id
        return (
            name.casefold(),
            model_id.casefold(),
            name,
            model_id,
            model.provider_model_ref,
        )

    return ModelCatalog(
        models=tuple(
            sorted(
                models.values(),
                key=order,
            )
        ),
        default_model_id=models[settings.model].wire_slug,
    )


def _catalog_model(
    ref: str,
    info: ProviderModelInfo | None,
    title_catalog: CatalogTitleMap,
    metadata_catalog: Mapping[tuple[str, str], ModelCatalogMetadata],
) -> CatalogModel:
    info = info if info is not None else ProviderModelInfo(ref)
    provider_id, model_id = split_provider_model_ref(ref)
    no_thinking = info.supports_thinking is False
    title = resolve_model_title(provider_id, model_id, ref, title_catalog)
    metadata = lookup_model_catalog_entry(provider_id, model_id, title_catalog)
    model_description = metadata[1] if metadata is not None else None
    descriptor = PROVIDER_CATALOG.get(provider_id)
    catalog_provider = MODEL_CATALOG_PROVIDER_MAPPING.get(provider_id)
    catalog_metadata = (
        metadata_catalog.get((catalog_provider, model_id))
        if catalog_provider is not None
        else None
    )
    return CatalogModel(
        wire_slug=no_thinking_gateway_model_id(ref) if no_thinking else ref,
        provider_model_ref=ref,
        display_name=f"{title} (no thinking)" if no_thinking else title,
        supports_reasoning=info.supports_thinking,
        description=descriptor.display_name if descriptor is not None else None,
        input_modalities=info.input_modalities,
        context_window_tokens=info.context_window_tokens,
        max_output_tokens=info.max_output_tokens,
        model_description=model_description,
        model_description_source="models.dev" if model_description else None,
        catalog_metadata=catalog_metadata,
    )


def catalog_wire_slug_for_ref(
    models: Sequence[CatalogModel], provider_model_ref: str | None
) -> str | None:
    """Resolve an explicit selection, retaining a missing or unset reference."""
    if not provider_model_ref:
        return provider_model_ref
    for model in models:
        if model.provider_model_ref == provider_model_ref:
            return model.wire_slug
    return provider_model_ref
