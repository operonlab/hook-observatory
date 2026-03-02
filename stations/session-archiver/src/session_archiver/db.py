"""PostgreSQL schema DDL and CRUD operations for session-archiver.

Uses psycopg3 (sync) directly -- this is a CLI tool, not FastAPI.
All DB operations degrade gracefully: return None/False when PG is unavailable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import psycopg
import structlog
from psycopg.rows import dict_row

from session_archiver.config import Config
from session_archiver.models import ArchiveRecord, ArchiveStats, ScoreBreakdown, SessionMeta

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};
SET search_path TO {schema};

CREATE TABLE IF NOT EXISTS sessions (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE,
    project_path    TEXT NOT NULL,
    tier            TEXT NOT NULL DEFAULT 'hot',
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    event_count     INTEGER NOT NULL DEFAULT 0,
    turn_count      INTEGER NOT NULL DEFAULT 0,
    has_companion   BOOLEAN NOT NULL DEFAULT FALSE,
    companion_size  BIGINT NOT NULL DEFAULT 0,
    first_timestamp TEXT,
    last_timestamp  TEXT,
    claude_version  TEXT,
    git_branch      TEXT,
    cwd             TEXT,
    score           DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_size      DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_age       DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_activity  DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_compress  DOUBLE PRECISION NOT NULL DEFAULT 0,
    archive_path    TEXT,
    archive_type    TEXT,
    compressed_size BIGINT,
    compression_ratio DOUBLE PRECISION,
    archived_at     TEXT,
    thawed_at       TEXT,
    thaw_count      INTEGER NOT NULL DEFAULT 0,
    summary         TEXT,
    scanned_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_embeddings (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE REFERENCES sessions(session_id) ON DELETE CASCADE,
    embedding       VECTOR(768) NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_log (
    id          SERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    action      TEXT NOT NULL,
    from_tier   TEXT,
    to_tier     TEXT,
    details     TEXT,
    dedup_hash  TEXT UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_tier ON sessions(tier);
CREATE INDEX IF NOT EXISTS idx_sessions_score ON sessions(score DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_sessions_last_ts ON sessions(last_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_archive_type ON sessions(archive_type);
CREATE INDEX IF NOT EXISTS idx_se_embedding ON session_embeddings USING hnsw (embedding vector_cosine_ops);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def get_connection(config: Config) -> psycopg.Connection | None:
    """Get a psycopg3 connection. Returns None if PG unavailable."""
    try:
        conn = psycopg.connect(
            config.database_url,
            row_factory=dict_row,
            autocommit=False,
        )
        conn.execute(
            "SET search_path TO %s",
            (config.db_schema,),
        )
        return conn
    except Exception:
        log.warning("pg_connect_failed", database_url=_redact_url(config.database_url))
        return None


def _redact_url(url: str) -> str:
    """Redact password from database URL for safe logging."""
    try:
        if "@" in url:
            prefix, rest = url.rsplit("@", 1)
            proto_user = prefix.rsplit(":", 1)[0]
            return f"{proto_user}:***@{rest}"
    except Exception:
        pass
    return "***"


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------


def ensure_schema(config: Config) -> bool:
    """Create schema and tables if they don't exist. Returns True on success."""
    conn = get_connection(config)
    if conn is None:
        return False
    try:
        with conn:
            # Enable pgvector extension (requires superuser or CREATE on schema)
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(_DDL.format(schema=config.db_schema))
        log.info("schema_ensured", schema=config.db_schema)
        return True
    except Exception:
        log.warning("schema_ensure_failed", schema=config.db_schema, exc_info=True)
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def upsert_session(config: Config, meta: SessionMeta, score: ScoreBreakdown) -> bool:
    """Insert or update a session record. Returns True on success."""
    conn = get_connection(config)
    if conn is None:
        return False

    now_iso = datetime.now(UTC).isoformat()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, project_path, tier,
                    file_size_bytes, event_count, turn_count,
                    has_companion, companion_size,
                    first_timestamp, last_timestamp,
                    claude_version, git_branch, cwd,
                    score, score_size, score_age, score_activity, score_compress,
                    scanned_at, updated_at
                ) VALUES (
                    %(session_id)s, %(project_path)s, 'hot',
                    %(file_size_bytes)s, %(event_count)s, %(turn_count)s,
                    %(has_companion)s, %(companion_size)s,
                    %(first_timestamp)s, %(last_timestamp)s,
                    %(claude_version)s, %(git_branch)s, %(cwd)s,
                    %(score)s, %(score_size)s, %(score_age)s,
                    %(score_activity)s, %(score_compress)s,
                    %(now)s, %(now)s
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    project_path    = EXCLUDED.project_path,
                    file_size_bytes = EXCLUDED.file_size_bytes,
                    event_count     = EXCLUDED.event_count,
                    turn_count      = EXCLUDED.turn_count,
                    has_companion   = EXCLUDED.has_companion,
                    companion_size  = EXCLUDED.companion_size,
                    first_timestamp = EXCLUDED.first_timestamp,
                    last_timestamp  = EXCLUDED.last_timestamp,
                    claude_version  = EXCLUDED.claude_version,
                    git_branch      = EXCLUDED.git_branch,
                    cwd             = EXCLUDED.cwd,
                    score           = EXCLUDED.score,
                    score_size      = EXCLUDED.score_size,
                    score_age       = EXCLUDED.score_age,
                    score_activity  = EXCLUDED.score_activity,
                    score_compress  = EXCLUDED.score_compress,
                    scanned_at      = EXCLUDED.scanned_at,
                    updated_at      = EXCLUDED.updated_at
                """,
                {
                    "session_id": meta.session_id,
                    "project_path": meta.project_path,
                    "file_size_bytes": meta.file_size_bytes,
                    "event_count": meta.event_count,
                    "turn_count": meta.turn_count,
                    "has_companion": meta.has_companion,
                    "companion_size": meta.companion_size,
                    "first_timestamp": meta.first_timestamp,
                    "last_timestamp": meta.last_timestamp,
                    "claude_version": meta.claude_version,
                    "git_branch": meta.git_branch,
                    "cwd": meta.cwd,
                    "score": score.total,
                    "score_size": score.size,
                    "score_age": score.age,
                    "score_activity": score.activity,
                    "score_compress": score.compressibility,
                    "now": now_iso,
                },
            )
        log.debug("session_upserted", session_id=meta.session_id, score=score.total)
        return True
    except Exception:
        log.warning("session_upsert_failed", session_id=meta.session_id, exc_info=True)
        return False
    finally:
        conn.close()


def update_archive_info(
    config: Config,
    session_id: str,
    archive_path: str,
    archive_type: str,
    compressed_size: int,
    compression_ratio: float,
) -> bool:
    """Update a session with archive info after compression."""
    conn = get_connection(config)
    if conn is None:
        return False

    now_iso = datetime.now(UTC).isoformat()
    try:
        with conn:
            conn.execute(
                """
                UPDATE sessions SET
                    tier = 'cold',
                    archive_path = %(archive_path)s,
                    archive_type = %(archive_type)s,
                    compressed_size = %(compressed_size)s,
                    compression_ratio = %(compression_ratio)s,
                    archived_at = %(now)s,
                    updated_at = %(now)s
                WHERE session_id = %(session_id)s
                """,
                {
                    "session_id": session_id,
                    "archive_path": archive_path,
                    "archive_type": archive_type,
                    "compressed_size": compressed_size,
                    "compression_ratio": compression_ratio,
                    "now": now_iso,
                },
            )
        log.debug("archive_info_updated", session_id=session_id, archive_type=archive_type)
        return True
    except Exception:
        log.warning("archive_info_update_failed", session_id=session_id, exc_info=True)
        return False
    finally:
        conn.close()


def update_thaw(config: Config, session_id: str) -> bool:
    """Mark a session as thawed (tier='hot', thaw_count += 1)."""
    conn = get_connection(config)
    if conn is None:
        return False

    now_iso = datetime.now(UTC).isoformat()
    try:
        with conn:
            conn.execute(
                """
                UPDATE sessions SET
                    tier = 'hot',
                    thawed_at = %(now)s,
                    thaw_count = thaw_count + 1,
                    updated_at = %(now)s
                WHERE session_id = %(session_id)s
                """,
                {"session_id": session_id, "now": now_iso},
            )
        log.debug("session_thawed", session_id=session_id)
        return True
    except Exception:
        log.warning("session_thaw_failed", session_id=session_id, exc_info=True)
        return False
    finally:
        conn.close()


def log_action(
    config: Config,
    session_id: str,
    action: str,
    from_tier: str,
    to_tier: str,
    details: str = "",
) -> bool:
    """Insert into archive_log with dedup_hash (ON CONFLICT DO NOTHING)."""
    conn = get_connection(config)
    if conn is None:
        return False

    now_iso = datetime.now(UTC).isoformat()
    dedup_hash = hashlib.sha256(
        f"{session_id}:{action}:{now_iso}".encode()
    ).hexdigest()

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO archive_log (
                    session_id, action, from_tier, to_tier,
                    details, dedup_hash, created_at
                ) VALUES (
                    %(session_id)s, %(action)s, %(from_tier)s, %(to_tier)s,
                    %(details)s, %(dedup_hash)s, %(now)s
                )
                ON CONFLICT (dedup_hash) DO NOTHING
                """,
                {
                    "session_id": session_id,
                    "action": action,
                    "from_tier": from_tier,
                    "to_tier": to_tier,
                    "details": details,
                    "dedup_hash": dedup_hash,
                    "now": now_iso,
                },
            )
        log.debug("action_logged", session_id=session_id, action=action)
        return True
    except Exception:
        log.warning("action_log_failed", session_id=session_id, action=action, exc_info=True)
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------


