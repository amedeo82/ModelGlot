from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from modelglot.application.usage_events import (
    CanonicalUsage,
    FinalUsageEvent,
    NormalizedUsage,
    UsageFilters,
    UsageGroupBy,
    UsageObservation,
    UsageProtocol,
    normalize_anthropic_usage,
    normalize_deepseek_chat_usage,
    normalize_gemini_usage,
    normalize_openai_chat_usage,
    normalize_openai_responses_usage,
)


def test_anthropic_partitions_inclusive_input_without_double_counting() -> None:
    result = normalize_anthropic_usage(
        {
            "input_tokens": 70,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 10,
            "output_tokens": 11,
        },
        estimated_input_tokens=123,
    )

    assert result.usage == CanonicalUsage(
        input_tokens=70,
        cache_read_tokens=20,
        cache_creation_tokens=10,
        input_total_tokens=100,
        output_tokens=11,
        reasoning_tokens=None,
        total_tokens=111,
        estimated_input_tokens=123,
    )
    assert result.issues == ()


def test_anthropic_missing_partition_fields_do_not_become_zero() -> None:
    result = normalize_anthropic_usage({"input_tokens": 7, "output_tokens": 2})

    assert result.usage.input_tokens == 7
    assert result.usage.cache_read_tokens is None
    assert result.usage.cache_creation_tokens is None
    assert result.usage.input_total_tokens is None
    assert result.usage.output_tokens == 2
    assert result.usage.total_tokens is None
    assert result.usage.estimated_input_tokens is None
    assert result.issues == ()


def test_anthropic_explicit_zeroes_remain_zero() -> None:
    result = normalize_anthropic_usage(
        {
            "input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "output_tokens": 0,
        },
        estimated_input_tokens=0,
    )

    assert result.usage == CanonicalUsage(
        input_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_total_tokens=0,
        output_tokens=0,
        total_tokens=0,
        estimated_input_tokens=0,
    )


@pytest.mark.parametrize("invalid", [True, False, -1, 1.5, "7", [], {}])
def test_anthropic_invalid_count_is_unknown_and_sanitized(invalid: object) -> None:
    result = normalize_anthropic_usage(
        {
            "input_tokens": invalid,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 3,
            "output_tokens": 4,
        }
    )

    assert result.usage.input_tokens is None
    assert result.usage.cache_read_tokens == 2
    assert result.usage.cache_creation_tokens == 3
    assert result.usage.input_total_tokens is None
    assert result.usage.output_tokens == 4
    assert result.usage.total_tokens is None
    issue = result.issues[0]
    assert issue.protocol is UsageProtocol.ANTHROPIC_MESSAGES
    assert issue.field == "input_tokens"
    assert issue.reason == "expected_non_negative_integer"
    assert repr(invalid) not in repr(result.issues) or invalid in (True, False, -1, 1.5)


def test_anthropic_invalid_cache_invalidates_only_dependent_totals() -> None:
    result = normalize_anthropic_usage(
        {
            "input_tokens": 5,
            "cache_read_input_tokens": -2,
            "cache_creation_input_tokens": 1,
            "output_tokens": 3,
        }
    )

    assert result.usage.input_tokens == 5
    assert result.usage.cache_read_tokens is None
    assert result.usage.cache_creation_tokens == 1
    assert result.usage.input_total_tokens is None
    assert result.usage.total_tokens is None


def test_openai_chat_inclusive_prompt_and_reasoning_subset() -> None:
    result = normalize_openai_chat_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "total_tokens": 125,
            "prompt_tokens_details": {
                "cached_tokens": 30,
                "cache_write_tokens": 10,
            },
            "completion_tokens_details": {"reasoning_tokens": 7},
        }
    )

    assert result.usage == CanonicalUsage(
        input_tokens=60,
        cache_read_tokens=30,
        cache_creation_tokens=10,
        input_total_tokens=100,
        output_tokens=25,
        reasoning_tokens=7,
        total_tokens=125,
    )


