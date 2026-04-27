-- ============================================================================
-- Worker 2 (cannibalize Phase 1): Verifier-Backed Extractive Fold + Dual-Key
-- ============================================================================
-- Branch:  feature/memvault-cann-2-fold-verifier
-- Target:  memvault.blocks   (ORM: core/src/modules/memvault/models.py :: MemoryBlock)
--
-- Adds three columns used by Dream Loop's _consolidate fold path:
--   fold_id       VARCHAR(16)  — sha256(sorted(children_block_ids))[:16]
--                                stable across re-runs over the same child-set
--   content_hash  VARCHAR(16)  — sha256(consolidate_output_text)[:16]
--                                detects child-content drift
--   status        VARCHAR(32)  — active | conflict_pending
--                                'conflict_pending' = pre-write KG contradiction
--                                detected, fold quarantined for human review
--
-- This file is **manual SQL** for Jones to run on the Mac host.
-- Do NOT run it from a sub-agent / remote Claude Code (alembic rule).
--
-- Suggested invocation:
--   psql workshop -v ON_ERROR_STOP=1 \
--     -f core/migrations/manual/feature-memvault-cann-2-fold-verifier.sql
--
-- After applying, also run an alembic revision to keep the version graph honest:
--   cd core && alembic revision -m "memvault fold dual-key + verifier" --autogenerate
-- ============================================================================

BEGIN;

-- 1. Columns ------------------------------------------------------------------
ALTER TABLE memvault.blocks
    ADD COLUMN IF NOT EXISTS fold_id      VARCHAR(16),
    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(16),
    ADD COLUMN IF NOT EXISTS status       VARCHAR(32) NOT NULL DEFAULT 'active';

-- 2. Index on fold_id (lookup hot path) --------------------------------------
-- Soft-delete safe: only index live rows (matches the partial-unique-index rule
-- documented in dev-patterns.md for soft-delete models).
CREATE INDEX IF NOT EXISTS idx_blocks_fold_id_active
    ON memvault.blocks (fold_id)
    WHERE deleted_at IS NULL AND fold_id IS NOT NULL;

-- 3. Optional: status index for dashboards / lint ----------------------------
CREATE INDEX IF NOT EXISTS idx_blocks_status
    ON memvault.blocks (status)
    WHERE deleted_at IS NULL;

-- 4. Backfill is intentionally a no-op:
--    legacy rows keep status='active' via column default; fold_id /
--    content_hash stay NULL until the next dream loop touches them.
--    (Worker 2 treats NULL fold_id as "never folded" → eligible for first fold.)

COMMIT;

-- Rollback (manual):
-- BEGIN;
-- DROP INDEX IF EXISTS memvault.idx_blocks_status;
-- DROP INDEX IF EXISTS memvault.idx_blocks_fold_id_active;
-- ALTER TABLE memvault.blocks
--     DROP COLUMN IF EXISTS status,
--     DROP COLUMN IF EXISTS content_hash,
--     DROP COLUMN IF EXISTS fold_id;
-- COMMIT;
