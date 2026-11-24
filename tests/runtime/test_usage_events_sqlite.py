import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from free_claude_code.application.usage_events import (
    CanonicalUsage,
    RequestUsageRecord,
    UsageFilters,
    UsageObservation,
    UsageProtocol,
)
from free_claude_code.runtime.sqlite_database import query_rows, required_column
from free_claude_code.runtime.usage_events_sqlite import (
    SQLiteUsageEventStore,
    UsageConflictError,
)
from tests.fixture_types import DatabaseFactory
from tests.wire_payload import array_payload, object_payload, string_payload

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


def record(
    request_id: str = "request-1",
    *,
    created_at: datetime = NOW,
    output: int = 7,
) -> RequestUsageRecord:
    return RequestUsageRecord(
        request_id=request_id,
        wire_api="chat",
        outcome="success",
        created_at=created_at,
        execution_id=f"execution-{request_id}",
        attempt=1,
        protocol=UsageProtocol.OPENAI_CHAT,
        usage=CanonicalUsage(
            input_total_tokens=10,
            output_tokens=output,
            total_tokens=10 + output,
            estimated_input_tokens=12,
        ),
        provider_id="provider-a",
        gateway_model="gateway-a",
        provider_model="model-a",
        status_code=200,
        duration_ms=25.0,
    )


def attempt(number: int = 1, *, outcome: str = "succeeded") -> UsageObservation:
    return UsageObservation(
        request_id="request-1",
        execution_id="execution-request-1",
        attempt=number,
        protocol=UsageProtocol.OPENAI_CHAT,
        usage=CanonicalUsage(input_total_tokens=10, output_tokens=7),
        created_at=NOW,
        provider_id="provider-a",
        gateway_model="gateway-a",
        provider_model="model-a",
        outcome=outcome,
    )


def filters() -> UsageFilters:
    return UsageFilters(start=NOW - timedelta(days=1), end=NOW + timedelta(days=1))


@pytest.mark.asyncio
async def test_sqlite_insert_duplicate_conflict_and_null_handling(
    database_factory: DatabaseFactory, tmp_path: Path
) -> None:
    database = database_factory(tmp_path / "usage.db", tmp_path / "usage.lock")
    store = SQLiteUsageEventStore(database, clock=lambda: NOW)
    await store.start()
    original = record()
    await store.record_usage(original, (attempt(1, outcome="failed"), attempt(2)))
    await store.record_usage(original, (attempt(1, outcome="failed"), attempt(2)))
    with pytest.raises(UsageConflictError):
        await store.record_usage(record(output=99), ())

    result = await store.usage(filters())
    assert result.payload["storage"] == "sqlite"
    row = object_payload(array_payload(result.payload["rows"])[0])
    assert row["request_count"] == 1
    assert row["output_tokens"] == 7
    assert row["physical_attempt_count"] == 2
    assert row["failed_attempt_count"] == 1
    assert row["reasoning_tokens"] is None
    reported_counts = object_payload(row["reported_counts"])
    assert reported_counts["reasoning_tokens"] == 0

    def usage_event_columns(connection: sqlite3.Connection) -> tuple[str, ...]:
        rows = query_rows(connection, "PRAGMA table_info(usage_events)").fetchall()
        return tuple(required_column(row, 1, str) for row in rows)

    columns = await database.run(usage_event_columns, write=False)
    assert not {"prompt", "completion", "raw", "payload", "path"}.intersection(columns)


@pytest.mark.asyncio
async def test_sqlite_retention_and_restart_persistence(
    database_factory: DatabaseFactory, tmp_path: Path
) -> None:
    path = tmp_path / "usage.db"
    lock = tmp_path / "usage.lock"
    database = database_factory(path, lock)
    store = SQLiteUsageEventStore(
        database, clock=lambda: NOW, retention_days=30, max_rows=2, retention_batch=1
    )
    await store.start()
    await store.record_usage(record("old", created_at=NOW - timedelta(days=31)), ())
    await store.record_usage(record("kept"), ())
    await store.record_usage(record("new"), ())
    await database.close()

    reopened = database_factory(path, lock)
    restarted = SQLiteUsageEventStore(reopened, clock=lambda: NOW)
    await restarted.start()
    result = await restarted.usage(filters())
    row = object_payload(array_payload(result.payload["rows"])[0])
    assert row["request_count"] == 2
    assert result.payload["retention_days"] == 30
    assert string_payload(result.payload["coverage_start"]).startswith("2026-11-17")


@pytest.mark.asyncio
async def test_sqlite_code_context_is_metadata_only(
    database_factory: DatabaseFactory, tmp_path: Path
) -> None:
    database = database_factory(tmp_path / "usage.db", tmp_path / "usage.lock")
    store = SQLiteUsageEventStore(database, clock=lambda: NOW)
    await store.start()

    def insert_context(connection: sqlite3.Connection) -> None:
        connection.execute(
            "INSERT INTO code_sessions ("
            "id,cwd,model,reasoning_effort,harness,title,title_search,cwd_search,"
            "auto_title,native_may_have_input,revision,status,created_at,updated_at,"
            "mode,native_permission_defaults,context_used_tokens,context_model,context_sampled_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "session",
                "C:/private/worktree",
                "provider/model",
                None,
                "codex",
                "title",
                "title",
                "cwd",
                0,
                0,
                1,
                "ready",
                1,
                1,
                "config",
                None,
                42,
                "provider/model",
                1000,
            ),
        )

    await database.run(insert_context, write=True)
    result = await store.usage(filters())
    assert len(result.code_samples) == 1
    sample = result.code_samples[0]
    assert sample.context_used_tokens == 42
    assert sample.context_model == "provider/model"
    assert sample.context_sampled_at == datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)
    assert "worktree" not in str(result.payload)


@pytest.mark.asyncio
async def test_sqlite_read_deadline_interrupts_slow_sql_and_restores_connection(
    database_factory: DatabaseFactory, tmp_path: Path
) -> None:
    database = database_factory(tmp_path / "usage.db", tmp_path / "usage.lock")
    await database.start()

    def slow_query(connection: sqlite3.Connection) -> None:
        query_rows(
            connection,
            "WITH RECURSIVE counter(value) AS ("
            "SELECT 0 UNION ALL SELECT value + 1 FROM counter LIMIT 100000000"
            ") SELECT sum(value) FROM counter",
        ).fetchone()

    with pytest.raises(sqlite3.OperationalError, match="interrupt"):
        await database.run_read(slow_query, timeout_seconds=0.001)

    def read_value(connection: sqlite3.Connection) -> int:
        row = query_rows(connection, "SELECT 42 AS value").fetchone()
        assert row is not None
        return required_column(row, "value", int)

    value = await database.run_read(read_value, timeout_seconds=1)
    assert value == 42
