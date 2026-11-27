"""Base provider interface - extend this to implement your own provider."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from modelglot.application.errors import InvalidRequestError
from modelglot.application.model_metadata import ProviderModelInfo
from modelglot.core.anthropic.models import MessagesRequest
from modelglot.core.anthropic.passthrough import NativeMessagesRequest
from modelglot.core.chat_completions.request import ChatRequest
from modelglot.core.gemini import GeminiRequest
from modelglot.core.openai_responses import OpenAIResponsesRequest
from modelglot.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from modelglot.core.stream_output import StreamOutput
from modelglot.core.stream_recovery import ContinuationSeed
from modelglot.providers.history_negotiation import HistoryModeCache


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Resolved immutable configuration for one provider instance.

    Base fields apply to all providers.
    """

    api_key: str | None
    base_url: str
    http_read_timeout: float
    http_write_timeout: float
    http_connect_timeout: float
    proxy: str | None
    log_raw_sse_events: bool
    log_api_error_tracebacks: bool


class BaseProvider(ABC):
    """Base class for all providers. Extend this to add your own."""

    def __init__(
        self, config: ProviderConfig, *, history_cache: HistoryModeCache | None = None
    ):
        self._config = config
        self._history_cache = (
            history_cache if history_cache is not None else HistoryModeCache()
        )

    @abstractmethod
    async def cleanup(self) -> None:
        """Release any resources held by this provider."""

    @abstractmethod
    async def list_model_infos(self) -> frozenset[ProviderModelInfo]:
        """Return the model metadata currently advertised by this provider."""

    def stream_native_messages(
        self,
        request: NativeMessagesRequest,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        request_headers: Mapping[str, str] | None = None,
        reasoning_override: ReasoningPolicy | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        raise InvalidRequestError(
            "This provider does not support native Messages execution."
        )

    def stream_chat(
        self,
        request: ChatRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        raise InvalidRequestError("This provider does not support Chat execution.")

    def stream_gemini(
        self,
        request: GeminiRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        raise InvalidRequestError("This provider does not support Gemini execution.")

    @abstractmethod
    def stream_messages(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        """Validate the request before yielding a response in Anthropic SSE format."""

    @abstractmethod
    def stream_responses(
        self,
        request: OpenAIResponsesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        """Validate the request before yielding OpenAI Responses SSE events."""
