-- bootstrap.sql — memvault-os standalone schema bootstrap
-- Run once after PostgreSQL is up to create all required tables.
--
-- Usage:
--   docker compose exec postgres psql -U memvault -d memvault_db -f /bootstrap.sql
--
-- Known limitations (see README.md for details):
-- 1. No HNSW vector index — small deployments (<10k blocks) use sequential scan.
--    Add manually for production: CREATE INDEX ... USING hnsw ...
-- 2. BlockFrozen / BlockArchive S3 fields present but cold-tier requires S3 storage.
-- 3. IDs are VARCHAR(32) storing UUID v7 hex (no hyphens) — same as workshop convention.
-- 4. No Alembic migration tracking — run this script once on a fresh DB only.

-- ==============================================================================
-- Prerequisites
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector (included in pgvector/pgvector:pg16 image)

-- ==============================================================================
-- Schema
-- ==============================================================================

CREATE SCHEMA IF NOT EXISTS memvault;

-- ==============================================================================
-- Helper: update updated_at on every row update
-- ==============================================================================

CREATE OR REPLACE FUNCTION memvault.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- ==============================================================================
-- blocks — primary memory store
-- SpaceScopedModel: id, created_at, updated_at, deleted_at, space_id, created_by
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.blocks (
    -- TimestampMixin
    id              VARCHAR(32)     PRIMARY KEY,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- SoftDeleteMixin
    deleted_at      TIMESTAMPTZ,
    -- SpaceScopedModel extras
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    -- MemoryBlock domain fields
    source_session  VARCHAR(64),
    content         TEXT            NOT NULL,
    block_type      VARCHAR(50)     NOT NULL DEFAULT 'general',
    tags            TEXT[]          NOT NULL DEFAULT '{}',
    confidence      FLOAT,
    -- Bitemporal fields (Graphiti-inspired)
    valid_at        TIMESTAMPTZ,
    invalid_at      TIMESTAMPTZ,
    superseded_by   VARCHAR(32),
    invalidation_reason VARCHAR(200),
    -- Access tracking
    access_count    INTEGER         NOT NULL DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    -- Fold / dedup (Verifier-Backed Extractive Fold)
    fold_id         VARCHAR(16),
    content_hash    VARCHAR(16),
    status          VARCHAR(32)     NOT NULL DEFAULT 'active',
    -- Dream pipeline signal extraction
    signal_type     VARCHAR(50),
    session_count   INTEGER         NOT NULL DEFAULT 1,
    -- Vector embedding (pgvector, 1024-dim = Qwen3-Embedding-0.6B)
    -- NULL until embedding is computed asynchronously
    embedding       VECTOR(1024)
);

CREATE INDEX IF NOT EXISTS idx_blocks_space_id   ON memvault.blocks (space_id);
CREATE INDEX IF NOT EXISTS idx_blocks_deleted_at ON memvault.blocks (deleted_at);
CREATE INDEX IF NOT EXISTS idx_blocks_type       ON memvault.blocks (block_type);
CREATE INDEX IF NOT EXISTS idx_blocks_session    ON memvault.blocks (source_session);
CREATE INDEX IF NOT EXISTS idx_blocks_fold_id    ON memvault.blocks (fold_id);
CREATE INDEX IF NOT EXISTS idx_blocks_signal     ON memvault.blocks (signal_type);
-- GIN index for tags array containment queries (@>, &&)
CREATE INDEX IF NOT EXISTS idx_blocks_tags ON memvault.blocks USING gin (tags);

-- NOTE: HNSW vector index omitted intentionally (see top-of-file comment).
-- For production add:
-- CREATE INDEX idx_blocks_embedding_hnsw ON memvault.blocks
--   USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TRIGGER trg_blocks_updated_at
    BEFORE UPDATE ON memvault.blocks
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- blocks_archive — cold data (metadata preserved, vector removed)
-- Uses Base (not SpaceScopedModel) — no soft-delete, archived_at instead
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.blocks_archive (
    id              VARCHAR(32)     PRIMARY KEY,
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    created_at      TEXT            NOT NULL,
    updated_at      TEXT            NOT NULL,
    source_session  VARCHAR(64),
    content         TEXT            NOT NULL,
    block_type      VARCHAR(50)     NOT NULL,
    tags            TEXT[]          NOT NULL DEFAULT '{}',
    confidence      FLOAT,
    archived_at     TEXT            NOT NULL,
    archive_type    VARCHAR(20)     NOT NULL DEFAULT 'cold-archive'
);

CREATE INDEX IF NOT EXISTS idx_ba_tags    ON memvault.blocks_archive USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_ba_type    ON memvault.blocks_archive (block_type);
CREATE INDEX IF NOT EXISTS idx_ba_created ON memvault.blocks_archive (created_at);
CREATE INDEX IF NOT EXISTS idx_ba_archived ON memvault.blocks_archive (archived_at);

-- ==============================================================================
-- tags — aggregated tag index
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.tags (
    id              VARCHAR(32)     PRIMARY KEY,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    name            VARCHAR(200)    NOT NULL,
    usage_count     INTEGER         NOT NULL DEFAULT 0
);

-- Unique tag name per space (only among active rows)
CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name ON memvault.tags (space_id, name)
    WHERE deleted_at IS NULL;

