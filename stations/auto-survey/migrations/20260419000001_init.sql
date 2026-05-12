-- SQLite schema for auto-survey-rs
-- Mirrors Python PG schema (stations/auto-survey/migrations/001_init.sql)
-- + ORM fields that were missing: submissions.is_pathfinder, submissions.answers_snapshot
-- + daily_runs table (was in ORM but not in PG SQL)
--
-- Type mapping:
--   UUID         → TEXT  (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx, Rust uuid crate default)
--   JSONB        → TEXT  (JSON string)
--   TIMESTAMPTZ  → TEXT  (ISO-8601 with offset, e.g. 2026-04-19T10:30:00+00:00)
--   DATE         → TEXT  (YYYY-MM-DD)
--   BOOLEAN      → INTEGER (0 = false, 1 = true)
--   INTEGER      → INTEGER
--   TEXT         → TEXT

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- surveys
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS surveys (
    id           TEXT    PRIMARY KEY,                 -- UUID TEXT
    url          TEXT    NOT NULL,
    url_hash     TEXT    NOT NULL UNIQUE,             -- SHA-256 of URL
    title        TEXT,
    type         TEXT    NOT NULL
                         CHECK (type IN ('attendance', 'quiz')),
    raw_content  TEXT,
    company_options TEXT,                             -- JSON array of strings
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

-- ---------------------------------------------------------------------------
-- questions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS questions (
    id            TEXT    PRIMARY KEY,                -- UUID TEXT
    survey_id     TEXT    NOT NULL
                          REFERENCES surveys(id) ON DELETE CASCADE,
    subject_id    TEXT    NOT NULL,                   -- SurveyCake slug, e.g. "subject-5"
    question_text TEXT    NOT NULL,
    options       TEXT    NOT NULL,                   -- JSON array of strings
    correct_answer TEXT,
    verified      INTEGER NOT NULL DEFAULT 0,         -- BOOLEAN: 0=false, 1=true
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_questions_survey ON questions(survey_id);

-- ---------------------------------------------------------------------------
-- people
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS people (
    id         TEXT    PRIMARY KEY,                   -- UUID TEXT
    name       TEXT    NOT NULL,
    email      TEXT    NOT NULL UNIQUE,
    company    TEXT    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,            -- BOOLEAN: 0=false, 1=true
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

-- ---------------------------------------------------------------------------
-- submissions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS submissions (
    id                TEXT    PRIMARY KEY,            -- UUID TEXT
    survey_id         TEXT    NOT NULL
                              REFERENCES surveys(id) ON DELETE CASCADE,
    person_id         TEXT    NOT NULL
                              REFERENCES people(id)  ON DELETE CASCADE,
    status            TEXT    NOT NULL
                              CHECK (status IN ('success', 'failed', 'skipped')),
    score             INTEGER,                        -- quiz score; NULL for attendance
    is_pathfinder     INTEGER NOT NULL DEFAULT 0,     -- BOOLEAN: 1 = this run's pathfinder
    answers_snapshot  TEXT,                           -- JSON object {subject_id: answer_text}
    error_message     TEXT,
    submitted_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    CONSTRAINT uq_survey_person UNIQUE (survey_id, person_id)
);

CREATE INDEX IF NOT EXISTS idx_submissions_survey ON submissions(survey_id);
CREATE INDEX IF NOT EXISTS idx_submissions_person ON submissions(person_id);

-- ---------------------------------------------------------------------------
-- daily_runs  (was in ORM but missing from PG migration SQL)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_runs (
    id             TEXT    PRIMARY KEY,               -- UUID TEXT
    run_date       TEXT    NOT NULL UNIQUE,           -- DATE: YYYY-MM-DD
    attend_url     TEXT,
    quiz_url       TEXT,
    status         TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    result_summary TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
