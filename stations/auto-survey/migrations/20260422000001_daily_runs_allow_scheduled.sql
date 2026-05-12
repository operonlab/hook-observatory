-- Extend daily_runs.status CHECK to include 'scheduled'.
-- src/web.rs create_run() sets status='scheduled' when submitted before
-- execution_hour; the original CHECK only allowed
-- ('pending','running','completed','failed'), so pre-14:00 POSTs returned 500.
-- SQLite can't ALTER a CHECK constraint, so rebuild the table.

PRAGMA foreign_keys = OFF;

CREATE TABLE daily_runs_new (
    id             TEXT    PRIMARY KEY,
    run_date       TEXT    NOT NULL UNIQUE,
    attend_url     TEXT,
    quiz_url       TEXT,
    status         TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'scheduled', 'running', 'completed', 'failed')),
    result_summary TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

INSERT INTO daily_runs_new (id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at)
SELECT id, run_date, attend_url, quiz_url, status, result_summary, created_at, updated_at
FROM daily_runs;

DROP TABLE daily_runs;
ALTER TABLE daily_runs_new RENAME TO daily_runs;

PRAGMA foreign_keys = ON;
