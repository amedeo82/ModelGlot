"""Pure canonical usage models and provider usage normalization.

Unknown token counts stay ``None`` throughout normalization.  Diagnostics contain
only a protocol, a provider field name, and a stable reason code; provider values
and payloads are never copied into an issue.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from free_claude_code.core.request_outcomes import (
    current_request_outcome,
    record_request_observation,
)

MAX_USAGE_FILTER_RANGE = timedelta(days=31)


class UsageProtocol(StrEnum):
    ANTHROPIC_MESSAGES = "anthropic_messages"
    OPENAI_CHAT = "openai_chat"
    OPENAI_RESPONSES = "openai_responses"
    GEMINI = "gemini"


class UsageGroupBy(StrEnum):
    MODEL = "model"
    PROVIDER = "provider"
    DAY = "day"


@dataclass(frozen=True, slots=True)
class UsageIssue:
    protocol: UsageProtocol
    field: str
    reason: str


@dataclass(frozen=True, slots=True)
class CanonicalUsage:
    input_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    input_total_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    estimated_input_tokens: int | None = None

    def __post_init__(self) -> None:
        _validate_optional_count(self.input_tokens, "input_tokens")
        _validate_optional_count(self.cache_read_tokens, "cache_read_tokens")
        _validate_optional_count(self.cache_creation_tokens, "cache_creation_tokens")
        _validate_optional_count(self.input_total_tokens, "input_total_tokens")
        _validate_optional_count(self.output_tokens, "output_tokens")
        _validate_optional_count(self.reasoning_tokens, "reasoning_tokens")
        _validate_optional_count(self.total_tokens, "total_tokens")
        _validate_optional_count(self.estimated_input_tokens, "estimated_input_tokens")


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    usage: CanonicalUsage
    issues: tuple[UsageIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class UsageObservation:
    request_id: str
    execution_id: str
    attempt: int
    protocol: UsageProtocol
    usage: CanonicalUsage
    created_at: datetime
    provider_id: str | None = None
    gateway_model: str | None = None
    provider_model: str | None = None
    outcome: str = "succeeded"
    operation_kind: str = "generation"
    issues: tuple[UsageIssue, ...] = ()

    def __post_init__(self) -> None:
        _validate_event(self)
        _validate_choice(self.outcome, "outcome", {"succeeded", "failed", "cancelled"})
        _validate_choice(
            self.operation_kind, "operation_kind", {"generation", "continuation"}
        )
        object.__setattr__(self, "protocol", UsageProtocol(self.protocol))
        object.__setattr__(
            self, "created_at", _aware_utc(self.created_at, "created_at")
        )


@dataclass(frozen=True, slots=True)
class FinalUsageEvent:
    request_id: str
    execution_id: str
    attempt: int
    protocol: UsageProtocol
    usage: CanonicalUsage
    created_at: datetime
    provider_id: str | None = None
    gateway_model: str | None = None
    provider_model: str | None = None

    def __post_init__(self) -> None:
        _validate_event(self)
        object.__setattr__(self, "protocol", UsageProtocol(self.protocol))
        object.__setattr__(
            self, "created_at", _aware_utc(self.created_at, "created_at")
        )

    @classmethod
    def from_observation(cls, observation: UsageObservation) -> FinalUsageEvent:
        """Select the same final event again without changing its identity or usage."""

        return cls(
            request_id=observation.request_id,
            execution_id=observation.execution_id,
            attempt=observation.attempt,
            protocol=observation.protocol,
            usage=observation.usage,
            created_at=observation.created_at,
            provider_id=observation.provider_id,
            gateway_model=observation.gateway_model,
            provider_model=observation.provider_model,
        )


@dataclass(frozen=True, slots=True)
class RequestUsageRecord:
    """One final logical client request plus optional winning-attempt usage."""

    request_id: str
    wire_api: str
    outcome: str
    created_at: datetime
    execution_id: str | None = None
    attempt: int | None = None
    protocol: UsageProtocol | None = None
    usage: CanonicalUsage = field(default_factory=CanonicalUsage)
    provider_id: str | None = None
    gateway_model: str | None = None
    provider_model: str | None = None
    status_code: int | None = None
    duration_ms: float | None = None
    failure_category: str | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.request_id, "request_id")
        _validate_choice(
            self.wire_api, "wire_api", {"messages", "responses", "chat", "gemini"}
        )
        _validate_choice(self.outcome, "outcome", {"success", "failure", "cancelled"})
        object.__setattr__(
            self, "created_at", _aware_utc(self.created_at, "created_at")
        )
        if self.execution_id is not None:
            _validate_identity(self.execution_id, "execution_id")
        if self.attempt is not None and (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise ValueError("attempt must be a positive integer or None.")
        if self.protocol is not None:
            object.__setattr__(self, "protocol", UsageProtocol(self.protocol))
        if not isinstance(self.usage, CanonicalUsage):
            raise ValueError("usage must be a CanonicalUsage instance.")
        _validate_optional_identity(self.provider_id, "provider_id")
        _validate_optional_identity(self.gateway_model, "gateway_model")
        _validate_optional_identity(self.provider_model, "provider_model")
        if self.status_code is not None and (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 100 <= self.status_code <= 599
        ):
            raise ValueError("status_code must be a valid HTTP status or None.")
        if self.duration_ms is not None and (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, (int, float))
            or not math.isfinite(self.duration_ms)
            or self.duration_ms < 0
        ):
            raise ValueError("duration_ms must be non-negative or None.")
        if self.failure_category is not None:
            _validate_optional_identity(self.failure_category, "failure_category")


@dataclass(frozen=True, slots=True)
class UsageFilters:
    start: datetime
    end: datetime
    group_by: UsageGroupBy = UsageGroupBy.MODEL
    provider_id: str | None = None
    gateway_model: str | None = None
    provider_model: str | None = None

    def __post_init__(self) -> None:
        start = _aware_utc(self.start, "start")
        end = _aware_utc(self.end, "end")
        if start >= end:
            raise ValueError("start must be earlier than end.")
        if end - start > MAX_USAGE_FILTER_RANGE:
            raise ValueError("usage filter range must not exceed 31 days.")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "group_by", UsageGroupBy(self.group_by))
        _validate_optional_identity(self.provider_id, "provider_id")
        _validate_optional_identity(self.gateway_model, "gateway_model")
        _validate_optional_identity(self.provider_model, "provider_model")

    def contains(self, value: datetime) -> bool:
        """Match the half-open UTC interval ``[start, end)``."""

        timestamp = _aware_utc(value, "value")
        return self.start <= timestamp < self.end

    def matches(
        self, event: UsageObservation | FinalUsageEvent | RequestUsageRecord
    ) -> bool:
        return self.contains(event.created_at) and all(
            getattr(self, field_name) is None
            or getattr(self, field_name) == getattr(event, field_name)
            for field_name in ("provider_id", "gateway_model", "provider_model")
        )


@dataclass(frozen=True, slots=True)
class _Count:
    value: int | None
    reported: bool
    valid: bool


_MISSING_COUNT = _Count(value=None, reported=False, valid=True)


def _validate_optional_count(value: object, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer or None.")


def _validate_optional_identity(value: object, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{field_name} must be a non-empty string or None.")


def _validate_identity(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _validate_choice(value: object, field_name: str, choices: set[str]) -> None:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{field_name} has an unsupported value.")


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be an aware datetime.")
    return value.astimezone(UTC)


def _validate_event(event: UsageObservation | FinalUsageEvent) -> None:
    _validate_identity(event.request_id, "request_id")
    _validate_identity(event.execution_id, "execution_id")
    if (
        isinstance(event.attempt, bool)
        or not isinstance(event.attempt, int)
        or event.attempt < 1
    ):
        raise ValueError("attempt must be a positive integer.")
    if not isinstance(event.usage, CanonicalUsage):
        raise ValueError("usage must be a CanonicalUsage instance.")
    _validate_optional_identity(event.provider_id, "provider_id")
    _validate_optional_identity(event.gateway_model, "gateway_model")
    _validate_optional_identity(event.provider_model, "provider_model")


def _issue(
    issues: list[UsageIssue],
    protocol: UsageProtocol,
    field: str,
    reason: str,
) -> None:
    issues.append(UsageIssue(protocol=protocol, field=field, reason=reason))


def _payload(
    payload: object,
    protocol: UsageProtocol,
    issues: list[UsageIssue],
) -> Mapping[str, object]:
    if isinstance(payload, Mapping):
        return payload
    _issue(issues, protocol, "usage", "expected_object")
    return {}


def _details(
    payload: Mapping[str, object],
    field: str,
    protocol: UsageProtocol,
    issues: list[UsageIssue],
) -> Mapping[str, object]:
    value = payload.get(field)
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    _issue(issues, protocol, field, "expected_object")
    return {}


def _count(
    payload: Mapping[str, object],
    field: str,
    protocol: UsageProtocol,
    issues: list[UsageIssue],
) -> _Count:
    if field not in payload or payload[field] is None:
        return _MISSING_COUNT
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _issue(issues, protocol, field, "expected_non_negative_integer")
        return _Count(value=None, reported=True, valid=False)
    return _Count(value=value, reported=True, valid=True)


def _estimated(
    value: object,
    protocol: UsageProtocol,
    issues: list[UsageIssue],
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _issue(
            issues,
            protocol,
            "estimated_input_tokens",
            "expected_non_negative_integer",
        )
        return None
    return value


def _result(
    protocol: UsageProtocol,
    issues: list[UsageIssue],
    estimated_input_tokens: object,
    **fields: int | None,
) -> NormalizedUsage:
    return NormalizedUsage(
        usage=CanonicalUsage(
            **fields,
            estimated_input_tokens=_estimated(estimated_input_tokens, protocol, issues),
        ),
        issues=tuple(issues),
    )


def _reported_or_derived_total(
    total: _Count,
    input_total: int | None,
    output: int | None,
    protocol: UsageProtocol,
    issues: list[UsageIssue],
) -> int | None:
    if total.valid and total.value is not None:
        if (
            input_total is not None
            and output is not None
            and total.value != input_total + output
        ):
            _issue(
                issues,
                protocol,
                "total_tokens",
                "total_does_not_match_components",
            )
            return None
        return total.value
    if not total.reported and input_total is not None and output is not None:
        return input_total + output
    return None


def _reasoning_subset(
    reasoning: int | None,
    output: int | None,
    field: str,
    protocol: UsageProtocol,
    issues: list[UsageIssue],
) -> int | None:
    if reasoning is not None and output is not None and reasoning > output:
        _issue(issues, protocol, field, "reasoning_exceeds_output")
        return None
    return reasoning


def normalize_anthropic_usage(
    payload: object,
    *,
    estimated_input_tokens: int | None = None,
) -> NormalizedUsage:
    """Normalize Anthropic Messages' exclusive input and cache partitions."""

    protocol = UsageProtocol.ANTHROPIC_MESSAGES
    issues: list[UsageIssue] = []
    usage = _payload(payload, protocol, issues)
    input_count = _count(usage, "input_tokens", protocol, issues)
    cache_read = _count(usage, "cache_read_input_tokens", protocol, issues)
    cache_creation = _count(usage, "cache_creation_input_tokens", protocol, issues)
    output = _count(usage, "output_tokens", protocol, issues)

    partitions = (input_count, cache_read, cache_creation)
    input_total = None
    if all(count.valid and count.value is not None for count in partitions):
        input_total = sum(
            count.value for count in partitions if count.value is not None
        )
    output_tokens = output.value
    total_tokens = None
    if input_total is not None and output_tokens is not None:
        total_tokens = input_total + output_tokens
    return _result(
        protocol,
        issues,
        estimated_input_tokens,
        input_tokens=input_count.value,
        cache_read_tokens=cache_read.value,
        cache_creation_tokens=cache_creation.value,
        input_total_tokens=input_total,
        output_tokens=output_tokens,
        reasoning_tokens=None,
        total_tokens=total_tokens,
    )


