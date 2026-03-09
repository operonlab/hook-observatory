"""ConversationStore — SQLite-based conversation persistence.

Stores browser bridge sessions, conversations, and messages.
Station-level storage (not Core DB) for independence.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    SessionInfo,
    SessionStatus,
    ConversationInfo,
    MessageInfo,
    MessageRole,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str = "brg") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ConversationStore:
    """SQLite store for bridge conversations.

    Schema:
    - sessions: browser session lifecycle
    - conversations: logical conversation threads
    - messages: individual turns (user + assistant)
    """

    def __init__(self, db_path: str = "data/bridge.db") -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                profile_path TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_active TEXT
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                title TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                artifacts TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conv_session
                ON conversations(session_id);
            CREATE INDEX IF NOT EXISTS idx_msg_conv
                ON messages(conversation_id);
        """)
        self._conn.commit()

    # --- Session operations ---

    def create_session(self, provider: str, profile_path: str = "") -> str:
        """Create a new session. Returns session ID."""
        sid = _gen_id("ses")
        now = _now()
        self._conn.execute(
            "INSERT INTO sessions (id, provider, profile_path, status, created_at, last_active) "
            "VALUES (?, ?, ?, 'active', ?, ?)",
            (sid, provider, profile_path, now, now),
        )
        self._conn.commit()
        return sid

    def update_session_status(self, session_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET status = ?, last_active = ? WHERE id = ?",
            (status, _now(), session_id),
        )
        self._conn.commit()

    def touch_session(self, session_id: str) -> None:
        """Update last_active timestamp."""
        self._conn.execute(
            "UPDATE sessions SET last_active = ? WHERE id = ?",
            (_now(), session_id),
        )
        self._conn.commit()

    def list_sessions(
        self, provider: str | None = None, limit: int = 50
    ) -> list[SessionInfo]:
        query = "SELECT * FROM sessions"
        params: list = []
        if provider:
            query += " WHERE provider = ?"
            params.append(provider)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [
            SessionInfo(
                id=r["id"],
                provider=r["provider"],
                status=SessionStatus(r["status"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                last_active=(
                    datetime.fromisoformat(r["last_active"])
                    if r["last_active"]
                    else None
                ),
            )
            for r in rows
        ]

    def get_session(self, session_id: str) -> SessionInfo | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return SessionInfo(
            id=row["id"],
            provider=row["provider"],
            status=SessionStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_active=(
                datetime.fromisoformat(row["last_active"])
                if row["last_active"]
                else None
            ),
        )

    # --- Conversation operations ---

    def create_conversation(
        self, session_id: str, title: str | None = None
    ) -> str:
        """Create a new conversation. Returns conversation ID."""
        cid = _gen_id("conv")
        self._conn.execute(
            "INSERT INTO conversations (id, session_id, title, created_at) "
            "VALUES (?, ?, ?, ?)",
            (cid, session_id, title, _now()),
        )
        self._conn.commit()
        self.touch_session(session_id)
        return cid

    def list_conversations(
        self, session_id: str | None = None, limit: int = 50
    ) -> list[ConversationInfo]:
        if session_id:
            query = (
                "SELECT c.*, COUNT(m.id) as msg_count "
                "FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id "
                "WHERE c.session_id = ? "
                "GROUP BY c.id ORDER BY c.created_at DESC LIMIT ?"
            )
            rows = self._conn.execute(query, (session_id, limit)).fetchall()
        else:
            query = (
                "SELECT c.*, COUNT(m.id) as msg_count "
                "FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id "
                "GROUP BY c.id ORDER BY c.created_at DESC LIMIT ?"
            )
            rows = self._conn.execute(query, (limit,)).fetchall()

        return [
            ConversationInfo(
                id=r["id"],
                session_id=r["session_id"],
                title=r["title"],
                created_at=datetime.fromisoformat(r["created_at"]),
                message_count=r["msg_count"],
            )
            for r in rows
        ]

    # --- Message operations ---

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        artifacts: list[str] | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Add a message to a conversation. Returns message ID."""
        cursor = self._conn.execute(
            "INSERT INTO messages (conversation_id, role, content, artifacts, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(artifacts or []),
                json.dumps(metadata or {}),
                _now(),
            ),
        )
        self._conn.commit()

        # Update session last_active
        row = self._conn.execute(
            "SELECT session_id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row:
            self.touch_session(row["session_id"])

        return cursor.lastrowid

    def get_messages(
        self, conversation_id: str, limit: int = 100
    ) -> list[MessageInfo]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [
            MessageInfo(
                id=r["id"],
                conversation_id=r["conversation_id"],
                role=MessageRole(r["role"]),
                content=r["content"],
                artifacts=json.loads(r["artifacts"]),
                metadata=json.loads(r["metadata"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # --- Stats ---

    def stats(self) -> dict:
        """Return store statistics."""
        sessions = self._conn.execute(
            "SELECT COUNT(*) as c FROM sessions"
        ).fetchone()["c"]
        active = self._conn.execute(
            "SELECT COUNT(*) as c FROM sessions WHERE status = 'active'"
        ).fetchone()["c"]
        conversations = self._conn.execute(
            "SELECT COUNT(*) as c FROM conversations"
        ).fetchone()["c"]
        messages = self._conn.execute(
            "SELECT COUNT(*) as c FROM messages"
        ).fetchone()["c"]
        return {
            "total_sessions": sessions,
            "active_sessions": active,
            "total_conversations": conversations,
            "total_messages": messages,
        }

    def close(self) -> None:
        self._conn.close()
