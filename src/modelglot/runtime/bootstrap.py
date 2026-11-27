"""Single production composition root for the ModelGlot server."""

import os
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from modelglot.api.app import create_app
from modelglot.api.ports import ApiServices
from modelglot.application.code_sessions import CodeService
from modelglot.config.api_keys import first_api_key
from modelglot.config.loader import ManagedConfigStore
from modelglot.config.logging_config import configure_logging
from modelglot.config.paths import (
    code_lock_path,
    legacy_code_database_path,
    model_catalog_cache_path,
    model_catalog_logo_dir_path,
    modelglot_database_path,
    server_log_path,
)
from modelglot.config.settings import Settings
from modelglot.core.async_tasks import run_sync_owned
from modelglot.messaging.voice import Transcriber
from modelglot.providers.base import BaseProvider, ProviderConfig
from modelglot.providers.github_copilot.auth import CopilotAuthManager
from modelglot.providers.history_negotiation import HistoryModeCache
from modelglot.providers.model_catalog_logos import ModelCatalogLogoStore
from modelglot.providers.model_catalog_source import ModelCatalogSource
from modelglot.providers.openai_codex.auth import OpenAIAuthManager
from modelglot.providers.runtime.runtime import ProviderRuntime, create_provider

if TYPE_CHECKING:
    from modelglot.providers.admission import ProviderAdmissionController
    from modelglot.providers.runtime.factory import ProviderFactory

from .application import ApplicationRuntime, RestartCallback
from .asgi import RuntimeASGIApp
from .code_sessions_sqlite import SQLiteCodeStore
from .codex_app_server import CodexHarnessFactory
from .codex_catalog import CodexModelCatalogPublisher
from .configuration import ConfigurationService
from .provider_manager import ProviderRuntimeManager
from .sqlite_database import SQLiteDatabase
from .token_optimization import ExternalTokenOptimizationCollector
from .usage_events_sqlite import SQLiteUsageEventStore
from .web_tools.client import HTTPWebToolsClient


def build_asgi_app(
    settings: Settings,
    restart_callback: RestartCallback | None = None,
) -> RuntimeASGIApp:
    """Construct the complete server application and its resource owner."""
    log_path = Path(os.getenv("LOG_FILE", server_log_path()))
    configure_logging(
        log_path,
        level=settings.log_level,
        verbose_third_party=settings.log_raw_api_payloads,
    )
    openai_auth = OpenAIAuthManager(proxy=settings.openai_proxy)
    copilot_auth = CopilotAuthManager()
    copilot_factory = partial(_load_copilot_provider, auth=copilot_auth)
    openai_factory = partial(_load_openai_provider, auth=openai_auth)
    provider_constructor = partial(
        create_provider,
        provider_loaders={
            "openai": openai_factory,
            "github_copilot": copilot_factory,
        },
    )
    runtime_factory = partial(
        ProviderRuntime,
        provider_constructor=provider_constructor,
    )
    model_catalog_logos = ModelCatalogLogoStore(model_catalog_logo_dir_path())
    provider_manager = ProviderRuntimeManager(
        settings,
        runtime_factory=runtime_factory,
        connected_provider_ids=lambda: (
            *openai_auth.connected_provider_ids(),
            *copilot_auth.connected_provider_ids(),
        ),
        model_catalog_publisher=CodexModelCatalogPublisher(),
        model_title_source=ModelCatalogSource(model_catalog_cache_path()),
        model_catalog_logos=model_catalog_logos,
    )
    database = SQLiteDatabase(
        modelglot_database_path(),
        code_lock_path(),
        legacy_path=legacy_code_database_path(),
    )
    code_service = CodeService(
        SQLiteCodeStore(database),
        CodexHarnessFactory(provider_manager),
    )
    runtime = ApplicationRuntime(
        provider_manager,
        configuration=ConfigurationService(ManagedConfigStore()),
        code_service=code_service,
        database=database,
        transcriber=None,
        transcriber_factory=_create_transcriber,
        restart_callback=restart_callback,
        connected_accounts={"openai": openai_auth, "github_copilot": copilot_auth},
        token_optimization_collector=ExternalTokenOptimizationCollector(),
        usage_store=SQLiteUsageEventStore(database),
    )
    services = ApiServices(
        requests=provider_manager,
        admin=runtime,
        integrations=runtime.integrations,
        tasks=runtime,
        web_tools=HTTPWebToolsClient(),
        code=code_service,
        usage=runtime,
        model_catalog_logos=model_catalog_logos,
    )
    return RuntimeASGIApp(create_app(services), runtime)


def _load_openai_provider(*, auth: OpenAIAuthManager) -> ProviderFactory:
    from modelglot.providers.openai_codex.provider import OpenAICodexProvider

    def construct(
        config: ProviderConfig,
        _settings: Settings,
        admission: ProviderAdmissionController,
        history_cache: HistoryModeCache | None = None,
    ) -> BaseProvider:
        return OpenAICodexProvider(
            config, auth=auth, admission=admission, history_cache=history_cache
        )

    return construct


def _load_copilot_provider(*, auth: CopilotAuthManager) -> ProviderFactory:
    from modelglot.providers.github_copilot.provider import GitHubCopilotProvider

    def construct(
        config: ProviderConfig,
        _settings: Settings,
        admission: ProviderAdmissionController,
        history_cache: HistoryModeCache | None = None,
    ) -> BaseProvider:
        return GitHubCopilotProvider(
            config, auth=auth, admission=admission, history_cache=history_cache
        )

    return construct


async def _create_transcriber(settings: Settings) -> Transcriber | None:
    if not settings.voice_note_enabled:
        return None

    def load():
        if settings.whisper_device == "nvidia_nim":
            from modelglot.providers.nvidia_nim.voice import NvidiaNimTranscriber

            return partial(
                NvidiaNimTranscriber,
                model=settings.whisper_model,
                api_key=_required_voice_key(
                    first_api_key(settings.nvidia_nim_api_keys)
                ),
            )
        from modelglot.messaging.transcription import TranscriptionService

        return partial(
            TranscriptionService,
            model=settings.whisper_model,
            device=settings.whisper_device,
            huggingface_api_key=first_api_key(settings.huggingface_api_keys),
        )

    constructor = await run_sync_owned(load)
    return constructor()


def _required_voice_key(api_key: str | None) -> str:
    if api_key is None:
        raise AssertionError("NIM voice settings were not validated")
    return api_key
