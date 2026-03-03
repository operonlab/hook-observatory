-- Full-text search GIN index for memvault blocks
-- Run manually: psql -d workshop -f core/migrations/memvault_fts_index.sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blocks_fts
ON memvault.blocks
USING GIN (to_tsvector('english', content));
