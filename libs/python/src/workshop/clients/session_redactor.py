"""Session Redactor SDK — direct implementation (no HTTP server).

Detects and redacts sensitive data (API keys, passwords, tokens) from
Claude Code session transcript .jsonl files. Uses plain sqlite3 for
processing history tracking.

Usage:
    from workshop.clients.session_redactor import SessionRedactorClient

    client = SessionRedactorClient()

    # Redact a single file
    result = client.redact_file("/path/to/session.jsonl")

    # Run full sweep of all projects
    summary = client.full_sweep()

    # Test arbitrary text
    info = client.redact_text("password=my_secret123")

    # Query history
    stats = client.get_stats()
    history = client.get_history(limit=10)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ======================== Patterns ========================

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_sessions (
    file_path      TEXT PRIMARY KEY,
    file_size      INTEGER NOT NULL,
    file_mtime     REAL NOT NULL,
    line_count     INTEGER NOT NULL DEFAULT 0,
    session_id     TEXT,
    project_dir    TEXT,
    first_seen_at  TEXT NOT NULL,
    processed_at   TEXT NOT NULL,
    redactions     INTEGER NOT NULL DEFAULT 0,
    categories     TEXT,
    trigger        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_sessions(processed_at);
CREATE INDEX IF NOT EXISTS idx_session_id ON processed_sessions(session_id);
"""


@dataclass(frozen=True)
class RedactPattern:
    """A pattern that detects and redacts sensitive data."""

    name: str
    category: str
    regex: re.Pattern
    replacement: str


# Order matters: more specific patterns first to avoid partial matches.
PATTERNS: list[RedactPattern] = [
    # -- Passwords -------------------------------------------------------
    RedactPattern(
        name="sudo_password_pipe",
        category="password",
        regex=re.compile(r'echo\s+"[^"]*"\s*\|\s*sudo\s+-S'),
        replacement='echo "[REDACTED:password]" | sudo -S',
    ),
    RedactPattern(
        name="sudo_password_pipe_single",
        category="password",
        regex=re.compile(r"echo\s+'[^']*'\s*\|\s*sudo\s+-S"),
        replacement="echo '[REDACTED:password]' | sudo -S",
    ),
    # echo without quotes: echo 1111 | sudo -S
    RedactPattern(
        name="sudo_password_pipe_bare",
        category="password",
        regex=re.compile(r"echo\s+(\S+)\s*\|\s*sudo\s+-S"),
        replacement="echo [REDACTED:password] | sudo -S",
    ),
    RedactPattern(
        name="password_chinese",
        category="password",
        regex=re.compile(r"密碼[是為：:\s]*\S+"),
        replacement="密碼[REDACTED]",
    ),
    RedactPattern(
        name="password_english",
        category="password",
        regex=re.compile(r"password\s*(?:is|[:=])\s*[\"']?\S+", re.IGNORECASE),
        replacement="password [REDACTED]",
    ),
    # password followed by value in parens: "password (1111)"
    RedactPattern(
        name="password_parens",
        category="password",
        regex=re.compile(r"password\s*\(\s*([^)]+)\s*\)", re.IGNORECASE),
        replacement="password ([REDACTED])",
    ),
    # password followed by quoted value: 'password "1111"' or "password '1111'"
    RedactPattern(
        name="password_quoted",
        category="password",
        regex=re.compile(r'password\s+"([^"]+)"', re.IGNORECASE),
        replacement='password "[REDACTED]"',
    ),
    RedactPattern(
        name="password_quoted_single",
        category="password",
        regex=re.compile(r"password\s+'([^']+)'", re.IGNORECASE),
        replacement="password '[REDACTED]'",
    ),
    # -- API Keys --------------------------------------------------------
    # Anthropic key (must be before generic sk- pattern)
    RedactPattern(
        name="anthropic_api_key",
        category="api_key",
        regex=re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),
        replacement="[REDACTED:anthropic_key]",
    ),
    # OpenAI key
    RedactPattern(
        name="openai_api_key",
        category="api_key",
        regex=re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
        replacement="[REDACTED:openai_key]",
    ),
    # GitHub token
    RedactPattern(
        name="github_token",
        category="api_key",
        regex=re.compile(r"gh[ps]_[A-Za-z0-9_]{30,}"),
        replacement="[REDACTED:github_token]",
    ),
    # -- Tokens ----------------------------------------------------------
    RedactPattern(
        name="bearer_token",
        category="token",
        regex=re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
        replacement="Bearer [REDACTED:token]",
    ),
    # -- AWS -------------------------------------------------------------
    RedactPattern(
        name="aws_access_key",
        category="aws_key",
        regex=re.compile(r"AKIA[0-9A-Z]{16}"),
        replacement="[REDACTED:aws_key]",
    ),
    RedactPattern(
        name="aws_secret_key",
        category="aws_secret",
        regex=re.compile(
            r"(?:aws_secret|AWS_SECRET)[^\n=]*=\s*[\"']?[A-Za-z0-9/+=]{30,}",
            re.IGNORECASE,
        ),
        replacement="[REDACTED:aws_secret]",
    ),
    # -- SSH Keys --------------------------------------------------------
    RedactPattern(
        name="ssh_private_key",
        category="ssh_key",
        regex=re.compile(r"-----BEGIN\s+\S+\s+PRIVATE\s+KEY-----"),
        replacement="[REDACTED:ssh_private_key]",
    ),
    # -- Database connection strings ------------------------------------
    RedactPattern(
        name="db_connection_password",
        category="db_password",
        regex=re.compile(r"(://\w+:)([^@]+)(@)"),
        replacement=r"\1***\3",
    ),
    # -- Generic secrets (catch-all, must be last) ----------------------
    RedactPattern(
        name="generic_secret_assignment",
        category="generic_secret",
        regex=re.compile(
            r"((?:password|secret|token|api_key|apikey|api-key)\s*[=:]\s*)[\"']?([^\s\"',}]{4,})",
            re.IGNORECASE,
        ),
        replacement=r"\1[REDACTED]",
    ),
]


