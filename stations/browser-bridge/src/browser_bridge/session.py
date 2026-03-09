"""SessionManager — Safari session lifecycle management.

Safari is a singleton browser on macOS. Sessions are logical groupings
rather than isolated browser profiles. No APFS clones needed.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field


@dataclass
class PlaywrightSession:
    """Active browser session state.

    Name kept as PlaywrightSession for interface compatibility with core.py.
    For Safari backend, profile_path is unused.
    """

    profile_path: str  # unused for Safari, kept for interface compat
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
    For Playwright backend: sessions use APFS clones (future).
    """

    _counter = itertools.count(1)

    def __init__(self) -> None:
        self._sessions: dict[str, PlaywrightSession] = {}

    @property
    def active_sessions(self) -> list[PlaywrightSession]:
        return [s for s in self._sessions.values() if not s._closed]

    async def create(self, provider: str) -> PlaywrightSession:
        """Create a new logical session."""
        sid = f"safari-{next(self._counter)}"
        session = PlaywrightSession(
            profile_path="",  # unused for Safari
            session_id=sid,
            provider=provider,
        )
        self._sessions[session.session_id] = session
        return session

    async def close(self, session: PlaywrightSession) -> None:
        """Mark session as closed."""
        if session._closed:
            return
        session._closed = True
        self._sessions.pop(session.session_id, None)

    async def close_all(self) -> None:
        """Close all active sessions."""
        for session in list(self._sessions.values()):
            await self.close(session)

    def get(self, session_id: str) -> PlaywrightSession | None:
        return self._sessions.get(session_id)
