-- Session tracking tables (ported from V1 pulso_agent_metrics)
-- Applied manually: psql -h localhost -U joneshong -d workshop -f 003_session_tables.sql
-- Prerequisite: 002_rename_schema.sql (schema is now agent_metrics)

CREATE TABLE IF NOT EXISTS agent_metrics.sessions (
    id                    TEXT PRIMARY KEY,
    sid                   TEXT NOT NULL,
    cli                   TEXT NOT NULL DEFAULT 'claude',
    model_id              TEXT NOT NULL DEFAULT '',
    model_display         TEXT NOT NULL DEFAULT '',
    project               TEXT NOT NULL DEFAULT '',
    cost_usd              DOUBLE PRECISION NOT NULL DEFAULT 0,
    context_used_pct      DOUBLE PRECISION NOT NULL DEFAULT 0,
    context_window_size   INTEGER NOT NULL DEFAULT 0,
    input_tokens          INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    first_seen            TIMESTAMPTZ NOT NULL,
    last_seen             TIMESTAMPTZ NOT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_am_sessions_last_seen ON agent_metrics.sessions(last_seen);
CREATE INDEX IF NOT EXISTS idx_am_sessions_active ON agent_metrics.sessions(is_active, last_seen);

CREATE TABLE IF NOT EXISTS agent_metrics.snapshots (
    id               TEXT PRIMARY KEY,
    ts               TIMESTAMPTZ NOT NULL,
    session_id       TEXT NOT NULL,
    sid              TEXT NOT NULL,
    cli              TEXT NOT NULL DEFAULT 'claude',
    cost_usd         DOUBLE PRECISION NOT NULL DEFAULT 0,
    context_used_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    input_tokens     INTEGER NOT NULL DEFAULT 0,
    output_tokens    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_am_snapshots_ts ON agent_metrics.snapshots(ts);

CREATE TABLE IF NOT EXISTS agent_metrics.daily_summary (
    id                  TEXT PRIMARY KEY,
    date                DATE NOT NULL UNIQUE,
    total_cost_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_sessions      INTEGER NOT NULL DEFAULT 0,
    peak_concurrent     INTEGER NOT NULL DEFAULT 0,
    total_input_tokens  INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    avg_context_pct     DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_context_pct     DOUBLE PRECISION NOT NULL DEFAULT 0
);