def test_openai_chat_cache_read_zero_is_a_real_partition() -> None:
    result = normalize_openai_chat_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0},
        }
    )

    assert result.usage.input_tokens == 100
    assert result.usage.cache_read_tokens == 0
    assert result.usage.cache_creation_tokens is None
    assert result.usage.input_total_tokens == 100
    assert result.usage.output_tokens == 0
    assert result.usage.total_tokens == 100


def test_openai_chat_absent_details_preserve_total_but_not_uncached_input() -> None:
    result = normalize_openai_chat_usage(
        {"prompt_tokens": 100, "completion_tokens": 20}
    )

    assert result.usage.input_tokens is None
    assert result.usage.cache_read_tokens is None
    assert result.usage.cache_creation_tokens is None
    assert result.usage.input_total_tokens == 100
    assert result.usage.output_tokens == 20
    assert result.usage.reasoning_tokens is None
    assert result.usage.total_tokens == 120


def test_openai_chat_inconsistent_reported_total_becomes_unknown() -> None:
    result = normalize_openai_chat_usage(
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 99}
    )

    assert result.usage.input_total_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens is None
    assert [(issue.field, issue.reason) for issue in result.issues] == [
        ("total_tokens", "total_does_not_match_components")
    ]


def test_openai_chat_reasoning_larger_than_output_becomes_unknown() -> None:
    result = normalize_openai_chat_usage(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "completion_tokens_details": {"reasoning_tokens": 6},
        }
    )

    assert result.usage.output_tokens == 5
    assert result.usage.reasoning_tokens is None
    assert result.usage.total_tokens == 15
    assert result.issues[0].reason == "reasoning_exceeds_output"


def test_openai_chat_cache_partition_larger_than_prompt_is_rejected() -> None:
    result = normalize_openai_chat_usage(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {
                "cached_tokens": 8,
                "cache_write_tokens": 3,
            },
        }
    )

    assert result.usage.input_tokens is None
    assert result.usage.cache_read_tokens is None
    assert result.usage.cache_creation_tokens is None
    assert result.usage.input_total_tokens == 10
    assert result.usage.total_tokens == 15
    assert result.issues[0].field == "prompt_tokens_details"
    assert result.issues[0].reason == "cache_partition_exceeds_input_total"


def test_openai_responses_inclusive_input_and_output_details() -> None:
    result = normalize_openai_responses_usage(
        {
            "input_tokens": 80,
            "output_tokens": 15,
            "total_tokens": 95,
            "input_tokens_details": {
                "cached_tokens": 20,
                "cache_write_tokens": 5,
            },
            "output_tokens_details": {"reasoning_tokens": 6},
        }
    )

    assert result.usage == CanonicalUsage(
        input_tokens=55,
        cache_read_tokens=20,
        cache_creation_tokens=5,
        input_total_tokens=80,
        output_tokens=15,
        reasoning_tokens=6,
        total_tokens=95,
    )


def test_openai_responses_null_counts_are_not_defaults() -> None:
    result = normalize_openai_responses_usage(
        {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "input_tokens_details": {"cached_tokens": None},
            "output_tokens_details": {"reasoning_tokens": None},
        }
    )

    assert result.usage == CanonicalUsage()
    assert result.issues == ()


@pytest.mark.parametrize(
    ("normalizer", "details_field"),
    [
        (normalize_openai_chat_usage, "prompt_tokens_details"),
        (normalize_openai_responses_usage, "input_tokens_details"),
    ],
)
def test_openai_malformed_details_emit_issue_without_payload(
    normalizer: Callable[[object], NormalizedUsage], details_field: str
) -> None:
    result = normalizer({details_field: "private-provider-payload"})

    assert result.usage.input_total_tokens is None
    assert result.usage.input_tokens is None
    assert [(issue.field, issue.reason) for issue in result.issues] == [
        (details_field, "expected_object")
    ]
    assert "private-provider-payload" not in repr(result)


@pytest.mark.parametrize("invalid", [True, -1, 2.5, "secret"])
def test_openai_nested_invalid_count_does_not_derive_partition(
    invalid: object,
) -> None:
    result = normalize_openai_chat_usage(
        {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "prompt_tokens_details": {"cached_tokens": invalid},
        }
    )

    assert result.usage.input_tokens is None
    assert result.usage.cache_read_tokens is None
    assert result.usage.input_total_tokens == 10
    assert result.usage.total_tokens == 12
    assert result.issues[0].reason == "expected_non_negative_integer"
    assert "secret" not in repr(result.issues)


