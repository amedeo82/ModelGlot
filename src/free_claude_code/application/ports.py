"""Typed capabilities consumed by application use cases."""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol, runtime_checkable

from free_claude_code.config.model_catalog_metadata import ModelCatalogMetadata
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic import MessagesRequest
from free_claude_code.core.anthropic.passthrough import NativeMessagesRequest
from free_claude_code.core.chat_completions.request import ChatRequest
from free_claude_code.core.gemini import GeminiRequest
from free_claude_code.core.json_types import JsonObject
from free_claude_code.core.openai_responses import OpenAIResponsesRequest
from free_claude_code.core.reasoning import ReasoningPolicy
from free_claude_code.core.stream_output import StreamOutput
from free_claude_code.core.stream_recovery import ContinuationSeed

from .model_metadata import ProviderModelInfo


class ProviderPort(Protocol):
    """Minimal provider capability required to execute one request."""

    def stream_chat(
        self,
        request: ChatRequest,
        *,
        input_tokens: int,
        request_id: str,
        response_model: str,
        reasoning: ReasoningPolicy,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]: ...

    def stream_gemini(
        self,
        request: GeminiRequest,
        *,
        input_tokens: int,
        request_id: str,
        response_model: str,
        reasoning: ReasoningPolicy,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]: ...

    def stream_native_messages(
        self,
        request: NativeMessagesRequest,
        *,
        request_id: str,
        response_model: str,
        request_headers: Mapping[str, str] | None = None,
        reasoning_override: ReasoningPolicy | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]: ...

    def stream_messages(
        self,
        request: MessagesRequest,
        *,
        input_tokens: int,
        request_id: str,
        response_model: str,
        reasoning: ReasoningPolicy,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]: ...

    def stream_responses(
        self,
        request: OpenAIResponsesRequest,
        *,
        input_tokens: int,
        request_id: str,
        response_model: str,
        reasoning: ReasoningPolicy,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]: ...


ProviderResolver = Callable[[str, int], Awaitable[ProviderPort]]
ModelInfoLookup = Callable[[str, str], ProviderModelInfo | None]


class RequestRuntimeLease(Protocol):
    """One provider generation retained for a complete API response."""

    @property
    def generation_id(self) -> int: ...

    @property
    def settings(self) -> Settings: ...

    def is_provider_cached(self, provider_id: str, api_key_number: int = 1) -> bool: ...

    async def wait_for_token_estimation(self) -> None: ...

    async def resolve_provider(
        self, provider_id: str, api_key_number: int = 1
    ) -> ProviderPort: ...

    def model_info(
        self, provider_id: str, model_id: str
    ) -> ProviderModelInfo | None: ...

    async def release(self) -> None: ...


class ModelCatalogPort(Protocol):
    """A coherent read-only projection of model configuration and metadata."""

    def current_settings(self) -> Settings: ...

    def cached_model_info(
        self, provider_id: str, model_id: str
    ) -> ProviderModelInfo | None: ...

    def cached_prefixed_model_infos(self) -> tuple[ProviderModelInfo, ...]: ...


@runtime_checkable
class ModelTitleCatalogPort(Protocol):
    """Optional runtime capability exposing cached presentation-only titles."""

    def model_title_catalog(self) -> Mapping[tuple[str, str], tuple[str, str]]: ...


class ModelCatalogLogoPort(Protocol):
    """Read-only access to previously validated same-origin catalog logos."""

    def url_for(self, kind: str, logo_id: str | None) -> str | None: ...

    def path_for(self, kind: str, logo_id: str) -> Path | None: ...


@runtime_checkable
class ModelCatalogMetadataPort(Protocol):
    """Optional runtime capability exposing provider-scoped catalog facts."""

    def model_catalog_metadata(
        self,
    ) -> Mapping[tuple[str, str], ModelCatalogMetadata]: ...


@dataclass(frozen=True, slots=True)
class ModelCatalogSnapshot:
    settings: Settings
    model_infos: tuple[ProviderModelInfo, ...]
    title_catalog: Mapping[tuple[str, str], tuple[str, str]] = field(
        default_factory=dict
    )
    catalog_metadata: Mapping[tuple[str, str], ModelCatalogMetadata] = field(
        default_factory=dict
    )

    def current_settings(self) -> Settings:
        return self.settings

    def cached_prefixed_model_infos(self) -> tuple[ProviderModelInfo, ...]:
        return self.model_infos

    def model_title_catalog(self) -> Mapping[tuple[str, str], tuple[str, str]]:
        return self.title_catalog

    def model_catalog_metadata(
        self,
    ) -> Mapping[tuple[str, str], ModelCatalogMetadata]:
        return self.catalog_metadata

    def cached_model_info(
        self, provider_id: str, model_id: str
    ) -> ProviderModelInfo | None:
        prefixed = f"{provider_id}/{model_id}"
        return next(
            (
                replace(info, model_id=model_id)
                for info in self.model_infos
                if info.model_id == prefixed
            ),
            None,
        )


class RequestRuntimePort(ModelCatalogPort, Protocol):
    """Provider generation and model metadata required by application requests."""

    async def acquire(self) -> RequestRuntimeLease: ...

    def catalog_snapshot(self) -> ModelCatalogSnapshot: ...

    async def wait_for_model_catalog(self, model: str) -> ModelCatalogSnapshot: ...

    def catalog_status(self) -> JsonObject: ...


@dataclass(frozen=True, slots=True)
class StopResult:
    """Implementation-neutral result retaining the existing ``/stop`` variants."""

    cancelled_count: int | None = None
    source: str | None = None


class TaskController(Protocol):
    """Stop managed work without exposing messaging or CLI resources."""

    async def stop_all(self) -> StopResult | None: ...