def _row_to_record(row: dict) -> ArchiveRecord:
    """Convert a dict row from the sessions table to an ArchiveRecord."""
    return ArchiveRecord(
        session_id=row["session_id"],
        project_path=row["project_path"],
        tier=row["tier"],
        file_size_bytes=row.get("file_size_bytes", 0),
        event_count=row.get("event_count", 0),
        turn_count=row.get("turn_count", 0),
        has_companion=row.get("has_companion", False),
        companion_size=row.get("companion_size", 0),
        first_timestamp=row.get("first_timestamp"),
        last_timestamp=row.get("last_timestamp"),
        claude_version=row.get("claude_version"),
        git_branch=row.get("git_branch"),
        cwd=row.get("cwd"),
        score=row.get("score", 0.0),
        score_size=row.get("score_size", 0.0),
        score_age=row.get("score_age", 0.0),
        score_activity=row.get("score_activity", 0.0),
        score_compress=row.get("score_compress", 0.0),
        archive_path=row.get("archive_path"),
        archive_type=row.get("archive_type"),
        compressed_size=row.get("compressed_size"),
        compression_ratio=row.get("compression_ratio"),
        archived_at=row.get("archived_at"),
        thawed_at=row.get("thawed_at"),
        thaw_count=row.get("thaw_count", 0),
        summary=row.get("summary"),
        scanned_at=row.get("scanned_at", ""),
        updated_at=row.get("updated_at", ""),
    )


