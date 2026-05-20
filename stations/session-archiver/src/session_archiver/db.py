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
SET search_path TO {schema}, public;

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
    embedding       VECTOR(1024) NOT NULL
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

CREATE TABLE IF NOT EXISTS session_reflections (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE,
    outcome         TEXT NOT NULL DEFAULT 'unknown',
    quality_score   DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_tokens    BIGINT NOT NULL DEFAULT 0,
    user_tokens     BIGINT NOT NULL DEFAULT 0,
    assistant_tokens BIGINT NOT NULL DEFAULT 0,
    tool_call_count     INTEGER NOT NULL DEFAULT 0,
    tool_success_count  INTEGER NOT NULL DEFAULT 0,
    tool_error_count    INTEGER NOT NULL DEFAULT 0,
    tool_success_rate   DOUBLE PRECISION NOT NULL DEFAULT 0,
    context_efficiency  DOUBLE PRECISION NOT NULL DEFAULT 0,
    turn_count      INTEGER NOT NULL DEFAULT 0,
    duration_secs   INTEGER NOT NULL DEFAULT 0,
    error_messages  TEXT[],
    failure_patterns TEXT[],
    reflection_fed  BOOLEAN NOT NULL DEFAULT FALSE,
    invariant_count INTEGER NOT NULL DEFAULT 0,
    derived_count   INTEGER NOT NULL DEFAULT 0,
    pipeline_stages_ok  INTEGER NOT NULL DEFAULT 0,
    pipeline_stages_fail INTEGER NOT NULL DEFAULT 0,
    reflected_at    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_tier ON sessions(tier);
CREATE INDEX IF NOT EXISTS idx_sessions_score ON sessions(score DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_sessions_last_ts ON sessions(last_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_archive_type ON sessions(archive_type);
CREATE INDEX IF NOT EXISTS idx_se_embedding
    ON session_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_sr_outcome ON session_reflections(outcome);
CREATE INDEX IF NOT EXISTS idx_sr_quality ON session_reflections(quality_score DESC);
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
            psycopg.sql.SQL("SET search_path TO {}, public").format(
                psycopg.sql.Identifier(config.db_schema)
            )
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
    except Exception:  # noqa: S110
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
            # pgvector extension is managed by core Alembic migrations (public schema)
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
    dedup_hash = hashlib.sha256(f"{session_id}:{action}:{now_iso}".encode()).hexdigest()

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
            elif tier == "warm":
                stats.warm_count = row["cnt"]
                stats.warm_size = row["total_size"]
            elif tier == "cold":
                stats.cold_count = row["cnt"]
                stats.cold_original_size = row["total_size"]
                stats.cold_compressed_size = row["total_compressed"]
            elif tier == "frozen":
                stats.frozen_count = row["cnt"]
                stats.frozen_original_size = row["total_size"]
                stats.frozen_compressed_size = row["total_compressed"]

        # Total saved = (cold + frozen) original - compressed
        total_original = stats.cold_original_size + stats.frozen_original_size
        total_compressed = stats.cold_compressed_size + stats.frozen_compressed_size
        if total_original > 0:
            stats.total_saved = total_original - total_compressed
            stats.compression_ratio = round(total_compressed / total_original, 4)

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


def search_by_text(config: Config, query: str, limit: int = 10) -> list[ArchiveRecord]:
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


# ---------------------------------------------------------------------------
# Reflection CRUD
# ---------------------------------------------------------------------------


def upsert_reflection(config: Config, data: dict) -> bool:
    """Insert or update a session reflection record. Returns True on success."""
    conn = get_connection(config)
    if conn is None:
        return False

    now_iso = datetime.now(UTC).isoformat()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO session_reflections (
                    session_id, outcome, quality_score,
                    total_tokens, user_tokens, assistant_tokens,
                    tool_call_count, tool_success_count, tool_error_count,
                    tool_success_rate, context_efficiency,
                    turn_count, duration_secs,
                    error_messages, failure_patterns,
                    reflection_fed, invariant_count, derived_count,
                    pipeline_stages_ok, pipeline_stages_fail,
                    reflected_at, created_at
                ) VALUES (
                    %(session_id)s, %(outcome)s, %(quality_score)s,
                    %(total_tokens)s, %(user_tokens)s, %(assistant_tokens)s,
                    %(tool_call_count)s, %(tool_success_count)s, %(tool_error_count)s,
                    %(tool_success_rate)s, %(context_efficiency)s,
                    %(turn_count)s, %(duration_secs)s,
                    %(error_messages)s, %(failure_patterns)s,
                    %(reflection_fed)s, %(invariant_count)s, %(derived_count)s,
                    %(pipeline_stages_ok)s, %(pipeline_stages_fail)s,
                    %(reflected_at)s, %(created_at)s
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    outcome             = EXCLUDED.outcome,
                    quality_score       = EXCLUDED.quality_score,
                    total_tokens        = EXCLUDED.total_tokens,
                    user_tokens         = EXCLUDED.user_tokens,
                    assistant_tokens    = EXCLUDED.assistant_tokens,
                    tool_call_count     = EXCLUDED.tool_call_count,
                    tool_success_count  = EXCLUDED.tool_success_count,
                    tool_error_count    = EXCLUDED.tool_error_count,
                    tool_success_rate   = EXCLUDED.tool_success_rate,
                    context_efficiency  = EXCLUDED.context_efficiency,
                    turn_count          = EXCLUDED.turn_count,
                    duration_secs       = EXCLUDED.duration_secs,
                    error_messages      = EXCLUDED.error_messages,
                    failure_patterns    = EXCLUDED.failure_patterns,
                    reflection_fed      = EXCLUDED.reflection_fed,
                    invariant_count     = EXCLUDED.invariant_count,
                    derived_count       = EXCLUDED.derived_count,
                    pipeline_stages_ok  = EXCLUDED.pipeline_stages_ok,
                    pipeline_stages_fail = EXCLUDED.pipeline_stages_fail,
                    reflected_at        = EXCLUDED.reflected_at
                """,
                {
                    "session_id": data["session_id"],
                    "outcome": data.get("outcome", "unknown"),
                    "quality_score": data.get("quality_score", 0.0),
                    "total_tokens": data.get("total_tokens", 0),
                    "user_tokens": data.get("user_tokens", 0),
                    "assistant_tokens": data.get("assistant_tokens", 0),
                    "tool_call_count": data.get("tool_call_count", 0),
                    "tool_success_count": data.get("tool_success_count", 0),
                    "tool_error_count": data.get("tool_error_count", 0),
                    "tool_success_rate": data.get("tool_success_rate", 0.0),
                    "context_efficiency": data.get("context_efficiency", 0.0),
                    "turn_count": data.get("turn_count", 0),
                    "duration_secs": data.get("duration_secs", 0),
                    "error_messages": data.get("error_messages") or [],
                    "failure_patterns": data.get("failure_patterns") or [],
                    "reflection_fed": data.get("reflection_fed", False),
                    "invariant_count": data.get("invariant_count", 0),
                    "derived_count": data.get("derived_count", 0),
                    "pipeline_stages_ok": data.get("pipeline_stages_ok", 0),
                    "pipeline_stages_fail": data.get("pipeline_stages_fail", 0),
                    "reflected_at": data.get("reflected_at", now_iso),
                    "created_at": now_iso,
                },
            )
        log.debug("reflection_upserted", session_id=data["session_id"])
        return True
    except Exception:
        log.warning("reflection_upsert_failed", session_id=data.get("session_id"), exc_info=True)
        return False
    finally:
        conn.close()


def get_reflection(config: Config, session_id: str) -> dict | None:
    """Get a reflection record by session_id. Returns None if not found."""
    conn = get_connection(config)
    if conn is None:
        return None

    try:
        with conn:
            row = conn.execute(
                "SELECT * FROM session_reflections WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)
    except Exception:
        log.warning("get_reflection_failed", session_id=session_id, exc_info=True)
        return None
    finally:
        conn.close()


def get_warm_candidates(
    config: Config, min_age_days: int = 3, min_turns: int = 1, limit: int = 100
) -> list[tuple[str, str]]:
    """Return (session_id, project_path) for hot sessions eligible for warm transition.

    Criteria: tier='hot', age >= min_age_days, turn_count >= min_turns, no summary yet.
    """
    conn = get_connection(config)
    if conn is None:
        return []

    try:
        with conn:
            rows = conn.execute(
                """
                SELECT session_id, project_path
                FROM sessions
                WHERE tier = 'hot'
                  AND summary IS NULL
                  AND turn_count >= %(min_turns)s
                  AND last_timestamp < (now() - make_interval(days => %(min_age)s))::text
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                {"min_turns": min_turns, "min_age": min_age_days, "limit": limit},
            ).fetchall()
        return [(r["session_id"], r.get("project_path", "")) for r in rows]
    except Exception:
        log.warning("get_warm_candidates_failed", exc_info=True)
        return []
    finally:
        conn.close()


def update_tier(config: Config, session_id: str, new_tier: str) -> bool:
    """Update the tier field for a session."""
    conn = get_connection(config)
    if conn is None:
        return False

    try:
        with conn:
            conn.execute(
                "UPDATE sessions SET tier = %(tier)s, updated_at = %(now)s WHERE session_id = %(sid)s",
                {"tier": new_tier, "now": datetime.now(UTC).isoformat(), "sid": session_id},
            )
        log.debug("tier_updated", session_id=session_id, tier=new_tier)
        return True
    except Exception:
        log.warning("tier_update_failed", session_id=session_id, exc_info=True)
        return False
    finally:
        conn.close()


def get_unreflected_session_ids(config: Config, limit: int = 50) -> list[tuple[str, str | None]]:
    """Return (session_id, project_path) for sessions without reflections."""
    conn = get_connection(config)
    if conn is None:
        return []

    try:
        with conn:
            rows = conn.execute(
                """
                SELECT s.session_id, s.project_path
                FROM sessions s
                LEFT JOIN session_reflections r ON r.session_id = s.session_id
                WHERE r.session_id IS NULL
                ORDER BY s.last_timestamp DESC NULLS LAST
                LIMIT %(limit)s
                """,
                {"limit": limit},
            ).fetchall()
        return [(r["session_id"], r.get("project_path")) for r in rows]
    except Exception:
        log.warning("get_unreflected_failed", exc_info=True)
        return []
    finally:
        conn.close()


def get_freeze_candidates(config: Config, min_cold_days: int = 30) -> list[dict]:
    """Return cold sessions eligible for freezing (archived_at older than min_cold_days)."""
    conn = get_connection(config)
    if conn is None:
        return []

    try:
        with conn:
            rows = conn.execute(
                """
                SELECT session_id, archive_path, archived_at, compressed_size
                FROM sessions
                WHERE tier = 'cold'
                  AND archived_at IS NOT NULL
                  AND archived_at::TIMESTAMPTZ < NOW() - make_interval(days => %s)
                ORDER BY archived_at ASC
                """,
                (min_cold_days,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        log.warning("get_freeze_candidates_failed", exc_info=True)
        return []
    finally:
        conn.close()


def update_freeze_info(
    config: Config,
    session_id: str,
    s3_uri: str,
    archive_type: str = "cold-blob",
) -> bool:
    """Update a session to frozen tier with S3 URI."""
    conn = get_connection(config)
    if conn is None:
        return False

    now_iso = datetime.now(UTC).isoformat()
    try:
        with conn:
            conn.execute(
                """
                UPDATE sessions SET
                    tier = 'frozen',
                    archive_path = %(archive_path)s,
                    archive_type = %(archive_type)s,
                    updated_at = %(now)s
                WHERE session_id = %(session_id)s
                """,
                {
                    "session_id": session_id,
                    "archive_path": s3_uri,
                    "archive_type": archive_type,
                    "now": now_iso,
                },
            )
        log.debug("freeze_info_updated", session_id=session_id, s3_uri=s3_uri)
        return True
    except Exception:
        log.warning("freeze_info_update_failed", session_id=session_id, exc_info=True)
        return False
    finally:
        conn.close()


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


def query_low_quality_sessions(config: Config, max_score: float = 0.15) -> list[dict]:
    """Return sessions with low quality score from reflections table."""
    conn = get_connection(config)
    if conn is None:
        return []
    try:
        with conn:
            rows = conn.execute(
                """
                SELECT sr.session_id, sr.quality_score, sr.outcome,
                       EXTRACT(EPOCH FROM (NOW() - s.updated_at)) / 86400 AS age_days
                FROM session_reflections sr
                JOIN sessions s ON s.session_id = sr.session_id
                WHERE sr.quality_score < %(max_score)s
                  AND sr.outcome = 'failure'
                ORDER BY sr.quality_score ASC
                """,
                {"max_score": max_score},
            ).fetchall()
        return [
            {
                "session_id": r[0],
                "quality_score": float(r[1]) if r[1] is not None else 0.0,
                "outcome": r[2],
                "age_days": float(r[3]) if r[3] is not None else 0.0,
            }
            for r in rows
        ]
    except Exception:
        log.warning("query_low_quality_failed", exc_info=True)
        return []
    finally:
        conn.close()


def delete_session(config: Config, session_id: str) -> bool:
    """Delete a session and its reflection from DB."""
    conn = get_connection(config)
    if conn is None:
        return False
    try:
        with conn:
            conn.execute(
                "DELETE FROM session_reflections WHERE session_id = %(sid)s",
                {"sid": session_id},
            )
            conn.execute(
                "DELETE FROM session_embeddings WHERE session_id = %(sid)s",
                {"sid": session_id},
            )
            conn.execute(
                "DELETE FROM sessions WHERE session_id = %(sid)s",
                {"sid": session_id},
            )
        log.debug("session_deleted", session_id=session_id)
        return True
    except Exception:
        log.warning("session_delete_failed", session_id=session_id, exc_info=True)
        return False
    finally:
        conn.close()


def cleanup_missing_hot_sessions(config: Config, scanned_ids: set[str]) -> int:
    """Delete DB rows whose JSONL has disappeared from disk.

    Only purges tier='hot' AND archive_path IS NULL rows that are NOT in scanned_ids.
    Preserves cold/warm/frozen and any already-archived hot rows.

    Returns the number of rows pruned (0 on DB connection failure).
    """
    if not scanned_ids:
        return 0
    conn = get_connection(config)
    if conn is None:
        return 0
    try:
        with conn:
            result = conn.execute(
                """
                DELETE FROM sessions
                WHERE tier = 'hot'
                  AND archive_path IS NULL
                  AND session_id != ALL(%(sids)s)
                """,
                {"sids": list(scanned_ids)},
            )
            pruned = result.rowcount or 0
        if pruned:
            log.info("cleanup_orphan_hot", pruned=pruned)
        return pruned
    except Exception:
        log.warning("cleanup_orphan_hot_failed", exc_info=True)
        return 0
    finally:
        conn.close()