def _normalize_openai(
    payload: object,
    *,
    protocol: UsageProtocol,
    input_field: str,
    output_field: str,
    input_details_field: str,
    output_details_field: str,
    estimated_input_tokens: object,
    deepseek: bool,
) -> NormalizedUsage:
    issues: list[UsageIssue] = []
    usage = _payload(payload, protocol, issues)
    input_total = _count(usage, input_field, protocol, issues)
    output = _count(usage, output_field, protocol, issues)
    total = _count(usage, "total_tokens", protocol, issues)
    input_details = _details(usage, input_details_field, protocol, issues)
    output_details = _details(usage, output_details_field, protocol, issues)
    reasoning = _count(output_details, "reasoning_tokens", protocol, issues)

    input_tokens: int | None = None
    cache_read: int | None = None
    cache_creation: int | None = None
    input_total_tokens = input_total.value
    deepseek_fields_present = any(
        field in usage and usage[field] is not None
        for field in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
    )
    if deepseek or deepseek_fields_present:
        hit = _count(usage, "prompt_cache_hit_tokens", protocol, issues)
        miss = _count(usage, "prompt_cache_miss_tokens", protocol, issues)
        if (
            hit.valid
            and miss.valid
            and hit.value is not None
            and miss.value is not None
        ):
            partition_total = hit.value + miss.value
            if (
                input_total.valid
                and input_total.value is not None
                and input_total.value != partition_total
            ):
                _issue(
                    issues,
                    protocol,
                    "prompt_cache_partition",
                    "deepseek_cache_partition_mismatch",
                )
            else:
                input_tokens = miss.value
                cache_read = hit.value
                if input_total_tokens is None:
                    input_total_tokens = partition_total
        elif (hit.reported or miss.reported) and hit.valid and miss.valid:
            _issue(
                issues,
                protocol,
                "prompt_cache_partition",
                "incomplete_deepseek_cache_partition",
            )
    else:
        cached = _count(input_details, "cached_tokens", protocol, issues)
        created = _count(input_details, "cache_write_tokens", protocol, issues)
        cache_read = cached.value
        cache_creation = created.value
        partition = (cached, created)
        if (
            input_total.valid
            and input_total.value is not None
            and any(count.reported for count in partition)
            and all(count.valid for count in partition)
        ):
            reported_cache_total = sum(
                count.value for count in partition if count.value is not None
            )
            if reported_cache_total <= input_total.value:
                input_tokens = input_total.value - reported_cache_total
            else:
                _issue(
                    issues,
                    protocol,
                    input_details_field,
                    "cache_partition_exceeds_input_total",
                )
                cache_read = None
                cache_creation = None

    output_tokens = output.value
    reasoning_tokens = _reasoning_subset(
        reasoning.value,
        output_tokens,
        f"{output_details_field}.reasoning_tokens",
        protocol,
        issues,
    )
    total_tokens = _reported_or_derived_total(
        total,
        input_total_tokens,
        output_tokens,
        protocol,
        issues,
    )
    return _result(
        protocol,
        issues,
        estimated_input_tokens,
        input_tokens=input_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        input_total_tokens=input_total_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
    )