def redact_line(line: str) -> tuple[str, dict[str, int]]:
    """Apply all patterns to a single line.

    Returns:
        (redacted_line, categories_count) where categories_count maps
        category name to number of matches found.
    """
    categories: dict[str, int] = {}
    for pattern in PATTERNS:
        new_line, count = pattern.regex.subn(pattern.replacement, line)
        if count > 0:
            line = new_line
            categories[pattern.category] = categories.get(pattern.category, 0) + count
    return line, categories


# ======================== JSON Walker ========================


def _redact_value(value: Any, categories: dict[str, int]) -> tuple[Any, int]:
    """Recursively walk a JSON value, redacting all string leaves.

    Returns (redacted_value, total_redactions).
    """
    if isinstance(value, str):
        redacted, cats = redact_line(value)
        count = sum(cats.values())
        for cat, n in cats.items():
            categories[cat] = categories.get(cat, 0) + n
        return redacted, count

    if isinstance(value, list):
        total = 0
        new_list = []
        for item in value:
            new_item, n = _redact_value(item, categories)
            new_list.append(new_item)
            total += n
        return new_list, total

    if isinstance(value, dict):
        total = 0
        new_dict = {}
        for k, v in value.items():
            new_v, n = _redact_value(v, categories)
            new_dict[k] = new_v
            total += n
        return new_dict, total

    # Numbers, booleans, None — pass through
    return value, 0


def _redact_jsonl_line(line: str, categories: dict[str, int]) -> tuple[str, int]:
    """Parse a JSONL line, redact all string values, serialize back.

    Falls back to raw text redaction if JSON parsing fails.
    """
    stripped = line.rstrip("\n")
    if not stripped:
        return line, 0

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        # Not valid JSON — apply patterns to raw text as fallback
        redacted, cats = redact_line(line)
        count = sum(cats.values())
        for cat, n in cats.items():
            categories[cat] = categories.get(cat, 0) + n
        return redacted, count

    new_obj, count = _redact_value(obj, categories)
    if count > 0:
        return json.dumps(new_obj, ensure_ascii=False) + "\n", count
    return line, 0


# ======================== Client ========================


class SessionRedactorError(Exception):
    """Raised on unrecoverable redactor errors."""

    pass


@dataclass
class RedactResult:
    """Result of redacting a single file."""

    file_path: str
    redactions: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    changed: bool = False
    skipped: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "redactions": self.redactions,
            "categories": self.categories,
            "changed": self.changed,
            "skipped": self.skipped,
            "error": self.error,
        }


