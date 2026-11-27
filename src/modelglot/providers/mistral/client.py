"""Mistral La Plateforme provider implementation (OpenAI-compatible chat completions)."""

from collections.abc import AsyncIterator, Mapping
from typing import Any, override

from openai.types.chat import ChatCompletionChunk

from modelglot.application.model_metadata import ProviderModelInfo
from modelglot.core.anthropic import ReasoningReplayMode
from modelglot.core.anthropic.models import MessagesRequest
from modelglot.core.chat_completions.request import ChatRequest
from modelglot.core.diagnostics import extract_upstream_error_detail
from modelglot.core.gemini import GeminiRequest
from modelglot.core.history_replay import ReplayOrigin
from modelglot.core.model_capabilities import ModelInputModality
from modelglot.core.openai_responses import OpenAIResponsesRequest
from modelglot.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from modelglot.core.stream_output import StreamOutput
from modelglot.core.stream_recovery import ContinuationSeed
from modelglot.providers.admission import ProviderAdmissionController
from modelglot.providers.base import ProviderConfig
from modelglot.providers.endpoint_types import EndpointContext
from modelglot.providers.history_negotiation import HistoryModeCache
from modelglot.providers.openai_chat import (
    NO_REASONING,
    OpenAIChatBehavior,
    OpenAIChatProfile,
    OpenAIChatProvider,
    OpenAIChatRequestPolicy,
    OpenAIModelListing,
)
from modelglot.providers.request_correction import Proposal

from .caching import mistral_affinity_headers
from .reasoning import (
    apply_mistral_history_shape,
    apply_mistral_reasoning_request_shape,
    clone_body_without_mistral_reasoning,
    is_mistral_reasoning_rejection,
    normalize_mistral_stream,
)

_REQUEST_POLICY = OpenAIChatRequestPolicy(
    provider_name="MISTRAL",
    reasoning_replay=ReasoningReplayMode.REASONING_CONTENT,
)
_PROFILE = OpenAIChatProfile(
    _REQUEST_POLICY,
    NO_REASONING,
    model_listing=OpenAIModelListing(
        input_modality_boolean_paths=(
            (
                ModelInputModality.TEXT,
                ("capabilities", "completion_chat"),
            ),
            (ModelInputModality.IMAGE, ("capabilities", "vision")),
        ),
        context_window_tokens_path=("max_context_length",),
    ),
)


class MistralChatBehavior(OpenAIChatBehavior):
    """Mistral Chat adaptation without HTTP ownership."""

    @property
    @override
    def reasoning_off_fields(self) -> tuple[tuple[str, ...], ...]:
        return (("reasoning_effort",),)

    @override
    def finalize_chat_body(
        self,
        body: dict[str, Any],
        *,
        reasoning: ReasoningPolicy,
    ) -> dict[str, Any]:
        apply_mistral_reasoning_request_shape(body, reasoning=reasoning)
        return body

    @override
    def prepare_history_body(
        self, body: dict[str, Any], origin: ReplayOrigin
    ) -> dict[str, Any]:
        apply_mistral_history_shape(body)
        return body

    @override
    def retry_request_body(
        self, error: Exception, body: dict[str, Any]
    ) -> Proposal | None:
        """Retry once without Mistral reasoning fields when a model rejects them."""
        detail = extract_upstream_error_detail(error)
        if not is_mistral_reasoning_rejection(error) or "reasoning_effort" not in (
            detail.body_text or detail.exception_text or ""
        ):
            return None
        retry_body = clone_body_without_mistral_reasoning(body)
        if retry_body is None:
            return None
        return Proposal(retry_body, "dropped reasoning")

    @override
    def normalize_stream(
        self,
        stream: AsyncIterator[ChatCompletionChunk],
        _body: Mapping[str, object],
    ) -> AsyncIterator[ChatCompletionChunk]:
        return normalize_mistral_stream(stream)


class MistralProvider(OpenAIChatProvider):
    """Mistral API using ``https://api.mistral.ai/v1/chat/completions``."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        admission: ProviderAdmissionController,
        history_cache: HistoryModeCache | None = None,
    ):
        super().__init__(
            config,
            behavior=MistralChatBehavior(_PROFILE),
            admission=admission,
            history_cache=history_cache,
        )

    @override
    def stream_messages(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        model_info: ProviderModelInfo | None = None,
        endpoint_context: EndpointContext | None = None,
        request_headers: Mapping[str, str] | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        """Stream with the Mistral prompt-cache affinity header when known.

        The base provider drops ``request_headers``; the transport accepts
        ``extra_headers`` instead, so the affinity header is derived here and
        passed straight through.
        """
        return self._chat.stream_messages(
            request,
            input_tokens=input_tokens,
            request_id=request_id,
            response_model=response_model,
            reasoning=reasoning,
            model_info=model_info,
            endpoint_context=endpoint_context,
            extra_headers=mistral_affinity_headers(request_headers),
            continuation=continuation,
        )

    @override
    def stream_chat(
        self,
        request: ChatRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        endpoint_context: EndpointContext | None = None,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        """Stream Chat with the Mistral prompt-cache affinity header."""
        return self._chat.stream_chat(
            request,
            input_tokens=input_tokens,
            request_id=request_id,
            response_model=response_model,
            reasoning=reasoning,
            endpoint_context=endpoint_context,
            extra_headers=mistral_affinity_headers(request_headers),
            continuation=continuation,
        )

    @override
    def stream_gemini(
        self,
        request: GeminiRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        endpoint_context: EndpointContext | None = None,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        """Stream Gemini with the Mistral prompt-cache affinity header."""
        return self._chat.stream_gemini(
            request,
            input_tokens=input_tokens,
            request_id=request_id,
            response_model=response_model,
            reasoning=reasoning,
            endpoint_context=endpoint_context,
            extra_headers=mistral_affinity_headers(request_headers),
            continuation=continuation,
        )

    @override
    def stream_responses(
        self,
        request: OpenAIResponsesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
        endpoint_context: EndpointContext | None = None,
        request_headers: Mapping[str, str] | None = None,
        model_info: ProviderModelInfo | None = None,
        continuation: ContinuationSeed | None = None,
    ) -> AsyncIterator[StreamOutput]:
        """Stream Responses with the Mistral prompt-cache affinity header."""
        return self._chat.stream_responses(
            request,
            input_tokens=input_tokens,
            request_id=request_id,
            response_model=response_model,
            reasoning=reasoning,
            endpoint_context=endpoint_context,
            extra_headers=mistral_affinity_headers(request_headers),
            continuation=continuation,
        )