CREATE TRIGGER trg_tags_updated_at
    BEFORE UPDATE ON memvault.tags
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- knowledge_domains — expertise area aggregates
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.knowledge_domains (
    id              VARCHAR(32)     PRIMARY KEY,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    name            VARCHAR(200)    NOT NULL,
    description     TEXT,
    maturity        FLOAT           NOT NULL DEFAULT 0.0,
    block_count     INTEGER         NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kd_name ON memvault.knowledge_domains (space_id, name)
    WHERE deleted_at IS NULL;

CREATE TRIGGER trg_knowledge_domains_updated_at
    BEFORE UPDATE ON memvault.knowledge_domains
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- profile_scores — KAS aggregate per space
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.profile_scores (
    id              VARCHAR(32)     PRIMARY KEY,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    knowledge_score FLOAT           NOT NULL DEFAULT 0.0,
    attitude_score  FLOAT           NOT NULL DEFAULT 0.0,
    skill_score     FLOAT           NOT NULL DEFAULT 0.0
);

-- One active profile score per space
CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_scores_space ON memvault.profile_scores (space_id)
    WHERE deleted_at IS NULL;

CREATE TRIGGER trg_profile_scores_updated_at
    BEFORE UPDATE ON memvault.profile_scores
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- search_feedback — explicit relevance signals
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.search_feedback (
    id              VARCHAR(32)     PRIMARY KEY,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    entity_id       VARCHAR(32)     NOT NULL,
    query_hash      VARCHAR(64)     NOT NULL,
    signal          VARCHAR(20)     NOT NULL,
    feedback_source VARCHAR(20)     NOT NULL DEFAULT 'agent'
);

CREATE INDEX IF NOT EXISTS idx_sf_entity        ON memvault.search_feedback (entity_id);
CREATE INDEX IF NOT EXISTS idx_sf_query_hash    ON memvault.search_feedback (query_hash);
CREATE INDEX IF NOT EXISTS idx_sf_entity_signal ON memvault.search_feedback (entity_id, signal);

CREATE TRIGGER trg_search_feedback_updated_at
    BEFORE UPDATE ON memvault.search_feedback
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- query_journal — append-only recall log
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.query_journal (
    id                  VARCHAR(32)     PRIMARY KEY,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    space_id            VARCHAR(32)     NOT NULL,
    created_by          VARCHAR(32),
    query_text          TEXT            NOT NULL,
    query_hash          VARCHAR(64)     NOT NULL,
    routing_intent      VARCHAR(50),
    routing_confidence  FLOAT,
    layers_searched     TEXT[]          NOT NULL DEFAULT '{}',
    result_count        INTEGER         NOT NULL DEFAULT 0,
    evaluation_verdict  VARCHAR(20),
    evaluation_score    FLOAT,
    top_entity_ids      TEXT[]          NOT NULL DEFAULT '{}',
    session_id          VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_qj_query_hash      ON memvault.query_journal (query_hash);
CREATE INDEX IF NOT EXISTS idx_qj_space_created   ON memvault.query_journal (space_id, created_at);
CREATE INDEX IF NOT EXISTS idx_qj_routing_intent  ON memvault.query_journal (routing_intent);

CREATE TRIGGER trg_query_journal_updated_at
    BEFORE UPDATE ON memvault.query_journal
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- interest_snapshots — periodic interest profile
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.interest_snapshots (
    id                  VARCHAR(32)     PRIMARY KEY,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    space_id            VARCHAR(32)     NOT NULL,
    created_by          VARCHAR(32),
    snapshot_date       TIMESTAMPTZ     NOT NULL,
    period              VARCHAR(20)     NOT NULL,
    top_intents         JSONB,
    top_entities        JSONB,
    top_communities     JSONB,
    knowledge_gaps      JSONB,
    attention_profile   JSONB,
    query_volume        INTEGER         NOT NULL DEFAULT 0,
    avg_result_quality  FLOAT
);

CREATE INDEX IF NOT EXISTS idx_is_space_date ON memvault.interest_snapshots (space_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_is_period     ON memvault.interest_snapshots (period);

CREATE TRIGGER trg_interest_snapshots_updated_at
    BEFORE UPDATE ON memvault.interest_snapshots
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- memory_block — hot snapshot (persona | human | project per space)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.memory_block (
    id              VARCHAR(32)     PRIMARY KEY,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    block_type      VARCHAR(32)     NOT NULL,
    content         TEXT,
    word_count      INTEGER         NOT NULL DEFAULT 0,
    block_version   INTEGER         NOT NULL DEFAULT 1
);

-- One active (space_id, block_type) pair at a time
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_block_space_type_active
    ON memvault.memory_block (space_id, block_type)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_memory_block_type ON memvault.memory_block (block_type);

CREATE TRIGGER trg_memory_block_updated_at
    BEFORE UPDATE ON memvault.memory_block
    FOR EACH ROW EXECUTE FUNCTION memvault.set_updated_at();

-- ==============================================================================
-- blocks_frozen — legal retention tier (content in S3)
-- Requires S3 storage to be useful; table created regardless.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS memvault.blocks_frozen (
    id              VARCHAR(32)     PRIMARY KEY,
    space_id        VARCHAR(32)     NOT NULL,
    created_by      VARCHAR(32),
    created_at      TEXT            NOT NULL,
    archived_at     TEXT            NOT NULL,
    frozen_at       TEXT            NOT NULL,
    block_type      VARCHAR(50)     NOT NULL,
    tags            TEXT[]          NOT NULL DEFAULT '{}',
    source_session  VARCHAR(64),
    summary         TEXT,
    s3_uri          TEXT            NOT NULL DEFAULT '',
    content_hash    VARCHAR(64)     NOT NULL,
    content_size    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_bf_space_created ON memvault.blocks_frozen (space_id, created_at);
CREATE INDEX IF NOT EXISTS idx_bf_tags          ON memvault.blocks_frozen USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_bf_frozen        ON memvault.blocks_frozen (frozen_at);
CREATE INDEX IF NOT EXISTS idx_bf_type          ON memvault.blocks_frozen (block_type);

-- ==============================================================================
-- Done
-- ==============================================================================

\echo 'memvault schema bootstrap complete.'