class SessionRedactorClient:
    """Session transcript redactor — detects and removes sensitive data.

    This is a DIRECT IMPLEMENTATION SDK (no HTTP server, no subprocess).
    All redaction logic runs in-process using plain sqlite3 for tracking.

    Args:
        db_path: SQLite database path. Defaults to REDACTOR_DB_PATH env or
            ~/.local/share/workshop/session_redactor.sqlite.
        projects_dir: Claude projects directory. Defaults to REDACTOR_PROJECTS_DIR
            env or ~/.claude/projects.
    """

    def __init__(
        self,
        db_path: str | None = None,
        projects_dir: str | None = None,
    ):
        self.db_path = db_path or os.environ.get(
            "REDACTOR_DB_PATH",
            os.path.expanduser("~/.local/share/workshop/session_redactor.sqlite"),
        )
        self.projects_dir = projects_dir or os.environ.get(
            "REDACTOR_PROJECTS_DIR",
            os.path.expanduser("~/.claude/projects"),
        )
        self._init_db()

    # ======================== DB Methods ========================

    def _init_db(self) -> None:
        """Create tables if they do not already exist."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        with self._connect() as con:
            con.executescript(_DB_SCHEMA)
        log.debug("session_redactor db initialized at %s", self.db_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the session redactor database."""
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _get_processed(self, file_path: str) -> dict | None:
        """Get the processing record for a file, or None if not yet processed."""
        with self._connect() as con:
            row = con.execute(
                "SELECT file_size, file_mtime FROM processed_sessions WHERE file_path = ?",
                (file_path,),
            ).fetchone()
            return dict(row) if row else None

    def _upsert_processed(
        self,
        file_path: str,
        file_size: int,
        file_mtime: float,
        line_count: int,
        session_id: str | None,
        project_dir: str | None,
        redactions: int,
        categories_json: str,
        trigger: str,
    ) -> None:
        """Insert or update a processing record."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as con:
            existing = con.execute(
                "SELECT first_seen_at FROM processed_sessions WHERE file_path = ?",
                (file_path,),
            ).fetchone()
            first_seen = existing["first_seen_at"] if existing else now

            con.execute(
                "INSERT OR REPLACE INTO processed_sessions "
                "(file_path, file_size, file_mtime, line_count, session_id, project_dir, "
                "first_seen_at, processed_at, redactions, categories, trigger) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_path,
                    file_size,
                    file_mtime,
                    line_count,
                    session_id,
                    project_dir,
                    first_seen,
                    now,
                    redactions,
                    categories_json,
                    trigger,
                ),
            )

    # ======================== Core Operations ========================

    def redact_file(
        self,
        file_path: str | Path,
        trigger: str = "manual",
        session_id: str | None = None,
    ) -> RedactResult:
        """Redact sensitive data in a single JSONL transcript file.

        Parses each line as JSON, recursively walks all string values,
        applies redaction patterns, and atomically writes back.

        Args:
            file_path: Path to the .jsonl file.
            trigger: What triggered this scan ("hook", "sweep", "manual").
            session_id: Optional session ID override.

        Returns:
            RedactResult with counts and status.
        """
        fp = Path(file_path)
        result = RedactResult(file_path=str(fp))

        if not fp.exists() or fp.suffix != ".jsonl":
            result.skipped = True
            return result

        # 1. Stat the file
        stat = fp.stat()
        file_size = stat.st_size
        file_mtime = stat.st_mtime

        # 2. Check DB: already processed and unchanged?
        existing = self._get_processed(str(fp))
        if existing and existing["file_size"] == file_size and existing["file_mtime"] == file_mtime:
            result.skipped = True
            return result

        # 3. Derive metadata
        if not session_id:
            session_id = fp.stem

        project_dir = str(fp.parent)
        if fp.parent.name == "subagents" or fp.parent.name.endswith("-subagents"):
            project_dir = str(fp.parent.parent)

        # 4. Read and redact (JSON-aware)
        try:
            lines = fp.read_text(encoding="utf-8").splitlines(keepends=True)
        except Exception as e:
            log.warning("redactor_read_error file=%s error=%s", str(fp), str(e))
            result.error = str(e)
            return result

        new_lines: list[str] = []
        total_redactions = 0
        all_categories: dict[str, int] = {}

        for line in lines:
            redacted, count = _redact_jsonl_line(line, all_categories)
            new_lines.append(redacted)
            total_redactions += count

        result.redactions = total_redactions
        result.categories = dict(all_categories)

        # 5. Atomic write if changed
        if total_redactions > 0:
            tmp_path = fp.with_suffix(".redacting.tmp")
            try:
                tmp_path.write_text("".join(new_lines), encoding="utf-8")
                os.replace(str(tmp_path), str(fp))
                result.changed = True
                log.info(
                    "redactor_redacted file=%s redactions=%d categories=%s trigger=%s",
                    str(fp),
                    total_redactions,
                    all_categories,
                    trigger,
                )
            except Exception as e:
                log.error("redactor_write_error file=%s error=%s", str(fp), str(e))
                tmp_path.unlink(missing_ok=True)
                result.error = str(e)
                return result

            # Re-stat after write
            stat = fp.stat()
            file_size = stat.st_size
            file_mtime = stat.st_mtime

        # 6. Record in DB
        self._upsert_processed(
            file_path=str(fp),
            file_size=file_size,
            file_mtime=file_mtime,
            line_count=len(lines),
            session_id=session_id,
            project_dir=project_dir,
            redactions=total_redactions,
            categories_json=json.dumps(all_categories) if all_categories else "{}",
            trigger=trigger,
        )

        return result

    def redact_text(self, text: str) -> dict:
        """Redact sensitive data from arbitrary text (no file I/O, no DB write).

        Useful for testing patterns or sanitizing text before logging.

        Returns:
            {
                "text": redacted_text,
                "redactions": total_count,
                "categories": {category: count, ...}
            }
        """
        categories: dict[str, int] = {}
        lines = text.splitlines(keepends=True)
        new_lines = []
        total = 0

        for line in lines:
            redacted_line, cats = redact_line(line)
            new_lines.append(redacted_line)
            count = sum(cats.values())
            total += count
            for cat, n in cats.items():
                categories[cat] = categories.get(cat, 0) + n

        return {
            "text": "".join(new_lines),
            "redactions": total,
            "categories": categories,
        }

    def full_sweep(self, trigger: str = "sweep") -> dict:
        """Scan all *.jsonl files under projects_dir.

        Returns:
            {
                "files_processed": int,
                "files_skipped": int,
                "total_redactions": int,
                "errors": int,
                "swept_at": ISO timestamp
            }
        """
        projects_dir = Path(self.projects_dir)
        if not projects_dir.exists():
            log.warning("redactor_projects_dir_missing path=%s", str(projects_dir))
            return {
                "files_processed": 0,
                "files_skipped": 0,
                "total_redactions": 0,
                "errors": 0,
                "swept_at": datetime.now(UTC).isoformat(),
            }

        log.info("redactor_sweep_start path=%s", str(projects_dir))

        files_processed = 0
        files_skipped = 0
        total_redactions = 0
        errors = 0

        for jsonl_file in sorted(projects_dir.rglob("*.jsonl")):
            result = self.redact_file(jsonl_file, trigger=trigger)
            if result.error:
                errors += 1
            elif result.skipped:
                files_skipped += 1
            else:
                files_processed += 1
                total_redactions += result.redactions

        swept_at = datetime.now(UTC).isoformat()
        log.info(
            "redactor_sweep_done files_processed=%d total_redactions=%d",
            files_processed,
            total_redactions,
        )
        return {
            "files_processed": files_processed,
            "files_skipped": files_skipped,
            "total_redactions": total_redactions,
            "errors": errors,
            "swept_at": swept_at,
        }

    # ======================== Query Operations ========================

    def get_stats(self) -> dict:
        """Get aggregate statistics.

        Returns:
            {
                "total_files": int,
                "total_redactions": int,
                "last_processed_at": ISO timestamp or None
            }
        """
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS total_files, "
                "COALESCE(SUM(redactions), 0) AS total_redactions, "
                "MAX(processed_at) AS last_processed_at "
                "FROM processed_sessions"
            ).fetchone()
            return (
                dict(row)
                if row
                else {
                    "total_files": 0,
                    "total_redactions": 0,
                    "last_processed_at": None,
                }
            )

    def get_history(self, limit: int = 30) -> list[dict]:
        """Get recent processing records, most recent first.

        Args:
            limit: Maximum records to return.

        Returns:
            List of dicts with file_path, redactions, categories, trigger, processed_at, etc.
        """
        with self._connect() as con:
            rows = con.execute(
                "SELECT file_path, file_size, line_count, session_id, "
                "project_dir, processed_at, redactions, categories, trigger "
                "FROM processed_sessions ORDER BY processed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_session_history(self, session_id: str) -> list[dict]:
        """Get processing records for a specific session ID.

        Args:
            session_id: Session ID (usually the .jsonl filename stem).

        Returns:
            List of processing records for that session.
        """
        with self._connect() as con:
            rows = con.execute(
                "SELECT file_path, file_size, line_count, "
                "processed_at, redactions, categories, trigger "
                "FROM processed_sessions WHERE session_id = ? ORDER BY processed_at DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_patterns(self) -> list[dict]:
        """Return all detection pattern names and categories.

        Returns:
            List of {name, category} dicts.
        """
        return [{"name": p.name, "category": p.category} for p in PATTERNS]
