from datetime import UTC, datetime, timedelta

import pytest

from modelglot.application.usage_events import (
    CanonicalUsage,
    RequestUsageRecord,
    UsageFilters,
    UsageGroupBy,
    UsageObservation,
    UsageProtocol,
)
from modelglot.runtime.usage_events import InMemoryUsageEventStore
from tests.wire_payload import (
    array_payload,
    int_payload,
    object_payload,
    string_payload,
)

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


def record(
    request_id: str = "request-1",
    *,
    created_at: datetime = NOW,
    outcome: str = "success",
    usage: CanonicalUsage | None = None,
    provider_id: str = "provider-a",
    gateway_model: str = "gateway-a",
    provider_model: str = "model-a",
    duration_ms: float | None = 100.0,
) -> RequestUsageRecord:
    return RequestUsageRecord(
        request_id=request_id,
        wire_api="chat",
        outcome=outcome,
        created_at=created_at,
        execution_id=f"execution-{request_id}",
        attempt=1,
        protocol=UsageProtocol.OPENAI_CHAT,
        usage=usage or CanonicalUsage(),
        provider_id=provider_id,
        gateway_model=gateway_model,
        provider_model=provider_model,
        status_code=200 if outcome == "success" else 503,
        duration_ms=duration_ms,
    )


def attempt(
    execution_id: str = "execution-request-1",
    number: int = 1,
    *,
    outcome: str = "succeeded",
    created_at: datetime = NOW,
    usage: CanonicalUsage | None = None,
) -> UsageObservation:
    return UsageObservation(
        request_id="request-1",
        execution_id=execution_id,
        attempt=number,
        protocol=UsageProtocol.OPENAI_CHAT,
        usage=usage or CanonicalUsage(),
        created_at=created_at,
        provider_id="provider-a",
        gateway_model="gateway-a",
        provider_model="model-a",
        outcome=outcome,
    )


def filters(group_by: UsageGroupBy = UsageGroupBy.MODEL) -> UsageFilters:
    return UsageFilters(
        start=NOW - timedelta(days=7),
        end=NOW + timedelta(days=1),
        group_by=group_by,
    )


@pytest.mark.asyncio
async def test_memory_aggregates_requests_attempts_null_zero_and_duration():
    store = InMemoryUsageEventStore(clock=lambda: NOW)
    await store.record_usage(
        record(
            usage=CanonicalUsage(
                input_total_tokens=10,
                output_tokens=5,
                total_tokens=15,
                estimated_input_tokens=12,
            )
        ),
        (
            attempt(number=1, outcome="failed"),
            attempt(
                number=2,
                usage=CanonicalUsage(input_total_tokens=10, output_tokens=5),
            ),
        ),
    )
    await store.record_usage(
        record("request-2", usage=CanonicalUsage(output_tokens=0)),
        (),
    )
    await store.record_usage(record("request-3", outcome="failure"), ())
    await store.record_usage(record("request-4", duration_ms=None), ())

    result = await store.usage(filters())

    payload = result.payload
    assert payload["storage"] == "memory"
    notices = array_payload(payload["notices"])
    assert "resets on server restart" in string_payload(notices[0])
    row = object_payload(array_payload(payload["rows"])[0])
    assert row["request_count"] == 4
    assert row["successful_count"] == 3
    assert row["failed_count"] == 1
    assert row["physical_attempt_count"] == 2
    assert row["failed_attempt_count"] == 1
    assert row["input_total_tokens"] == 10
    assert row["output_tokens"] == 5
    assert row["total_tokens"] == 15
    assert row["reasoning_tokens"] is None
    reported_counts = object_payload(row["reported_counts"])
    assert reported_counts["output_tokens"] == 2
    assert reported_counts["reasoning_tokens"] == 0
    assert row["estimated_input_tokens"] == 12
    assert row["token_basis"] == "provider_reported"
    assert row["estimated_basis"] == "estimated"
    assert object_payload(row["duration_ms"]) == {
        "average": 100.0,
        "maximum": 100.0,
        "reported_count": 3,
    }
    assert len(result.request_samples) == 1


@pytest.mark.asyncio
async def test_memory_duplicate_and_conflicting_delivery_never_double_counts():
    store = InMemoryUsageEventStore(clock=lambda: NOW)
    original = record(usage=CanonicalUsage(output_tokens=4))
    await store.record_usage(original, (attempt(),))
    await store.record_usage(original, (attempt(),))
    await store.record_usage(
        record(usage=CanonicalUsage(output_tokens=99)), (attempt(),)
    )

    result = await store.usage(filters())
    row = object_payload(array_payload(result.payload["rows"])[0])
    assert row["request_count"] == 1
    assert row["output_tokens"] == 4
    assert row["physical_attempt_count"] == 1


@pytest.mark.asyncio
async def test_memory_day_provider_filters_order_and_retention():
    store = InMemoryUsageEventStore(clock=lambda: NOW, retention_days=30)
    await store.record_usage(record("old", created_at=NOW - timedelta(days=31)), ())
    await store.record_usage(record("day-2", created_at=NOW - timedelta(days=1)), ())
    await store.record_usage(
        record(
            "other-provider",
            provider_id="provider-b",
            provider_model="shared-model",
        ),
        (),
    )

    day_result = await store.usage(filters(UsageGroupBy.DAY))
    day_rows = [
        object_payload(row) for row in array_payload(day_result.payload["rows"])
    ]
    assert [string_payload(row["day"]) for row in day_rows] == [
        "2026-11-17",
        "2026-11-18",
    ]
    day_notices = array_payload(day_result.payload["notices"])
    assert "UTC" in string_payload(day_notices[1])
    provider_result = await store.usage(filters(UsageGroupBy.PROVIDER))
    provider_rows = [
        object_payload(row) for row in array_payload(provider_result.payload["rows"])
    ]
    assert [string_payload(row["provider_id"]) for row in provider_rows] == [
        "provider-a",
        "provider-b",
    ]
    filtered = await store.usage(
        UsageFilters(
            start=NOW - timedelta(days=7),
            end=NOW + timedelta(days=1),
            provider_id="provider-b",
        )
    )
    filtered_row = object_payload(array_payload(filtered.payload["rows"])[0])
    assert filtered_row["request_count"] == 1


@pytest.mark.asyncio
async def test_memory_bound_and_close():
    store = InMemoryUsageEventStore(clock=lambda: NOW, max_records=2, retention_batch=1)
    for index in range(4):
        await store.record_usage(record(f"request-{index}"), ())
    result = await store.usage(filters())
    rows = [object_payload(row) for row in array_payload(result.payload["rows"])]
    assert sum(int_payload(row["request_count"]) for row in rows) == 2
    await store.close()
    with pytest.raises(RuntimeError, match="closed"):
        await store.usage(filters())