def normalize_openai_chat_usage(
    payload: object,
    *,
    estimated_input_tokens: int | None = None,
    deepseek: bool = False,
) -> NormalizedUsage:
    """Normalize inclusive Chat Completions totals and their optional partitions."""

    return _normalize_openai(
        payload,
        protocol=UsageProtocol.OPENAI_CHAT,
        input_field="prompt_tokens",
        output_field="completion_tokens",
        input_details_field="prompt_tokens_details",
        output_details_field="completion_tokens_details",
        estimated_input_tokens=estimated_input_tokens,
        deepseek=deepseek,
    )


def normalize_deepseek_chat_usage(
    payload: object,
    *,
    estimated_input_tokens: int | None = None,
) -> NormalizedUsage:
    """Normalize DeepSeek's validated cache-hit/cache-miss input partition."""

    return normalize_openai_chat_usage(
        payload,
        estimated_input_tokens=estimated_input_tokens,
        deepseek=True,
    )


def normalize_openai_responses_usage(
    payload: object,
    *,
    estimated_input_tokens: int | None = None,
) -> NormalizedUsage:
    """Normalize inclusive Responses totals and output reasoning subsets."""

    return _normalize_openai(
        payload,
        protocol=UsageProtocol.OPENAI_RESPONSES,
        input_field="input_tokens",
        output_field="output_tokens",
        input_details_field="input_tokens_details",
        output_details_field="output_tokens_details",
        estimated_input_tokens=estimated_input_tokens,
        deepseek=False,
    )


