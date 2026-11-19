"""SQLite-backed durable usage metadata on FCC's shared database owner."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from free_claude_code.application.usage_events import (
    CanonicalUsage,
    RequestUsageRecord,
    UsageFilters,
    UsageObservation,
    usage_protocol,
)

from .sqlite_database import SQLiteDatabase
from .usage_events import (
    CodeContextSample,
    UsageQueryResult,
    build_usage_query,
)

_COLUMNS = (
    "request_id",
    "execution_id",
    "attempt",
    "record_kind",
    "provider_id",
    "gateway_model",
    "provider_model",
    "wire_api",
    "outcome",
    "status_code",
    "duration_ms",
    "failure_category",
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "input_total_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "estimated_input_tokens",
    "created_at",
)
_SELECT_COLUMNS = ", ".join(_COLUMNS)
_PLACEHOLDERS = ", ".join("?" for _ in _COLUMNS)
_PROTOCOL_TO_WIRE = {
    "anthropic_messages": "messages",
    "openai_chat": "chat",
    "openai_responses": "responses",
    "gemini": "gemini",
}
_ATTEMPT_OUTCOMES = {
    "succeeded": "success",
    "failed": "failure",
    "cancelled": "cancelled",
}


class UsageConflictError(ValueError):
    """The same idempotency key arrived with different canonical metadata."""


def _epoch_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _from_epoch_ms(value: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)


def _values(
    event: RequestUsageRecord | UsageObservation, record_kind: str
) -> tuple[object, ...]:
    if isinstance(event, RequestUsageRecord):
        usage = event.usage
        return (
            event.request_id,
            event.execution_id,
            event.attempt,
            record_kind,
            event.provider_id,
            event.gateway_model,
            event.provider_model,
            event.wire_api,
            event.outcome,
            event.status_code,
            event.duration_ms,
            event.failure_category,
            usage.input_tokens,
            usage.cache_read_tokens,
            usage.cache_creation_tokens,
            usage.input_total_tokens,
            usage.output_tokens,
            usage.reasoning_tokens,
            usage.total_tokens,
            usage.estimated_input_tokens,
            _epoch_ms(event.created_at),
        )
    usage = event.usage
    return (
        event.request_id,
        event.execution_id,
        event.attempt,
        record_kind,
        event.provider_id,
        event.gateway_model,
        event.provider_model,
        _PROTOCOL_TO_WIRE[event.protocol.value],
        _ATTEMPT_OUTCOMES[event.outcome],
        None,
        None,
        None,
        usage.input_tokens,
        usage.cache_read_tokens,
        usage.cache_creation_tokens,
        usage.input_total_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
        usage.total_tokens,
        usage.estimated_input_tokens,
        _epoch_ms(event.created_at),
    )


def _usage(row: sqlite3.Row) -> CanonicalUsage:
    return CanonicalUsage(
        input_tokens=row["input_tokens"],
        cache_read_tokens=row["cache_read_tokens"],
        cache_creation_tokens=row["cache_creation_tokens"],
        input_total_tokens=row["input_total_tokens"],
        output_tokens=row["output_tokens"],
        reasoning_tokens=row["reasoning_tokens"],
        total_tokens=row["total_tokens"],
        estimated_input_tokens=row["estimated_input_tokens"],
    )


def _record(row: sqlite3.Row) -> RequestUsageRecord:
    return RequestUsageRecord(
        request_id=row["request_id"],
        wire_api=row["wire_api"],
        outcome=row["outcome"],
        created_at=_from_epoch_ms(row["created_at"]),
        execution_id=row["execution_id"],
        attempt=row["attempt"],
        usage=_usage(row),
        provider_id=row["provider_id"],
        gateway_model=row["gateway_model"],
        provider_model=row["provider_model"],
        status_code=row["status_code"],
        duration_ms=row["duration_ms"],
        failure_category=row["failure_category"],
    )


def _attempt(row: sqlite3.Row) -> UsageObservation:
    outcome = {
        "success": "succeeded",
        "failure": "failed",
        "cancelled": "cancelled",
    }[row["outcome"]]
    return UsageObservation(
        request_id=row["request_id"],
        execution_id=row["execution_id"],
        attempt=row["attempt"],
        protocol=usage_protocol(row["wire_api"]),
        usage=_usage(row),
        created_at=_from_epoch_ms(row["created_at"]),
        provider_id=row["provider_id"],
        gateway_model=row["gateway_model"],
        provider_model=row["provider_model"],
        outcome=outcome,
    )


def _insert_idempotent(
    connection: sqlite3.Connection,
    event: RequestUsageRecord | UsageObservation,
    *,
    record_kind: str,
) -> None:
    values = _values(event, record_kind)
    cursor = connection.execute(
        f"INSERT OR IGNORE INTO usage_events ({_SELECT_COLUMNS}) VALUES ({_PLACEHOLDERS})",
        values,
    )
    if cursor.rowcount:
        return
    if record_kind == "final":
        where = "request_id = ? AND record_kind = 'final'"
        identity = (event.request_id,)
    else:
        where = "execution_id = ? AND attempt = ? AND record_kind = 'attempt'"
        identity = (event.execution_id, event.attempt)
    existing = connection.execute(
        f"SELECT {_SELECT_COLUMNS} FROM usage_events WHERE {where}", identity
    ).fetchone()
    if existing is None or tuple(existing) != values:
        raise UsageConflictError("usage event idempotency conflict")


class SQLiteUsageEventStore:
    """Durable metadata repository with bounded retention and idempotent writes."""

    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retention_days: int = 30,
        max_rows: int = 50_000,
        retention_batch: int = 1000,
        query_timeout_seconds: float = 5.0,
    ) -> None:
        if (
            retention_days <= 0
            or max_rows <= 0
            or retention_batch <= 0
            or query_timeout_seconds <= 0
        ):
            raise ValueError("usage store bounds must be positive")
        self._database = database
        self._clock = clock
        self._retention_days = retention_days
        self._max_rows = max_rows
        self._retention_batch = retention_batch
        self._query_timeout_seconds = query_timeout_seconds
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("usage store is closed")
        await self._database.start()
        await self.enforce_retention()

    async def close(self) -> None:
        # The shared SQLiteDatabase has a separate, longer ownership lifetime.
        self._closed = True

    async def record_usage(
        self,
        record: RequestUsageRecord,
        attempts: tuple[UsageObservation, ...],
    ) -> None:
        if self._closed:
            raise RuntimeError("usage store is closed")

        def write(connection: sqlite3.Connection) -> None:
            _insert_idempotent(connection, record, record_kind="final")
            for attempt in attempts:
                _insert_idempotent(connection, attempt, record_kind="attempt")
            self._retention_batch_sync(connection)

        await self._database.run(write, write=True)

    async def usage(self, filters: UsageFilters) -> UsageQueryResult:
        if self._closed:
            raise RuntimeError("usage store is closed")
        generated_at = self._clock().astimezone(UTC)
        cutoff = generated_at - timedelta(days=self._retention_days)
        start = max(filters.start, cutoff)
        clauses = ["created_at >= ?", "created_at < ?"]
        parameters: list[object] = [_epoch_ms(start), _epoch_ms(filters.end)]
        for field in ("provider_id", "gateway_model", "provider_model"):
            value = getattr(filters, field)
            if value is not None:
                clauses.append(f"{field} = ?")
                parameters.append(value)
        where = " AND ".join(clauses)

        def read(connection: sqlite3.Connection):
            final_rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM usage_events "
                f"WHERE record_kind = 'final' AND {where} "
                "ORDER BY created_at, id",
                parameters,
            ).fetchall()
            attempt_rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM usage_events "
                f"WHERE record_kind = 'attempt' AND {where} "
                "ORDER BY created_at, id",
                parameters,
            ).fetchall()
            context_rows = connection.execute(
                "SELECT context_model, context_used_tokens, context_sampled_at "
                "FROM code_sessions WHERE context_used_tokens IS NOT NULL"
            ).fetchall()
            return final_rows, attempt_rows, context_rows

        final_rows, attempt_rows, context_rows = await self._database.run_read(
            read, timeout_seconds=self._query_timeout_seconds
        )
        code_samples = tuple(
            CodeContextSample(
                context_model=row["context_model"],
                context_used_tokens=row["context_used_tokens"],
                context_sampled_at=(
                    _from_epoch_ms(row["context_sampled_at"])
                    if row["context_sampled_at"] is not None
                    else None
                ),
            )
            for row in context_rows
        )
        return build_usage_query(
            (_record(row) for row in final_rows),
            (_attempt(row) for row in attempt_rows),
            filters,
            storage="sqlite",
            generated_at=generated_at,
            retention_days=self._retention_days,
            code_samples=code_samples,
        )

    async def enforce_retention(self) -> None:
        if self._closed:
            return
        # Each transaction is bounded; the cap prevents an unbounded startup loop.
        for _ in range(100):
            deleted = await self._database.run(self._retention_batch_sync, write=True)
            if deleted == 0:
                break

    def _retention_batch_sync(self, connection: sqlite3.Connection) -> int:
        cutoff = _epoch_ms(self._clock() - timedelta(days=self._retention_days))
        cursor = connection.execute(
            "DELETE FROM usage_events WHERE id IN ("
            "SELECT id FROM usage_events WHERE created_at < ? "
            "ORDER BY created_at, id LIMIT ?)",
            (cutoff, self._retention_batch),
        )
        deleted = cursor.rowcount
        count = connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
        overflow = max(0, count - self._max_rows)
        if overflow:
            cursor = connection.execute(
                "DELETE FROM usage_events WHERE id IN ("
                "SELECT id FROM usage_events ORDER BY created_at, id LIMIT ?)",
                (min(overflow, self._retention_batch),),
            )
            deleted += cursor.rowcount
        return deleted