def test_deepseek_hit_miss_partition_is_coherent() -> None:
    result = normalize_deepseek_chat_usage(
        {
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
            "prompt_tokens": 100,
            "completion_tokens": 5,
            "total_tokens": 105,
        }
    )

    assert result.usage == CanonicalUsage(
        input_tokens=60,
        cache_read_tokens=40,
        cache_creation_tokens=None,
        input_total_tokens=100,
        output_tokens=5,
        reasoning_tokens=None,
        total_tokens=105,
    )


def test_deepseek_partition_can_supply_missing_inclusive_prompt_total() -> None:
    result = normalize_openai_chat_usage(
        {
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 12,
            "completion_tokens": 3,
        }
    )

    assert result.usage.input_tokens == 12
    assert result.usage.cache_read_tokens == 0
    assert result.usage.input_total_tokens == 12
    assert result.usage.total_tokens == 15


def test_deepseek_mismatch_rejects_partition_not_provider_prompt_total() -> None:
    result = normalize_deepseek_chat_usage(
        {
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 50,
            "prompt_tokens": 100,
            "completion_tokens": 5,
            "total_tokens": 105,
        }
    )

    assert result.usage.input_tokens is None
    assert result.usage.cache_read_tokens is None
    assert result.usage.input_total_tokens == 100
    assert result.usage.total_tokens == 105
    assert [(issue.field, issue.reason) for issue in result.issues] == [
        ("prompt_cache_partition", "deepseek_cache_partition_mismatch")
    ]


def test_deepseek_incomplete_partition_does_not_assume_missing_half_is_zero() -> None:
    result = normalize_deepseek_chat_usage(
        {"prompt_cache_hit_tokens": 4, "prompt_tokens": 10}
    )

    assert result.usage.input_tokens is None
    assert result.usage.cache_read_tokens is None
    assert result.usage.input_total_tokens == 10
    assert result.issues[0].reason == "incomplete_deepseek_cache_partition"


@pytest.mark.parametrize(
    ("candidates", "thoughts", "total", "expected_output"),
    [(8, 3, 21, 11), (11, 3, 21, 11), (8, 3, 18, 8)],
)
def test_gemini_uses_total_to_disambiguate_candidates_and_thoughts(
    candidates: int, thoughts: int, total: int, expected_output: int
) -> None:
    result = normalize_gemini_usage(
        {
            "promptTokenCount": 10,
            "candidatesTokenCount": candidates,
            "thoughtsTokenCount": thoughts,
            "totalTokenCount": total,
        }
    )

    assert result.usage.input_total_tokens == 10
    assert result.usage.output_tokens == expected_output
    assert result.usage.reasoning_tokens == 3
    assert result.usage.total_tokens == total
    assert result.issues == ()


def test_gemini_ambiguous_candidates_without_total_remain_unknown() -> None:
    result = normalize_gemini_usage(
        {
            "promptTokenCount": 10,
            "candidatesTokenCount": 8,
            "thoughtsTokenCount": 3,
        }
    )

    assert result.usage.input_total_tokens == 10
    assert result.usage.output_tokens is None
    assert result.usage.reasoning_tokens == 3
    assert result.usage.total_tokens is None
    assert result.issues == ()


def test_gemini_zero_thoughts_make_output_unambiguous_without_total() -> None:
    result = normalize_gemini_usage(
        {
            "promptTokenCount": 10,
            "candidatesTokenCount": 8,
            "thoughtsTokenCount": 0,
        }
    )

    assert result.usage.output_tokens == 8
    assert result.usage.reasoning_tokens == 0
    assert result.usage.total_tokens == 18


def test_gemini_absent_thoughts_do_not_get_added_to_candidates() -> None:
    result = normalize_gemini_usage({"promptTokenCount": 10, "candidatesTokenCount": 8})

    assert result.usage.output_tokens == 8
    assert result.usage.reasoning_tokens is None
    assert result.usage.total_tokens == 18


