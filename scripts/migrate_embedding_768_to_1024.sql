-- Migration: Embedding dimension 768 → 1024
-- Reason: Switching from Ollama nomic-embed-text (768d) to MLX Qwen3-Embedding-0.6B (1024d)
-- Date: 2026-03-10
--
-- Strategy:
--   1. DELETE rows in dedicated embedding tables (NOT NULL columns, will be regenerated)
--   2. NULL out embedding columns in entity tables (nullable columns)
--   3. ALTER COLUMN type from vector(768) to vector(1024)
--   4. Re-embedding happens via application code after migration

BEGIN;

-- ============================================================
-- memvault schema
-- ============================================================

-- Dedicated embedding tables: delete all rows (will be regenerated)
DELETE FROM memvault.block_embeddings;
DELETE FROM memvault.triple_embeddings;

-- Entity tables: null out embeddings
UPDATE memvault.blocks SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE memvault.triples SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE memvault.attitude_facts SET embedding = NULL WHERE embedding IS NOT NULL;

-- ALTER columns
ALTER TABLE memvault.blocks ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE memvault.block_embeddings ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE memvault.triple_embeddings ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE memvault.triples ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE memvault.attitude_facts ALTER COLUMN embedding TYPE vector(1024);

-- ============================================================
-- intelflow schema
-- ============================================================

-- Dedicated embedding table: delete all rows
DELETE FROM intelflow.report_embeddings;

-- Entity tables: null out embeddings
UPDATE intelflow.reports SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE intelflow.topics SET embedding = NULL WHERE embedding IS NOT NULL;

-- ALTER columns
ALTER TABLE intelflow.report_embeddings ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE intelflow.reports ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE intelflow.topics ALTER COLUMN embedding TYPE vector(1024);

-- ============================================================
-- briefing schema
-- ============================================================

-- Entity tables: null out embeddings
UPDATE briefing.briefings SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE briefing.briefing_entries SET embedding = NULL WHERE embedding IS NOT NULL;

-- ALTER columns
ALTER TABLE briefing.briefings ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE briefing.briefing_entries ALTER COLUMN embedding TYPE vector(1024);

COMMIT;
