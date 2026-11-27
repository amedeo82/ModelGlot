"""Version 6: durable provider usage and Code context provenance."""

import sqlite3


def upgrade(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            execution_id TEXT,
            attempt INTEGER CHECK (attempt IS NULL OR attempt > 0),
            record_kind TEXT NOT NULL DEFAULT 'final'
                CHECK (record_kind IN ('final', 'attempt')),
            provider_id TEXT,
            gateway_model TEXT,
            provider_model TEXT,
            wire_api TEXT NOT NULL
                CHECK (wire_api IN ('messages', 'responses', 'chat', 'gemini')),
            outcome TEXT NOT NULL
                CHECK (outcome IN ('success', 'failure', 'cancelled')),
            status_code INTEGER
                CHECK (status_code IS NULL OR status_code BETWEEN 100 AND 599),
            duration_ms REAL CHECK (duration_ms IS NULL OR duration_ms >= 0),
            failure_category TEXT,
            input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
            cache_read_tokens INTEGER
                CHECK (cache_read_tokens IS NULL OR cache_read_tokens >= 0),
            cache_creation_tokens INTEGER
                CHECK (cache_creation_tokens IS NULL OR cache_creation_tokens >= 0),
            input_total_tokens INTEGER
                CHECK (input_total_tokens IS NULL OR input_total_tokens >= 0),
            output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
            reasoning_tokens INTEGER
                CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
            total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
            estimated_input_tokens INTEGER
                CHECK (estimated_input_tokens IS NULL OR estimated_input_tokens >= 0),
            created_at INTEGER NOT NULL CHECK (created_at >= 0),
            CHECK (
                record_kind = 'final'
                OR (execution_id IS NOT NULL AND attempt IS NOT NULL)
            )
        )
    """)
    connection.execute("""
        CREATE UNIQUE INDEX usage_events_final_request
        ON usage_events(request_id) WHERE record_kind = 'final'
    """)
    connection.execute("""
        CREATE UNIQUE INDEX usage_events_attempt_identity
        ON usage_events(execution_id, attempt, record_kind)
        WHERE record_kind = 'attempt'
    """)
    connection.execute(
        "CREATE INDEX usage_events_created_at ON usage_events(created_at, id)"
    )
    connection.execute("""
        CREATE INDEX usage_events_provider_model
        ON usage_events(provider_id, provider_model, created_at, id)
    """)
    connection.execute("""
        CREATE INDEX usage_events_gateway_model
        ON usage_events(gateway_model, created_at, id)
    """)
    connection.execute("ALTER TABLE code_sessions ADD COLUMN context_model TEXT")
    connection.execute(
        "ALTER TABLE code_sessions ADD COLUMN context_sampled_at INTEGER "
        "CHECK(context_sampled_at IS NULL OR context_sampled_at >= 0)"
    )
