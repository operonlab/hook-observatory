-- Guardian + Sweep action log table
CREATE TABLE IF NOT EXISTS agent_metrics.guardian_actions (
    id TEXT PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    level TEXT NOT NULL,          -- WARN/CRIT/SWEEP
    priority TEXT NOT NULL,       -- P1/P2/P3/SWEEP-*
    pid INTEGER,
    process_name TEXT,
    mem_mb DOUBLE PRECISION,
    cpu_pct DOUBLE PRECISION,
    action TEXT NOT NULL,         -- TERM/SIGTERM/SIGKILL/SKIP/SIGUSR1/SIGCHLD
    result TEXT NOT NULL,         -- success/already_dead/failed/skipped/warn/no_permission
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_guardian_ts ON agent_metrics.guardian_actions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_guardian_level ON agent_metrics.guardian_actions(level);
