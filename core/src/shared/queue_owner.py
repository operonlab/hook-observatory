"""Queue Owner Lease — file-based exclusive access for agent coordination.

Inspired by acpx's Queue Owner pattern: lock file + IPC socket.
Simplified for Workshop: file lock + PID tracking (no Unix socket needed yet).

Usage:
    async with QueueOwner("session-abc") as owner:
        if owner.acquired:
            # We have exclusive access
            await do_work()
        else:
            # Another process owns this session
            print(f"Owned by PID {owner.current_owner_pid}")
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCK_DIR = Path.home() / ".workshop" / "locks"
DEFAULT_TTL = 300  # seconds


class LockData:
    """Parsed content of a .lock file."""

    __slots__ = ("acquired_at", "pid", "ttl")

    def __init__(self, pid: int, acquired_at: str, ttl: int) -> None:
        self.pid = pid
        self.acquired_at = acquired_at
        self.ttl = ttl

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LockData:
        return cls(
            pid=int(data["pid"]),
            acquired_at=str(data["acquired_at"]),
            ttl=int(data["ttl"]),
        )

    def to_json(self) -> str:
        return json.dumps(
            {"pid": self.pid, "acquired_at": self.acquired_at, "ttl": self.ttl}
        )

    def age_seconds(self) -> float:
        try:
            ts = datetime.fromisoformat(self.acquired_at)
            return (datetime.now(UTC) - ts).total_seconds()
        except ValueError:
            return float("inf")


class QueueOwner:
    """File-based exclusive lease for a named resource.

    Uses O_CREAT | O_EXCL for atomic creation — guaranteed race-free on POSIX.
    Automatically reclaims stale locks (dead PID or TTL exceeded).
    """

    def __init__(self, name: str, ttl: int = DEFAULT_TTL) -> None:
        self._name = name
        self._ttl = ttl
        self._lock_path = LOCK_DIR / f"{name}.lock"
        self.acquired: bool = False
        self._asyncio_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_owner_pid(self) -> int | None:
        """Return the PID recorded in the lock file, or None if no lock exists."""
        data = self._read_lock()
        return data.pid if data else None

    async def acquire(self) -> bool:
        """Try to acquire the lease.  Returns True if successful."""
        async with self._asyncio_lock:
            LOCK_DIR.mkdir(parents=True, exist_ok=True)

            # Attempt atomic creation first
            if self._try_create():
                self.acquired = True
                return True

            # If creation failed, check whether the existing lock is stale
            existing = self._read_lock()
            if existing and self._is_stale(existing):
                self._lock_path.unlink(missing_ok=True)
                if self._try_create():
                    self.acquired = True
                    return True

            self.acquired = False
            return False

    def release(self) -> None:
        """Release the lease (no-op if we don't own it)."""
        if not self.acquired:
            return
        try:
            self._lock_path.unlink(missing_ok=True)
        finally:
            self.acquired = False

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> QueueOwner:
        await self.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        self.release()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _try_create(self) -> bool:
        """Atomically create the lock file.  Returns True on success."""
        try:
            fd = os.open(
                self._lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            data = LockData(
                pid=os.getpid(),
                acquired_at=datetime.now(UTC).isoformat(),
                ttl=self._ttl,
            )
            os.write(fd, data.to_json().encode())
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def _read_lock(self) -> LockData | None:
        """Parse the existing lock file; return None if missing or corrupt."""
        try:
            raw = self._lock_path.read_text(encoding="utf-8")
            return LockData.from_dict(json.loads(raw))
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
            return None

    def _is_stale(self, data: LockData) -> bool:
        """Return True if the lock should be reclaimed."""
        # TTL exceeded?
        if data.age_seconds() > data.ttl:
            return True
        # PID dead?
        try:
            os.kill(data.pid, 0)
            return False  # process alive
        except ProcessLookupError:
            return True  # PID gone
        except PermissionError:
            return False  # exists but owned by another user — not stale