def get_session(config: Config, session_id: str) -> ArchiveRecord | None:
    """Get a single session by exact ID or prefix match (min 8 chars)."""
    conn = get_connection(config)
    if conn is None:
        return None

    try:
        with conn:
            # Try exact match first, then prefix
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()
            if row is None and len(session_id) >= 8:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id LIKE %s LIMIT 1",
                    (session_id + "%",),
                ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)
    except Exception:
        log.warning("get_session_failed", session_id=session_id, exc_info=True)
        return None
    finally:
        conn.close()


def get_stats(config: Config) -> ArchiveStats | None:
    """Get aggregate statistics grouped by tier."""
    conn = get_connection(config)
    if conn is None:
        return None

    try:
        with conn:
            rows = conn.execute(
                """
                SELECT
                    tier,
                    COUNT(*)::INTEGER AS cnt,
                    COALESCE(SUM(file_size_bytes), 0)::BIGINT AS total_size,
                    COALESCE(SUM(compressed_size), 0)::BIGINT AS total_compressed
                FROM sessions
                GROUP BY tier
                """
            ).fetchall()

        stats = ArchiveStats()
        for row in rows:
            tier = row["tier"]
            if tier == "hot":
                stats.hot_count = row["cnt"]
                stats.hot_size = row["total_size"]
            elif tier == "cold":
                stats.cold_count = row["cnt"]
                stats.cold_original_size = row["total_size"]
                stats.cold_compressed_size = row["total_compressed"]
            elif tier == "frozen":
                stats.frozen_count = row["cnt"]

        # Total saved = original cold size - compressed cold size
        if stats.cold_original_size > 0:
            stats.total_saved = stats.cold_original_size - stats.cold_compressed_size
            stats.compression_ratio = round(
                stats.cold_compressed_size / stats.cold_original_size, 4
            )

        return stats
    except Exception:
        log.warning("get_stats_failed", exc_info=True)
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Embedding operations
# ---------------------------------------------------------------------------