def test_gemini_total_matching_neither_interpretation_is_unknown() -> None:
    result = normalize_gemini_usage(
        {
            "promptTokenCount": 10,
            "candidatesTokenCount": 8,
            "thoughtsTokenCount": 3,
            "totalTokenCount": 99,
        }
    )

    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None
    assert [(issue.field, issue.reason) for issue in result.issues] == [
        ("totalTokenCount", "total_does_not_match_components")
    ]


def test_gemini_cached_content_is_partitioned_from_inclusive_prompt() -> None:
    result = normalize_gemini_usage(
        {
            "promptTokenCount": 10,
            "cachedContentTokenCount": 4,
            "candidatesTokenCount": 2,
            "totalTokenCount": 12,
        }
    )

    assert result.usage.input_tokens == 6
    assert result.usage.cache_read_tokens == 4
    assert result.usage.input_total_tokens == 10
    assert result.usage.output_tokens == 2


def test_gemini_invalid_cache_does_not_invent_uncached_input() -> None:
    result = normalize_gemini_usage(
        {
            "promptTokenCount": 10,
            "cachedContentTokenCount": 11,
            "candidatesTokenCount": 2,
            "totalTokenCount": 12,
        }
    )

    assert result.usage.input_tokens is None
    assert result.usage.cache_read_tokens is None
    assert result.usage.input_total_tokens == 10
    assert result.usage.total_tokens == 12
    assert result.issues[0].reason == "cache_partition_exceeds_input_total"


def test_gemini_inclusive_candidates_validate_reasoning_subset() -> None:
    result = normalize_gemini_usage(
        {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "thoughtsTokenCount": 7,
            "totalTokenCount": 15,
        }
    )

    assert result.usage.output_tokens == 5
    assert result.usage.reasoning_tokens is None
    assert result.usage.total_tokens == 15
    assert result.issues[0].field == "thoughtsTokenCount"
    assert result.issues[0].reason == "reasoning_exceeds_output"


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "secret"])
@pytest.mark.parametrize(
    ("field", "canonical_field"),
    [
        ("promptTokenCount", "input_total_tokens"),
        ("cachedContentTokenCount", "cache_read_tokens"),
        ("candidatesTokenCount", "output_tokens"),
        ("thoughtsTokenCount", "reasoning_tokens"),
        ("totalTokenCount", "total_tokens"),
    ],
)
def test_gemini_invalid_counts_are_unknown_and_sanitized(
    field: str, canonical_field: str, invalid: object
) -> None:
    payload = {
        "promptTokenCount": 10,
        "cachedContentTokenCount": 4,
        "candidatesTokenCount": 8,
        "thoughtsTokenCount": 3,
        "totalTokenCount": 21,
        field: invalid,
    }

    result = normalize_gemini_usage(payload)

    assert getattr(result.usage, canonical_field) is None
    assert any(issue.field == field for issue in result.issues)
    assert "secret" not in repr(result.issues)


@pytest.mark.parametrize(
    ("normalizer", "protocol"),
    [
        (normalize_anthropic_usage, UsageProtocol.ANTHROPIC_MESSAGES),
        (normalize_openai_chat_usage, UsageProtocol.OPENAI_CHAT),
        (normalize_openai_responses_usage, UsageProtocol.OPENAI_RESPONSES),
        (normalize_gemini_usage, UsageProtocol.GEMINI),
    ],
)
def test_malformed_root_returns_all_unknown_with_sanitized_issue(
    normalizer: Callable[[object], NormalizedUsage], protocol: UsageProtocol
) -> None:
    result = normalizer("private raw response")

    assert result.usage == CanonicalUsage()
    assert len(result.issues) == 1
    assert result.issues[0].protocol is protocol
    assert result.issues[0].field == "usage"
    assert result.issues[0].reason == "expected_object"
    assert "private raw response" not in repr(result)