def normalize_gemini_usage(
    payload: object,
    *,
    estimated_input_tokens: int | None = None,
) -> NormalizedUsage:
    """Disambiguate Gemini candidates/thoughts using the inclusive total."""

    protocol = UsageProtocol.GEMINI
    issues: list[UsageIssue] = []
    usage = _payload(payload, protocol, issues)
    prompt = _count(usage, "promptTokenCount", protocol, issues)
    cached = _count(usage, "cachedContentTokenCount", protocol, issues)
    candidates = _count(usage, "candidatesTokenCount", protocol, issues)
    thoughts = _count(usage, "thoughtsTokenCount", protocol, issues)
    total = _count(usage, "totalTokenCount", protocol, issues)

    input_total_tokens = prompt.value
    input_tokens = None
    cache_read_tokens = cached.value
    if prompt.valid and prompt.value is not None and cached.reported and cached.valid:
        if cached.value is not None and cached.value <= prompt.value:
            input_tokens = prompt.value - cached.value
        else:
            _issue(
                issues,
                protocol,
                "cachedContentTokenCount",
                "cache_partition_exceeds_input_total",
            )
            cache_read_tokens = None

    output_tokens = None
    total_tokens = total.value if total.valid else None
    output_is_unambiguous = (
        candidates.valid
        and candidates.value is not None
        and (not thoughts.reported or (thoughts.valid and thoughts.value == 0))
    )
    if output_is_unambiguous and candidates.value is not None:
        output_tokens = candidates.value
        if total.valid and total.value is not None:
            if prompt.value is not None and total.value != prompt.value + output_tokens:
                _issue(
                    issues,
                    protocol,
                    "totalTokenCount",
                    "total_does_not_match_components",
                )
                total_tokens = None
        elif not total.reported and prompt.value is not None:
            total_tokens = prompt.value + output_tokens
    elif (
        candidates.valid
        and candidates.value is not None
        and thoughts.valid
        and thoughts.value is not None
        and prompt.valid
        and prompt.value is not None
        and total.valid
        and total.value is not None
    ):
        exclusive_total = prompt.value + candidates.value + thoughts.value
        inclusive_total = prompt.value + candidates.value
        if total.value == exclusive_total:
            output_tokens = candidates.value + thoughts.value
        elif total.value == inclusive_total:
            output_tokens = candidates.value
        else:
            _issue(
                issues,
                protocol,
                "totalTokenCount",
                "total_does_not_match_components",
            )
            total_tokens = None

    reasoning_tokens = _reasoning_subset(
        thoughts.value,
        output_tokens,
        "thoughtsTokenCount",
        protocol,
        issues,
    )
    return _result(
        protocol,
        issues,
        estimated_input_tokens,
        input_tokens=input_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=None,
        input_total_tokens=input_total_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
    )


