-- AgentOps schema — multi-CLI dispatch runs + team-task projects
-- Applied manually: psql -h localhost -U joneshong -d workshop -f 001_init.sql

CREATE SCHEMA IF NOT EXISTS agentops;

-- Maestro dispatch runs (hybrid: core columns + JSONB detail)
CREATE TABLE IF NOT EXISTS agentops.dispatch_runs (
    id              TEXT PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    pattern         TEXT NOT NULL,
    budget          TEXT NOT NULL DEFAULT 'balanced',
    task_summary    TEXT NOT NULL,
    cwd             TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    duration_s      DOUBLE PRECISION,
    detail          JSONB
);

CREATE INDEX IF NOT EXISTS idx_dispatch_runs_status
    ON agentops.dispatch_runs(status);
CREATE INDEX IF NOT EXISTS idx_dispatch_runs_started
    ON agentops.dispatch_runs(started_at DESC);

-- Team-task projects (hybrid: core columns + JSONB state)
CREATE TABLE IF NOT EXISTS agentops.projects (
    id              TEXT PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    mode            TEXT NOT NULL,
    goal            TEXT,
    workspace       TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    state           JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_status
    ON agentops.projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_mode
    ON agentops.projects(mode);
