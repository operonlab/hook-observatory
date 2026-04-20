-- SQLite schema for agent-metrics-rs
-- Mirrors PG `agent_metrics` schema (4 PG migrations consolidated):
--   001_init.sql            → dispatch_runs, projects
--   002_rename_schema.sql   → schema rename only (no DDL needed in SQLite)
--   003_session_tables.sql  → sessions, snapshots, daily_summary
--   004_guardian.sql        → guardian_actions
--
-- Type mapping (PG → SQLite):
--   TEXT             → TEXT
--   TIMESTAMPTZ      → TEXT  (ISO-8601 with offset)
--   DATE             → TEXT  (YYYY-MM-DD)
--   BOOLEAN          → INTEGER (0/1)
--   DOUBLE PRECISION → REAL
--   INTEGER          → INTEGER
--   JSONB            → TEXT  (JSON string; sqlx::types::Json on Rust side)

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- dispatch_runs (Maestro multi-CLI dispatch records)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dispatch_runs (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    pattern         TEXT NOT NULL,
    budget          TEXT NOT NULL DEFAULT 'balanced',
    task_summary    TEXT NOT NULL,
    cwd             TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    completed_at    TEXT,
    duration_s      REAL,
    detail          TEXT
);
CREATE INDEX IF NOT EXISTS idx_dispatch_runs_status  ON dispatch_runs(status);
CREATE INDEX IF NOT EXISTS idx_dispatch_runs_started ON dispatch_runs(started_at DESC);

-- ---------------------------------------------------------------------------
-- projects (team-task projects)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    mode        TEXT NOT NULL,
    goal        TEXT,
    workspace   TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    state       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_mode   ON projects(mode);

-- ---------------------------------------------------------------------------
-- sessions (CC reader live session state)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id                    TEXT PRIMARY KEY,
    sid                   TEXT NOT NULL,
    cli                   TEXT NOT NULL DEFAULT 'claude',
    model_id              TEXT NOT NULL DEFAULT '',
    model_display         TEXT NOT NULL DEFAULT '',
    project               TEXT NOT NULL DEFAULT '',
    cost_usd              REAL    NOT NULL DEFAULT 0,
    context_used_pct      REAL    NOT NULL DEFAULT 0,
    context_window_size   INTEGER NOT NULL DEFAULT 0,
    input_tokens          INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    first_seen            TEXT NOT NULL,
    last_seen             TEXT NOT NULL,
    is_active             INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_am_sessions_last_seen ON sessions(last_seen);
CREATE INDEX IF NOT EXISTS idx_am_sessions_active    ON sessions(is_active, last_seen);

-- ---------------------------------------------------------------------------
-- snapshots (per-session per-tick snapshots)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS snapshots (
    id               TEXT PRIMARY KEY,
    ts               TEXT NOT NULL,
    session_id       TEXT NOT NULL,
    sid              TEXT NOT NULL,
    cli              TEXT NOT NULL DEFAULT 'claude',
    cost_usd         REAL    NOT NULL DEFAULT 0,
    context_used_pct REAL    NOT NULL DEFAULT 0,
    input_tokens     INTEGER NOT NULL DEFAULT 0,
    output_tokens    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_am_snapshots_ts ON snapshots(ts);

-- ---------------------------------------------------------------------------
-- daily_summary (one row per UTC day)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_summary (
    id                  TEXT PRIMARY KEY,
    date                TEXT NOT NULL UNIQUE,
    total_cost_usd      REAL    NOT NULL DEFAULT 0,
    total_sessions      INTEGER NOT NULL DEFAULT 0,
    peak_concurrent     INTEGER NOT NULL DEFAULT 0,
    total_input_tokens  INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    avg_context_pct     REAL    NOT NULL DEFAULT 0,
    max_context_pct     REAL    NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- guardian_actions (Guardian + Sweep action log)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS guardian_actions (
    id            TEXT PRIMARY KEY,
    ts            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    level         TEXT NOT NULL,
    priority      TEXT NOT NULL,
    pid           INTEGER,
    process_name  TEXT,
    mem_mb        REAL,
    cpu_pct       REAL,
    action        TEXT NOT NULL,
    result        TEXT NOT NULL,
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_guardian_ts    ON guardian_actions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_guardian_level ON guardian_actions(level);
