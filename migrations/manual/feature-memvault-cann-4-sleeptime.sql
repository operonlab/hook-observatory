-- =====================================================================
-- Worker 4 — Sleeptime Reflection Agent
-- branch: feature/memvault-cann-4-sleeptime
--
-- Adds memvault.memory_block — multi-block hot snapshot table
-- (persona | human | project) maintained by sleeptime.py.
--
-- IMPORTANT: This migration must be wired into Alembic by Jones on the Mac
-- main host. Worker 4 cannot run alembic. Open follow-up issue.
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS memvault.memory_block (
    id              VARCHAR(32) PRIMARY KEY,
    space_id        VARCHAR(32) NOT NULL,
    created_by      VARCHAR(32),
    block_type      VARCHAR(32) NOT NULL,
    content         TEXT,
    word_count      INTEGER NOT NULL DEFAULT 0,
    block_version   INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT chk_memory_block_type
        CHECK (block_type IN ('persona', 'human', 'project'))
);

-- Soft-delete-aware uniqueness: one active row per (space_id, block_type)
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_block_space_type_active
    ON memvault.memory_block (space_id, block_type)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_memory_block_type
    ON memvault.memory_block (block_type);

CREATE INDEX IF NOT EXISTS idx_memory_block_space
    ON memvault.memory_block (space_id);

COMMIT;

-- =====================================================================
-- Rollback (manual):
--   DROP TABLE IF EXISTS memvault.memory_block;
-- =====================================================================
