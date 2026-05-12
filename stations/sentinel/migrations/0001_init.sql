-- Sentinel SQLite schema v1
-- Pragmas are set programmatically at pool connect time (db.rs)

CREATE TABLE IF NOT EXISTS health_checks (
    id          TEXT PRIMARY KEY,
    service     TEXT NOT NULL,
    check_type  TEXT NOT NULL,
    status      TEXT NOT NULL,
    response_ms REAL,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_hc_service_created ON health_checks(service, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hc_created ON health_checks(created_at);
CREATE INDEX IF NOT EXISTS idx_hc_status ON health_checks(status);

CREATE TABLE IF NOT EXISTS incidents (
    id            TEXT PRIMARY KEY,
    service       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'investigating',
    severity      TEXT NOT NULL DEFAULT 'minor',
    title         TEXT NOT NULL,
    detail        TEXT,
    diagnosis     TEXT,
    repair_result TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_inc_service ON incidents(service);
CREATE INDEX IF NOT EXISTS idx_inc_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_inc_created ON incidents(created_at DESC);

CREATE TABLE IF NOT EXISTS active_operations (
    id                 TEXT PRIMARY KEY,
    service            TEXT NOT NULL,
    action             TEXT NOT NULL,
    agent_id           TEXT NOT NULL,
    pid                INTEGER,
    estimated_duration INTEGER NOT NULL DEFAULT 300,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at        TEXT,
    result             TEXT
);
CREATE INDEX IF NOT EXISTS idx_ao_service ON active_operations(service);
CREATE INDEX IF NOT EXISTS idx_ao_agent ON active_operations(agent_id);
CREATE INDEX IF NOT EXISTS idx_ao_open ON active_operations(resolved_at) WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS subscriptions (
    id         TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    events     TEXT NOT NULL DEFAULT '["*"]',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sub_active ON subscriptions(active) WHERE active = 1;
