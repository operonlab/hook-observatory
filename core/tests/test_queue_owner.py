"""Tests for QueueOwner — file-based exclusive lease."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# We isolate tests to a temp lock dir so we never touch ~/.workshop/locks
# ---------------------------------------------------------------------------

FAKE_LOCK_DIR = Path("/tmp/test_workshop_locks")  # noqa: S108


@pytest.fixture(autouse=True)
def patch_lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect LOCK_DIR to a fresh temp directory for each test."""
    import src.shared.queue_owner as qo_mod

    monkeypatch.setattr(qo_mod, "LOCK_DIR", tmp_path)
    # Patch the class-level path derivation by overriding module constant only;
    # individual QueueOwner instances rebuild their path from the module attr.


# Helper — import after monkeypatch applies (done via fixture, so direct import is fine
# at module load; instances created inside tests pick up the patched constant).
from src.shared.queue_owner import QueueOwner  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Acquire / release lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.shared.queue_owner as qo_mod

    monkeypatch.setattr(qo_mod, "LOCK_DIR", tmp_path)

    owner = QueueOwner.__new__(QueueOwner)
    owner._name = "test-res"
    owner._ttl = 300
    owner._lock_path = tmp_path / "test-res.lock"
    owner.acquired = False
    owner._asyncio_lock = asyncio.Lock()

    acquired = await owner.acquire()
    assert acquired is True
    assert owner.acquired is True
    assert owner._lock_path.exists()

    # Lock file should contain valid JSON with our PID
    data = json.loads(owner._lock_path.read_text())
    assert data["pid"] == os.getpid()
    assert data["ttl"] == 300

    owner.release()
    assert owner.acquired is False
    assert not owner._lock_path.exists()


@pytest.mark.asyncio
async def test_context_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.shared.queue_owner as qo_mod

    monkeypatch.setattr(qo_mod, "LOCK_DIR", tmp_path)

    owner = QueueOwner.__new__(QueueOwner)
    owner._name = "ctx-res"
    owner._ttl = 300
    owner._lock_path = tmp_path / "ctx-res.lock"
    owner.acquired = False
    owner._asyncio_lock = asyncio.Lock()

    async with owner as o:
        assert o.acquired is True

    assert owner.acquired is False


@pytest.mark.asyncio
async def test_second_acquire_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.shared.queue_owner as qo_mod

    monkeypatch.setattr(qo_mod, "LOCK_DIR", tmp_path)

    def make(name: str) -> QueueOwner:
        o = QueueOwner.__new__(QueueOwner)
        o._name = name
        o._ttl = 300
        o._lock_path = tmp_path / f"{name}.lock"
        o.acquired = False
        o._asyncio_lock = asyncio.Lock()
        return o

    first = make("shared-res")
    second = make("shared-res")

    await first.acquire()
    assert first.acquired is True

    result = await second.acquire()
    assert result is False
    assert second.acquired is False

    first.release()


# ---------------------------------------------------------------------------
# 2. Stale lock detection — dead PID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_dead_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.shared.queue_owner as qo_mod

    monkeypatch.setattr(qo_mod, "LOCK_DIR", tmp_path)

    lock_path = tmp_path / "stale-res.lock"

    # Write a lock file with a PID that cannot exist (very high number)
    dead_pid = 999999999
    stale_data = {
        "pid": dead_pid,
        "acquired_at": datetime.now(UTC).isoformat(),
        "ttl": 300,
    }
    lock_path.write_text(json.dumps(stale_data))

    owner = QueueOwner.__new__(QueueOwner)
    owner._name = "stale-res"
    owner._ttl = 300
    owner._lock_path = lock_path
    owner.acquired = False
    owner._asyncio_lock = asyncio.Lock()

    acquired = await owner.acquire()
    assert acquired is True, "Should reclaim stale lock from dead PID"
    owner.release()


# ---------------------------------------------------------------------------
# 3. TTL expiration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_ttl_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.shared.queue_owner as qo_mod

    monkeypatch.setattr(qo_mod, "LOCK_DIR", tmp_path)

    lock_path = tmp_path / "ttl-res.lock"

    # Write a lock whose acquired_at is far in the past with TTL=1
    ancient_time = "2000-01-01T00:00:00+00:00"
    stale_data = {"pid": os.getpid(), "acquired_at": ancient_time, "ttl": 1}
    lock_path.write_text(json.dumps(stale_data))

    owner = QueueOwner.__new__(QueueOwner)
    owner._name = "ttl-res"
    owner._ttl = 300
    owner._lock_path = lock_path
    owner.acquired = False
    owner._asyncio_lock = asyncio.Lock()

    acquired = await owner.acquire()
    assert acquired is True, "Should reclaim TTL-expired lock"
    owner.release()