def normalize_provider_usage(
    protocol: str,
    payload: object,
    *,
    estimated_input_tokens: int | None = None,
    provider_id: str | None = None,
) -> NormalizedUsage:
    """Normalize one allow-listed upstream snapshot without transport imports."""

    if protocol == "messages":
        return normalize_anthropic_usage(
            payload, estimated_input_tokens=estimated_input_tokens
        )
    if protocol == "chat":
        return normalize_openai_chat_usage(
            payload,
            estimated_input_tokens=estimated_input_tokens,
            deepseek=provider_id == "deepseek",
        )
    if protocol == "responses":
        return normalize_openai_responses_usage(
            payload, estimated_input_tokens=estimated_input_tokens
        )
    if protocol == "gemini":
        return normalize_gemini_usage(
            payload, estimated_input_tokens=estimated_input_tokens
        )
    raise ValueError("unsupported provider usage protocol")


def usage_protocol(protocol: str) -> UsageProtocol:
    return {
        "messages": UsageProtocol.ANTHROPIC_MESSAGES,
        "chat": UsageProtocol.OPENAI_CHAT,
        "responses": UsageProtocol.OPENAI_RESPONSES,
        "gemini": UsageProtocol.GEMINI,
    }[protocol]


def record_terminal_usage(
    *,
    request_id: str | None,
    execution_id: str,
    attempt: int,
    protocol: str,
    payload: object,
    provider_id: str,
    gateway_model: str,
    provider_model: str | None,
    outcome: str,
    operation_kind: str,
    created_at: datetime,
) -> UsageObservation | None:
    """Record one immutable terminal attempt in the current request, if any."""

    outcome_state = current_request_outcome.get()
    if outcome_state is None or not request_id:
        return None
    normalized = normalize_provider_usage(
        protocol,
        payload,
        estimated_input_tokens=outcome_state.estimated_input_tokens,
        provider_id=provider_id,
    )
    observation = UsageObservation(
        request_id=request_id,
        execution_id=execution_id,
        attempt=attempt,
        protocol=usage_protocol(protocol),
        usage=normalized.usage,
        created_at=created_at,
        provider_id=provider_id,
        gateway_model=gateway_model,
        provider_model=provider_model,
        outcome=outcome,
        operation_kind=operation_kind,
        issues=normalized.issues,
    )
    if record_request_observation(execution_id, attempt, observation):
        return observation
    return None


__all__ = [
    "MAX_USAGE_FILTER_RANGE",
    "CanonicalUsage",
    "FinalUsageEvent",
    "NormalizedUsage",
    "RequestUsageRecord",
    "UsageFilters",
    "UsageGroupBy",
    "UsageIssue",
    "UsageObservation",
    "UsageProtocol",
    "normalize_anthropic_usage",
    "normalize_deepseek_chat_usage",
    "normalize_gemini_usage",
    "normalize_openai_chat_usage",
    "normalize_openai_responses_usage",
    "normalize_provider_usage",
    "record_terminal_usage",
    "usage_protocol",
]
