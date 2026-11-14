from free_claude_code.application.model_catalog import read_model_catalog
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.application.ports import ModelCatalogSnapshot
from free_claude_code.application.routing import ModelRouter
from free_claude_code.config.settings import Settings


def test_titles_never_change_routing_candidates_or_advertised_identity() -> None:
    settings = Settings(model="open_router/vendor/model")
    info = ProviderModelInfo("open_router/vendor/model")
    snapshots = (
        ModelCatalogSnapshot(settings, (info,)),
        ModelCatalogSnapshot(
            settings,
            (info,),
            title_catalog={
                ("openrouter", "vendor/model"): ("Descriptive Model", "Description")
            },
        ),
        ModelCatalogSnapshot(
            settings,
            (info,),
            title_catalog={
                ("openrouter", "vendor/model"): ("Stale Model", "Description")
            },
        ),
    )
    catalogs = tuple(read_model_catalog(snapshot) for snapshot in snapshots)
    identities = tuple(
        tuple((model.provider_model_ref, model.wire_slug) for model in catalog.models)
        for catalog in catalogs
    )
    routes = tuple(
        (
            route.primary.provider_model_ref,
            *(fallback.target.provider_model_ref for fallback in route.fallbacks),
        )
        for route in (
            ModelRouter(settings).resolve("claude-opus-test") for _ in catalogs
        )
    )

    assert identities[0] == identities[1] == identities[2]
    assert routes[0] == routes[1] == routes[2]
    assert catalogs[1].models[0].display_name == "Descriptive Model"
    assert catalogs[2].models[0].display_name == "Stale Model"
