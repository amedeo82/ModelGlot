"""Local admin UI routes and APIs."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter, time

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

from free_claude_code.application.connected_accounts import (
    ConnectedAccountLoginMode,
)
from free_claude_code.application.errors import ApplicationError
from free_claude_code.application.model_catalog import CatalogModel, read_model_catalog
from free_claude_code.application.model_metadata import ProviderModelRefreshResult
from free_claude_code.application.ports import ModelCatalogLogoPort
from free_claude_code.application.usage_events import UsageFilters, UsageGroupBy
from free_claude_code.config.admin.custom_providers import CustomProviderMutation
from free_claude_code.config.admin.manifest import FIELD_BY_KEY
from free_claude_code.config.errors import ConfigConflictError
from free_claude_code.config.model_catalog_mapping import (
    MODEL_CATALOG_CACHE_TTL_SECONDS,
    MODEL_CATALOG_PROVIDER_MAPPING,
)
from free_claude_code.config.model_refs import split_provider_model_ref
from free_claude_code.config.provider_catalog import (
    PROVIDER_CATALOG,
    ProviderAuthKind,
)
from free_claude_code.core.json_types import JsonObject, JsonValue
from free_claude_code.core.model_capabilities import ModelInputModality
from free_claude_code.core.version import package_version

from .admin_security import require_loopback_admin
from .dependencies import get_services
from .ports import ApiServices
from .usage_csv import usage_csv

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "admin_static"
PACKAGE_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_ADMIN_ASSET_VERSION_PLACEHOLDER = "__FCC_VERSION__"
_ADMIN_ASSET_MEDIA_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}
_ADMIN_ASSET_FILENAMES = frozenset(
    {
        "admin.css",
        "admin.js",
        "form_controls.js",
        "app-icon.svg",
        "code_sessions.css",
        "code_sessions.js",
        "session_layout.css",
        "session_ui.js",
        "token_optimization.css",
        "token_optimization.js",
        "model_picker_details.js",
        "model_combobox.js",
        "api_key_editor.js",
        *(
            f"providers/{provider.logo_filename}"
            for provider in PROVIDER_CATALOG.values()
        ),
    }
)
LOCAL_PROVIDER_PATHS = {
    "lmstudio": "/models",
    "llamacpp": "/models",
    "ollama": "/api/tags",
}
_LOCAL_PROVIDER_CHECK_FAILURE_MESSAGE = (
    "Could not connect. Verify the URL and that the local provider is running."
)


class AdminConfigPayload(BaseModel):
    """Partial config update submitted by the admin UI."""

    values: JsonObject = Field(default_factory=dict, repr=False)
    custom_provider: CustomProviderMutation | None = None


class ConnectedAccountLoginPayload(BaseModel):
    """Interactive connected-account login selection."""

    mode: ConnectedAccountLoginMode | None = None


def _asset_path(filename: str) -> Path:
    asset_dir = PACKAGE_ASSETS_DIR if filename == "app-icon.svg" else STATIC_DIR
    path = asset_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Admin asset not found")
    return path


def _asset_response(filename: str) -> FileResponse:
    path = _asset_path(filename)
    return FileResponse(path, media_type=_ADMIN_ASSET_MEDIA_TYPES[path.suffix])


def admin_page_response() -> HTMLResponse:
    template = _asset_path("index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        template.replace(_ADMIN_ASSET_VERSION_PLACEHOLDER, package_version())
    )


@router.get("/admin", include_in_schema=False)
@router.get("/admin/model_config", include_in_schema=False)
@router.get("/admin/messaging", include_in_schema=False)
@router.get("/admin/integrations", include_in_schema=False)
@router.get("/admin/token_optimization", include_in_schema=False)
def admin_page(request: Request):
    require_loopback_admin(request)
    return admin_page_response()


@router.get("/admin/assets/{version}/{filename:path}", include_in_schema=False)
async def admin_asset(version: str, filename: str, request: Request):
    require_loopback_admin(request)
    if version != package_version() or filename not in _ADMIN_ASSET_FILENAMES:
        raise HTTPException(status_code=404, detail="Admin asset not found")
    return _asset_response(filename)


@router.get("/admin/catalog-logos/{kind}/{logo_id}.svg", include_in_schema=False)
def admin_catalog_logo(
    kind: str,
    logo_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    store = services.model_catalog_logos
    path = store.path_for(kind, logo_id) if store is not None else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Catalog logo not found")
    return FileResponse(
        path,
        media_type="image/svg+xml",
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'none'; object-src 'none'; "
                "style-src 'unsafe-inline'; base-uri 'none'; sandbox"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/admin/api/config")
async def get_admin_config(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await services.admin.admin_config()


@router.post("/admin/api/config/apply")
async def apply_admin_config(
    payload: AdminConfigPayload,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    try:
        if payload.custom_provider is not None:
            return await services.admin.apply_admin_config(
                _filtered_values(payload.values), payload.custom_provider
            )
        return await services.admin.apply_admin_config(_filtered_values(payload.values))
    except ConfigConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/admin/api/status")
async def admin_status(
    request: Request,
    response: Response,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    # A local Admin page may reconnect after Apply changes the listening port.
    # The existing security check admits only loopback callers and origins.
    if origin := request.headers.get("origin"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return await services.admin.admin_status()


@router.get("/admin/api/token-optimization")
async def admin_token_optimization(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    try:
        return await services.admin.token_optimization()
    except Exception as exc:
        logger.warning(
            "Token optimization collection failed: exc_type={}", type(exc).__name__
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Token optimization report is unavailable."},
        )


def _usage_filters(request: Request) -> UsageFilters:
    params = request.query_params
    end = _rfc3339(params.get("to")) if params.get("to") else datetime.now(UTC)
    start = (
        _rfc3339(params.get("from")) if params.get("from") else end - timedelta(days=30)
    )
    return UsageFilters(
        start=start,
        end=end,
        group_by=UsageGroupBy(params.get("group_by", "model")),
        provider_id=params.get("provider_id") or None,
        gateway_model=params.get("gateway_model") or None,
        provider_model=params.get("provider_model") or None,
    )


def _rfc3339(value: str | None) -> datetime:
    if not value:
        raise ValueError("timestamp is required")
    return datetime.fromisoformat(
        value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
    )


@router.get("/admin/api/usage")
async def admin_usage(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    try:
        filters = _usage_filters(request)
    except TypeError, ValueError:
        raise HTTPException(status_code=400, detail="Invalid usage filters.") from None
    try:
        return await services.admin.usage(filters)
    except Exception as exc:
        logger.warning("Usage query failed: exc_type={}", type(exc).__name__)
        return JSONResponse(
            status_code=500, content={"detail": "Usage report is unavailable."}
        )


@router.get("/admin/api/usage/export")
async def admin_usage_export(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    try:
        filters = _usage_filters(request)
    except TypeError, ValueError:
        raise HTTPException(status_code=400, detail="Invalid usage filters.") from None
    try:
        payload = await services.admin.usage(filters)
        content = usage_csv(payload)
    except Exception as exc:
        logger.warning("Usage export failed: exc_type={}", type(exc).__name__)
        return JSONResponse(
            status_code=500, content={"detail": "Usage export is unavailable."}
        )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="fcc-usage.csv"'},
    )


@router.get("/admin/api/providers/{provider_id}/local-status")
async def local_provider_status(
    provider_id: str, request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    if provider_id not in LOCAL_PROVIDER_PATHS:
        raise HTTPException(status_code=404, detail="Local provider not found")
    values = {
        key: entry.value or ""
        for key, entry in (await services.admin.admin_values()).items()
    }
    return await _check_local_provider(
        provider_id,
        _local_provider_url(provider_id, values),
        LOCAL_PROVIDER_PATHS[provider_id],
    )


@router.post("/admin/api/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await services.admin.test_provider(provider_id)


@router.get("/admin/api/providers/{provider_id}/auth")
async def connected_account_status(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    status = await services.admin.connected_account_status(provider_id)
    return _no_store(status.as_dict())


@router.post("/admin/api/providers/{provider_id}/auth/login")
async def start_connected_account_login(
    provider_id: str,
    payload: ConnectedAccountLoginPayload,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    account = await services.admin.connected_account_status(provider_id)
    mode = payload.mode or account.default_login_mode
    if mode not in account.supported_login_modes:
        raise HTTPException(
            status_code=422,
            detail="Login mode is not supported by this provider.",
        )
    try:
        status = await services.admin.start_connected_account_login(provider_id, mode)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(f"Could not start connected-account login ({type(exc).__name__})."),
        ) from exc
    return _no_store(status.as_dict())


@router.post("/admin/api/providers/{provider_id}/auth/cancel")
async def cancel_connected_account_login(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    status = await services.admin.cancel_connected_account_login(provider_id)
    return _no_store(status.as_dict())


@router.delete("/admin/api/providers/{provider_id}/auth")
async def disconnect_connected_account(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    status = await services.admin.disconnect_connected_account(provider_id)
    return _no_store(status.as_dict())


@router.get("/admin/api/models")
async def models(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return _model_options(services)


@router.get("/admin/api/integrations/claude-onboarding")
async def claude_onboarding_status(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.claude_onboarding_status)


@router.post("/admin/api/integrations/claude-onboarding/complete")
async def complete_claude_onboarding(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.complete_claude_onboarding)


@router.get("/admin/api/integrations/claude-vscode")
async def claude_vscode_status(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.claude_vscode_status)


@router.get("/admin/api/integrations/vscode-chat")
async def vscode_chat_status(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.vscode_chat_status)


@router.post("/admin/api/integrations/vscode-chat/connect")
async def connect_vscode_chat(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.connect_vscode_chat)


@router.post("/admin/api/integrations/vscode-chat/disconnect")
async def disconnect_vscode_chat(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.disconnect_vscode_chat)


@router.post("/admin/api/integrations/vscode-chat/refresh")
async def refresh_vscode_chat(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.refresh_vscode_chat)


@router.post("/admin/api/integrations/claude-vscode/connect")
async def connect_claude_vscode(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.connect_claude_vscode)


@router.post("/admin/api/integrations/claude-vscode/refresh")
async def refresh_claude_vscode(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.refresh_claude_vscode)


@router.post("/admin/api/integrations/claude-vscode/disconnect")
async def disconnect_claude_vscode(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.disconnect_claude_vscode)


@router.get("/admin/api/integrations/dsh-desktop")
async def dsh_desktop_status(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.dsh_desktop_status)


@router.post("/admin/api/integrations/dsh-desktop/connect")
async def connect_dsh_desktop(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.connect_dsh_desktop)


@router.post("/admin/api/integrations/dsh-desktop/disconnect")
async def disconnect_dsh_desktop(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.disconnect_dsh_desktop)


@router.post("/admin/api/integrations/dsh-desktop/refresh")
async def refresh_dsh_desktop(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.refresh_dsh_desktop)


@router.get("/admin/api/integrations/claude-desktop")
async def claude_desktop_status(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.claude_desktop_status)


@router.post("/admin/api/integrations/claude-desktop/connect")
async def connect_claude_desktop(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.connect_claude_desktop)


@router.post("/admin/api/integrations/claude-desktop/disconnect")
async def disconnect_claude_desktop(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.disconnect_claude_desktop)


@router.post("/admin/api/integrations/claude-desktop/refresh")
async def refresh_claude_desktop(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.refresh_claude_desktop)


@router.get("/admin/api/integrations/jetbrains-acp")
async def jetbrains_acp_status(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.jetbrains_acp_status)


@router.post("/admin/api/integrations/jetbrains-acp/connect")
async def connect_jetbrains_acp(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.connect_jetbrains_acp)


@router.post("/admin/api/integrations/jetbrains-acp/disconnect")
async def disconnect_jetbrains_acp(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.disconnect_jetbrains_acp)


@router.post("/admin/api/integrations/jetbrains-acp/refresh")
async def refresh_jetbrains_acp(
    request: Request, services: ApiServices = Depends(get_services)
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.refresh_jetbrains_acp)


@router.get("/admin/api/integrations/codex")
async def codex_integration_status(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.codex_integration_status)


@router.post("/admin/api/integrations/codex/connect")
async def connect_codex(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.connect_codex)


@router.post("/admin/api/integrations/codex/refresh")
async def refresh_codex_integration(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.refresh_codex_integration)


@router.post("/admin/api/integrations/codex/disconnect")
async def disconnect_codex(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await _integration_response(services.admin.disconnect_codex)


async def _integration_response(
    operation: Callable[[], Awaitable[JsonObject]],
) -> JSONResponse:
    try:
        return _no_store(await operation())
    except ApplicationError as exc:
        return JSONResponse(
            {"detail": exc.message},
            status_code=exc.status_code,
            headers={"Cache-Control": "no-store"},
        )


@router.post("/admin/api/models/refresh")
async def refresh_models(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    result = await services.admin.refresh_models()
    return _model_options(services, refresh_result=result)


def _model_options(
    services: ApiServices,
    *,
    refresh_result: ProviderModelRefreshResult | None = None,
) -> JsonObject:
    catalog = read_model_catalog(services.requests)
    failed_provider_ids = (
        refresh_result.failed_provider_ids if refresh_result is not None else ()
    )
    return {
        "models": [model.provider_model_ref for model in catalog.models],
        "model_labels": {
            model.provider_model_ref: model.display_name for model in catalog.models
        },
        "model_details": {
            model.provider_model_ref: _admin_model_details(
                model, services.model_catalog_logos
            )
            for model in catalog.models
        },
        "failed_providers": list(failed_provider_ids),
    }


def _admin_model_details(
    model: CatalogModel, logo_store: ModelCatalogLogoPort | None = None
) -> JsonObject:
    provider_id, _ = split_provider_model_ref(model.provider_model_ref)
    modalities = (
        [
            modality.value
            for modality in ModelInputModality
            if modality in model.input_modalities
        ]
        if model.input_modalities is not None
        else []
    )
    context = model.context_window_tokens
    output = model.max_output_tokens
    details: JsonObject = {
        "display_name": model.display_name,
        "provider_id": provider_id,
        "provider_label": model.description,
        "description": model.model_description,
        "description_source": model.model_description_source,
        "supports_reasoning": model.supports_reasoning,
        "input_modalities": modalities or None,
        "context_window_tokens": context
        if context is not None and context > 0
        else None,
        "max_output_tokens": output if output is not None and output > 0 else None,
    }
    metadata = model.catalog_metadata
    source_provider_id = MODEL_CATALOG_PROVIDER_MAPPING.get(provider_id)
    if metadata is not None and source_provider_id is not None:
        lab_id = metadata.lab_id
        fetched_at = metadata.fetched_at
        details["catalog"] = {
            "source": "models.dev",
            "source_provider_id": source_provider_id,
            "canonical_model_id": metadata.canonical_model_id,
            "lab": {
                "id": lab_id,
                "label": metadata.lab_label,
                "logo_url": logo_store.url_for("labs", lab_id)
                if logo_store is not None
                else None,
            }
            if lab_id is not None
            else None,
            "provider_logo_url": _admin_provider_logo_url(provider_id),
            "fetched_at": fetched_at,
            "stale": fetched_at is None
            or time() - fetched_at >= MODEL_CATALOG_CACHE_TTL_SECONDS,
            "last_updated": metadata.last_updated,
            "reasoning": metadata.reasoning,
            "tool_call": metadata.tool_call,
            "structured_output": metadata.structured_output,
            "modalities": {
                "input": list(metadata.input_modalities)
                if metadata.input_modalities is not None
                else None,
                "output": list(metadata.output_modalities)
                if metadata.output_modalities is not None
                else None,
            },
            "limit": {
                "context": metadata.context_limit,
                "input": metadata.input_limit,
                "output": metadata.output_limit,
            },
            "release_date": metadata.release_date,
            "status": metadata.status,
            "knowledge": metadata.knowledge,
            "open_weights": metadata.open_weights,
        }
    return details


def _admin_provider_logo_url(provider_id: str) -> str | None:
    descriptor = PROVIDER_CATALOG.get(provider_id)
    if descriptor is None or not descriptor.logo_filename:
        return None
    return f"/admin/assets/{package_version()}/providers/{descriptor.logo_filename}"


def _filtered_values(values: Mapping[str, JsonValue]) -> JsonObject:
    return {key: value for key, value in values.items() if key in FIELD_BY_KEY}


def _local_provider_url(provider_id: str, values: dict[str, str]) -> str:
    if provider_id == "lmstudio":
        return values.get("LM_STUDIO_BASE_URL", "")
    if provider_id == "llamacpp":
        return values.get("LLAMACPP_BASE_URL", "")
    if provider_id == "ollama":
        return values.get("OLLAMA_BASE_URL", "")
    return ""


async def _check_local_provider(
    provider_id: str, base_url: str, path: str
) -> JsonObject:
    clean_url = base_url.strip().rstrip("/")
    if not clean_url:
        return {
            "provider_id": provider_id,
            "status": "missing_url",
            "label": "Missing URL",
            "base_url": base_url,
            "probe_path": path,
            "latency_ms": None,
            "error_type": None,
        }

    url = f"{clean_url}{path}"
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(url)
        ok = 200 <= response.status_code < 300
        return {
            "provider_id": provider_id,
            "status": "reachable" if ok else "offline",
            "label": "Reachable" if ok else "Offline",
            "base_url": base_url,
            "status_code": response.status_code,
            "probe_path": path,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "error_type": None if ok else "http_error",
        }
    except Exception as exc:
        logger.debug(
            "Admin local provider check failed: provider={} exc_type={}",
            provider_id,
            type(exc).__name__,
        )
        error_type, message = _local_provider_failure(exc)
        return {
            "provider_id": provider_id,
            "status": "offline",
            "label": "Offline",
            "base_url": base_url,
            "message": message,
            "probe_path": path,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "error_type": error_type,
        }


def _local_provider_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, httpx.TimeoutException):
        return (
            "timeout",
            "The local provider availability check timed out. Check that its server is responsive and retry.",
        )
    if isinstance(exc, (httpx.ConnectError, httpx.ProxyError)):
        return "connection_error", _LOCAL_PROVIDER_CHECK_FAILURE_MESSAGE
    if isinstance(exc, (httpx.InvalidURL, httpx.UnsupportedProtocol)):
        return (
            "invalid_url",
            "Check the local provider's HTTP or HTTPS base URL and port.",
        )
    if isinstance(exc, httpx.RequestError):
        return (
            "transport_error",
            "The connection ended before the availability check completed. Retry and check the local server logs.",
        )
    return "unexpected_error", _LOCAL_PROVIDER_CHECK_FAILURE_MESSAGE


def _require_connected_account_provider(provider_id: str) -> None:
    descriptor = PROVIDER_CATALOG.get(provider_id)
    if (
        descriptor is None
        or descriptor.auth_kind is not ProviderAuthKind.CONNECTED_ACCOUNT
    ):
        raise HTTPException(
            status_code=404,
            detail="Provider does not support connected-account login.",
        )


def _no_store(payload: JsonValue) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