def test_invalid_estimate_is_unknown_separate_from_provider_usage() -> None:
    result = normalize_openai_responses_usage(
        {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        estimated_input_tokens=True,
    )

    assert result.usage.input_total_tokens == 0
    assert result.usage.total_tokens == 0
    assert result.usage.estimated_input_tokens is None
    assert result.issues[0].field == "estimated_input_tokens"


def test_canonical_usage_is_immutable_and_validates_direct_construction() -> None:
    usage = CanonicalUsage(input_tokens=0)

    with pytest.raises(FrozenInstanceError):
        usage.__setattr__("input_tokens", 1)
    with pytest.raises(ValueError, match="non-negative integer"):
        CanonicalUsage(input_tokens=True)
    with pytest.raises(ValueError, match="non-negative integer"):
        CanonicalUsage(total_tokens=-1)


def _observation(created_at: datetime) -> UsageObservation:
    return UsageObservation(
        request_id="request-1",
        execution_id="execution-1",
        attempt=1,
        protocol=UsageProtocol.OPENAI_CHAT,
        usage=CanonicalUsage(input_total_tokens=10),
        created_at=created_at,
        provider_id="provider-a",
        gateway_model="gateway-a",
        provider_model="provider-model-a",
    )


def test_final_event_selection_is_idempotent_and_timestamps_are_utc() -> None:
    offset = timezone(timedelta(hours=2))
    observation = _observation(datetime(2026, 11, 18, 12, tzinfo=offset))

    first = FinalUsageEvent.from_observation(observation)
    second = FinalUsageEvent.from_observation(observation)

    assert first == second
    assert first.created_at == datetime(2026, 11, 18, 10, tzinfo=UTC)
    assert observation.created_at.tzinfo is UTC


@pytest.mark.parametrize("attempt", [True, 0, -1, 1.5])
def test_observation_rejects_invalid_attempt(attempt: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        UsageObservation(
            request_id="request",
            execution_id="execution",
            attempt=cast(int, attempt),
            protocol=UsageProtocol.GEMINI,
            usage=CanonicalUsage(),
            created_at=datetime(2026, 11, 18, tzinfo=UTC),
        )


def test_observation_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="aware datetime"):
        _observation(datetime(2026, 11, 18))


def test_usage_filters_use_half_open_utc_interval_and_metadata() -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    filters = UsageFilters(
        start=start,
        end=end,
        group_by=cast(UsageGroupBy, "model"),
        provider_id="provider-a",
        gateway_model="gateway-a",
    )

    assert filters.group_by is UsageGroupBy.MODEL
    assert filters.contains(start)
    assert not filters.contains(end)
    assert filters.contains(end - timedelta(microseconds=1))
    assert filters.matches(_observation(start))
    assert not filters.matches(_observation(end))
    assert not filters.matches(
        UsageObservation(
            request_id="request-2",
            execution_id="execution-2",
            attempt=1,
            protocol=UsageProtocol.GEMINI,
            usage=CanonicalUsage(),
            created_at=start,
            provider_id="provider-b",
        )
    )


def test_usage_filters_allow_exactly_31_days_and_reject_larger_ranges() -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)

    filters = UsageFilters(start=start, end=start + timedelta(days=31))
    assert filters.group_by is UsageGroupBy.MODEL
    with pytest.raises(ValueError, match="31 days"):
        UsageFilters(
            start=start,
            end=start + timedelta(days=31, microseconds=1),
        )


@pytest.mark.parametrize("group_by", ["model", "provider", "day"])
def test_usage_filter_groupings_are_allow_listed(group_by: str) -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)
    filters = UsageFilters(
        start=start,
        end=start + timedelta(days=1),
        group_by=cast(UsageGroupBy, group_by),
    )

    assert filters.group_by is UsageGroupBy(group_by)


def test_usage_filters_reject_invalid_order_naive_datetimes_and_grouping() -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="earlier"):
        UsageFilters(start=start, end=start)
    with pytest.raises(ValueError, match="aware datetime"):
        UsageFilters(start=datetime(2026, 11, 1), end=start)
    with pytest.raises(ValueError):
        UsageFilters(
            start=start,
            end=start + timedelta(days=1),
            group_by=cast(UsageGroupBy, "raw_payload"),
        )