def upsert_embedding(config: Config, session_id: str, embedding: list[float]) -> bool:
    """Insert or update a summary embedding."""
    conn = get_connection(config)
    if conn is None:
        return False

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO session_embeddings (session_id, embedding)
                VALUES (%(session_id)s, %(embedding)s::vector)
                ON CONFLICT (session_id) DO UPDATE SET
                    embedding = EXCLUDED.embedding
                """,
                {"session_id": session_id, "embedding": str(embedding)},
            )
        log.debug("embedding_upserted", session_id=session_id)
        return True
    except Exception:
        log.warning("embedding_upsert_failed", session_id=session_id, exc_info=True)
        return False
    finally:
        conn.close()


def search_by_embedding(
    config: Config, query_embedding: list[float], limit: int = 10
) -> list[ArchiveRecord]:
    """Semantic search via pgvector cosine similarity."""
    conn = get_connection(config)
    if conn is None:
        return []

    try:
        with conn:
            rows = conn.execute(
                """
                SELECT s.*, (se.embedding <=> %(embedding)s::vector) AS distance
                FROM session_embeddings se
                JOIN sessions s ON s.session_id = se.session_id
                ORDER BY se.embedding <=> %(embedding)s::vector
                LIMIT %(limit)s
                """,
                {"embedding": str(query_embedding), "limit": limit},
            ).fetchall()

        return [_row_to_record(row) for row in rows]
    except Exception:
        log.warning("search_by_embedding_failed", exc_info=True)
        return []
    finally:
        conn.close()


def search_by_text(
    config: Config, query: str, limit: int = 10
) -> list[ArchiveRecord]:
    """ILIKE fallback search on summary field."""
    conn = get_connection(config)
    if conn is None:
        return []

    try:
        pattern = f"%{query}%"
        with conn:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                WHERE summary ILIKE %(pattern)s
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                {"pattern": pattern, "limit": limit},
            ).fetchall()

        return [_row_to_record(row) for row in rows]
    except Exception:
        log.warning("search_by_text_failed", query=query, exc_info=True)
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Summary update
# ---------------------------------------------------------------------------


def update_summary(config: Config, session_id: str, summary: str) -> bool:
    """Update the summary field for a session."""
    conn = get_connection(config)
    if conn is None:
        return False

    now_iso = datetime.now(UTC).isoformat()
    try:
        with conn:
            conn.execute(
                """
                UPDATE sessions SET
                    summary = %(summary)s,
                    updated_at = %(now)s
                WHERE session_id = %(session_id)s
                """,
                {"session_id": session_id, "summary": summary, "now": now_iso},
            )
        log.debug("summary_updated", session_id=session_id)
        return True
    except Exception:
        log.warning("summary_update_failed", session_id=session_id, exc_info=True)
        return False
    finally:
        conn.close()
