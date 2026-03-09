"""SessionManager — browser session lifecycle management.

Supports two backends controlled by BRIDGE_BACKEND env var:
- "safari" (default): logical sessions, no isolated profiles, no subprocess.
- "playwright": APFS clone per session via pw_session.py, requires cleanup on close.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_BACKEND_TYPE = os.environ.get("BRIDGE_BACKEND", "safari")

PW_SESSION_SCRIPT = os.path.expanduser("~/.claude/scripts/pw_session.py")

_CHILD_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:"
    + os.environ.get("PATH", ""),
}


@dataclass
class PlaywrightSession:
    """Active browser session state.

    Name kept as PlaywrightSession for interface compatibility with core.py.
    For Safari backend, profile_path is unused.
    """

    profile_path: str  # unused for Safari backend, APFS clone path for Playwright
    session_id: str
    provider: str
    _closed: bool = field(default=False, repr=False)

    def cli_session_tag(self, suffix: str = "") -> str:
        """Generate session tag (kept for interface compatibility)."""
        tag = f"{self.session_id}-{self.provider}"
        if suffix:
            tag = f"{tag}-{suffix}"
        return tag


class SessionManager:
    """Manages browser sessions.

    For Safari backend: sessions are logical (no isolated profiles).
    For Playwright backend: sessions use APFS clones via pw_session.py.
    """

    _counter = itertools.count(1)

    def __init__(self) -> None:
        self._sessions: dict[str, PlaywrightSession] = {}

    @property
    def active_sessions(self) -> list[PlaywrightSession]:
        return [s for s in self._sessions.values() if not s._closed]

    async def create(self, provider: str) -> PlaywrightSession:
        """Create a new session using the configured backend."""
        if _BACKEND_TYPE == "playwright":
            return await self._create_playwright(provider)
        return self._create_safari(provider)

    def _create_safari(self, provider: str) -> PlaywrightSession:
        """Create a logical Safari session (no subprocess)."""
        sid = f"safari-{next(self._counter)}"
        session = PlaywrightSession(
            profile_path="",  # unused for Safari
            session_id=sid,
            provider=provider,
        )
        self._sessions[session.session_id] = session
        return session

    async def _create_playwright(self, provider: str) -> PlaywrightSession:
        """Create a Playwright session via APFS clone (pw_session.py init)."""
        proc = await asyncio.create_subprocess_exec(
            "python3",
            PW_SESSION_SCRIPT,
            "init",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CHILD_ENV,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"pw_session.py init failed: {stderr.decode()[:200]}")
        output = stdout.decode()
        profile_match = re.search(r"PW_PROFILE='?([^'\s;]+)'?", output)
        sid_match = re.search(r"SID='?([^'\s;]+)'?", output)
        if not profile_match or not sid_match:
            raise RuntimeError(f"Failed to parse pw_session.py output: {output[:200]}")
        session = PlaywrightSession(
            profile_path=profile_match.group(1).strip("'"),
            session_id=sid_match.group(1).strip("'"),
            provider=provider,
        )
        self._sessions[session.session_id] = session
        return session

    async def close(self, session: PlaywrightSession) -> None:
        """Close session and release resources."""
        if session._closed:
            return
        if _BACKEND_TYPE == "playwright" and session.profile_path:
            await self._close_playwright(session)
        session._closed = True
        self._sessions.pop(session.session_id, None)

    async def _close_playwright(self, session: PlaywrightSession) -> None:
        """Close Playwright CLI session and clean up APFS clone."""
        close_proc = await asyncio.create_subprocess_exec(
            "npx",
            "@playwright/cli",
            f"-s={session.cli_session_tag()}",
            "close",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CHILD_ENV,
        )
        await close_proc.communicate()

        cleanup_proc = await asyncio.create_subprocess_exec(
            "python3",
            PW_SESSION_SCRIPT,
            "cleanup",
            session.profile_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CHILD_ENV,
        )
        await cleanup_proc.communicate()

    async def close_all(self) -> None:
        """Close all active sessions."""
        for session in list(self._sessions.values()):
            await self.close(session)

    def get(self, session_id: str) -> PlaywrightSession | None:
        return self._sessions.get(session_id)
