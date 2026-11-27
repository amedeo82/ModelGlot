"""Bounded in-memory usage collection and shared aggregate semantics."""

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from modelglot.application.usage_events import (
    RequestUsageRecord,
    UsageFilters,
    UsageGroupBy,
    UsageObservation,
)
from modelglot.core.json_types import JsonObject

TOKEN_FIELDS = (
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "input_total_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)
DAY_MS = 86_400_000

type UsageGroupKey = tuple[str | None, str | None, str | None, str | None]


@dataclass(slots=True)
class _UsageGroup:
    records: list[RequestUsageRecord]
    attempts: list[UsageObservation]


@dataclass(frozen=True, slots=True)
class CodeContextSample:
    context_model: str | None
    context_used_tokens: int | None
    context_sampled_at: datetime | None


@dataclass(frozen=True, slots=True)
class UsageQueryResult:
    payload: JsonObject
    request_samples: tuple[RequestUsageRecord, ...]
    code_samples: tuple[CodeContextSample, ...] = ()


def timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def build_usage_query(
    records: Iterable[RequestUsageRecord],
    attempts: Iterable[UsageObservation],
    filters: UsageFilters,
    *,
    storage: str,
    generated_at: datetime,
    retention_days: int,
    code_samples: tuple[CodeContextSample, ...] = (),
) -> UsageQueryResult:
    """Aggregate one materialized snapshot without conflating attempts/requests."""

    generated_at = generated_at.astimezone(UTC)
    cutoff = generated_at - timedelta(days=retention_days)
    retained_records = tuple(
        record
        for record in records
        if filters.matches(record) and record.created_at >= cutoff
    )
    retained_attempts = tuple(
        attempt
        for attempt in attempts
        if filters.matches(attempt) and attempt.created_at >= cutoff
    )
    groups: dict[UsageGroupKey, _UsageGroup] = {}

    def group_for(
        event: RequestUsageRecord | UsageObservation,
    ) -> UsageGroupKey:
        day = event.created_at.astimezone(UTC).date().isoformat()
        if filters.group_by is UsageGroupBy.MODEL:
            return event.provider_id, event.gateway_model, event.provider_model, None
        if filters.group_by is UsageGroupBy.PROVIDER:
            return event.provider_id, None, None, None
        return None, None, None, day

    def group(key: UsageGroupKey) -> _UsageGroup:
        if key not in groups:
            groups[key] = _UsageGroup(records=[], attempts=[])
        return groups[key]

    for record in retained_records:
        group(group_for(record)).records.append(record)
    for attempt in retained_attempts:
        group(group_for(attempt)).attempts.append(attempt)

    rows = [
        _aggregate_row(key, values.records, values.attempts, filters.group_by)
        for key, values in groups.items()
    ]
    rows.sort(key=_row_order)
    latest: dict[tuple[str | None, str | None, str | None], RequestUsageRecord] = {}
    for record in retained_records:
        if record.outcome != "success" or record.usage.input_total_tokens is None:
            continue
        key = (record.provider_id, record.gateway_model, record.provider_model)
        previous = latest.get(key)
        if previous is None or record.created_at > previous.created_at:
            latest[key] = record
    request_samples = tuple(
        sorted(
            latest.values(),
            key=lambda record: (
                record.provider_id or "",
                record.gateway_model or "",
                record.provider_model or "",
            ),
        )[:1000]
    )
    oldest = min((record.created_at for record in retained_records), default=None)
    newest = max((record.created_at for record in retained_records), default=None)
    notices: list[str] = []
    if storage == "memory":
        notices.append("Usage is process-local and resets on server restart.")
    if filters.group_by is UsageGroupBy.DAY:
        notices.append("Daily buckets use UTC; the current day is partial.")
    coverage_end = min(filters.end, generated_at)
    coverage_start = min(max(filters.start, cutoff), coverage_end)
    payload: JsonObject = {
        "schema_version": 1,
        "generated_at": timestamp(generated_at),
        "coverage_start": timestamp(coverage_start),
        "coverage_end": timestamp(coverage_end),
        "oldest_event_at": timestamp(oldest) if oldest else None,
        "newest_event_at": timestamp(newest) if newest else None,
        "retention_days": retention_days,
        "storage": storage,
        "group_by": filters.group_by.value,
        "rows": rows[:5000],
        "truncated": len(rows) > 5000,
        "context": {
            "request_input": {"rows": []},
            "code_session_current": {"rows": []},
        },
        "notices": notices,
    }
    return UsageQueryResult(payload, request_samples, code_samples)


def _aggregate_row(
    key: UsageGroupKey,
    records: list[RequestUsageRecord],
    attempts: list[UsageObservation],
    group_by: UsageGroupBy,
) -> JsonObject:
    provider_id, gateway_model, provider_model, day = key
    successful = [record for record in records if record.outcome == "success"]
    reported_counts = {
        field: sum(getattr(record.usage, field) is not None for record in successful)
        for field in TOKEN_FIELDS
    }
    token_sums = {
        field: _nullable_sum(getattr(record.usage, field) for record in successful)
        for field in TOKEN_FIELDS
    }
    durations = [
        record.duration_ms for record in records if record.duration_ms is not None
    ]
    return {
        "day": day if group_by is UsageGroupBy.DAY else None,
        "provider_id": provider_id,
        "gateway_model": gateway_model,
        "provider_model": provider_model,
        "request_count": len(records),
        "successful_count": sum(record.outcome == "success" for record in records),
        "failed_count": sum(record.outcome == "failure" for record in records),
        "cancelled_count": sum(record.outcome == "cancelled" for record in records),
        "physical_attempt_count": len(attempts),
        "failed_attempt_count": sum(
            attempt.outcome != "succeeded" for attempt in attempts
        ),
        **token_sums,
        "estimated_input_tokens": _nullable_sum(
            record.usage.estimated_input_tokens for record in successful
        ),
        "reported_counts": {
            **reported_counts,
            "estimated_input_tokens": sum(
                record.usage.estimated_input_tokens is not None for record in successful
            ),
        },
        "token_basis": "provider_reported",
        "estimated_basis": "estimated",
        "duration_ms": {
            "average": round(sum(durations) / len(durations), 2) if durations else None,
            "maximum": max(durations) if durations else None,
            "reported_count": len(durations),
        },
    }


def _nullable_sum(values: Iterable[int | None]) -> int | None:
    materialized = [value for value in values if value is not None]
    return sum(materialized) if materialized else None


def _row_order(row: JsonObject):
    return (
        row["day"] or "",
        row["provider_id"] or "",
        row["gateway_model"] or "",
        row["provider_model"] or "",
    )


class UsageEventStore(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def record_usage(
        self,
        record: RequestUsageRecord,
        attempts: tuple[UsageObservation, ...],
    ) -> None: ...

    async def usage(self, filters: UsageFilters) -> UsageQueryResult: ...

    async def enforce_retention(self) -> None: ...


class InMemoryUsageEventStore:
    """Process-local Wave 2 store with the durable store's public contract."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_records: int = 10_000,
        retention_days: int = 30,
        retention_batch: int = 1000,
    ) -> None:
        if max_records <= 0 or retention_days <= 0 or retention_batch <= 0:
            raise ValueError("usage store bounds must be positive")
        self._clock = clock
        self._max_records = max_records
        self._retention_days = retention_days
        self._retention_batch = retention_batch
        self._records: dict[str, RequestUsageRecord] = {}
        self._attempts: dict[tuple[str, int], UsageObservation] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("usage store is closed")
        await self.enforce_retention()

    async def close(self) -> None:
        self._closed = True

    async def record_usage(
        self,
        record: RequestUsageRecord,
        attempts: tuple[UsageObservation, ...],
    ) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("usage store is closed")
            existing = self._records.get(record.request_id)
            if existing is None:
                self._records[record.request_id] = record
            for attempt in attempts:
                self._attempts.setdefault(
                    (attempt.execution_id, attempt.attempt), attempt
                )
            self._enforce_retention_sync()

    async def usage(self, filters: UsageFilters) -> UsageQueryResult:
        async with self._lock:
            if self._closed:
                raise RuntimeError("usage store is closed")
            return build_usage_query(
                self._records.values(),
                self._attempts.values(),
                filters,
                storage="memory",
                generated_at=self._clock(),
                retention_days=self._retention_days,
            )

    async def enforce_retention(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._enforce_retention_sync()

    def _enforce_retention_sync(self) -> None:
        cutoff = self._clock() - timedelta(days=self._retention_days)
        for key, record in tuple(self._records.items()):
            if record.created_at < cutoff:
                del self._records[key]
        for key, attempt in tuple(self._attempts.items()):
            if attempt.created_at < cutoff:
                del self._attempts[key]
        overflow = len(self._records) + len(self._attempts) - self._max_records
        if overflow <= 0:
            return
        events = [
            (record.created_at, "final", key) for key, record in self._records.items()
        ] + [
            (attempt.created_at, "attempt", key)
            for key, attempt in self._attempts.items()
        ]
        events.sort(key=lambda event: (event[0], event[1], str(event[2])))
        for _, kind, key in events[: min(overflow, self._retention_batch)]:
            if kind == "final" and isinstance(key, str):
                self._records.pop(key, None)
            elif isinstance(key, tuple):
                self._attempts.pop(key, None)
