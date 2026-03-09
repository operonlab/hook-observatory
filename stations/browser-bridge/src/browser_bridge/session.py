"""SessionManager — Playwright CLI session lifecycle management.

Wraps ~/.claude/scripts/pw_session.py for APFS clone-based browser isolation.
Each session gets an independent profile cloned from the golden master.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field

PW_SESSION_SCRIPT = os.path.expanduser("~/.claude/scripts/pw_session.py")


@dataclass
class PlaywrightSession:
    """Active Playwright session state."""
    profile_path: str      # /tmp/pw-XXXX
    session_id: str        # XXXX (from pw_session.py)
    provider: str          # which provider owns this session
    _closed: bool = field(default=False, repr=False)

    def cli_session_tag(self, suffix: str = "") -> str:
        """Generate -s= tag for Playwright CLI."""
        tag = f"{self.session_id}-{self.provider}"
        if suffix:
            tag = f"{tag}-{suffix}"
        return tag


class SessionManager:
    """Manages Playwright CLI sessions using pw_session.py APFS clones.

    Each call to create() produces an isolated browser profile.
    Concurrent sessions are safe (each gets its own clone).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, PlaywrightSession] = {}

    @property
    def active_sessions(self) -> list[PlaywrightSession]:
        return [s for s in self._sessions.values() if not s._closed]

    async def create(self, provider: str) -> PlaywrightSession:
        """Create a new isolated browser session via APFS clone.

        Returns:
            PlaywrightSession with profile_path and session_id set.
        """
        proc = await asyncio.create_subprocess_exec(
            "python3", PW_SESSION_SCRIPT, "init",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"pw_session.py init failed: {stderr.decode()[:200]}"
            )

        # Parse output: export PW_PROFILE=/tmp/pw-XXXX; export SID=XXXX
        output = stdout.decode()
        profile_match = re.search(r'PW_PROFILE=([^\s;]+)', output)
        sid_match = re.search(r'SID=([^\s;]+)', output)

        if not profile_match or not sid_match:
            raise RuntimeError(
                f"Failed to parse pw_session.py output: {output[:200]}"
            )

        session = PlaywrightSession(
            profile_path=profile_match.group(1),
            session_id=sid_match.group(1),
            provider=provider,
        )
        self._sessions[session.session_id] = session
        return session

    async def close(self, session: PlaywrightSession) -> None:
        """Close a session: stop Playwright CLI + cleanup profile clone."""
        if session._closed:
            return

        # Close Playwright CLI session
        close_proc = await asyncio.create_subprocess_exec(
            "npx", "@playwright/cli",
            f"-s={session.cli_session_tag()}",
            "close",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await close_proc.communicate()

        # Cleanup APFS clone
        cleanup_proc = await asyncio.create_subprocess_exec(
            "python3", PW_SESSION_SCRIPT,
            "cleanup", session.profile_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await cleanup_proc.communicate()

        session._closed = True
        self._sessions.pop(session.session_id, None)

    async def close_all(self) -> None:
        """Close all active sessions."""
        for session in list(self._sessions.values()):
            await self.close(session)

    def get(self, session_id: str) -> PlaywrightSession | None:
        """Get session by ID."""
        return self._sessions.get(session_id)
