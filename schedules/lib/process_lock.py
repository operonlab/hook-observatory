"""Robust single-instance lock with PID-based stale detection.

Usage (at the bottom of any runner script):

    if __name__ == "__main__":
        from lib.process_lock import acquire_or_exit
        acquire_or_exit()
        main()

Features:
  - Writes PID to lock file for stale-lock detection
  - Auto-cleanup via atexit + SIGTERM handler
  - If holding process is dead, forces lock re-acquisition
"""

from __future__ import annotations

import atexit
import fcntl
import os
import signal
import sys
from pathlib import Path

_lock_fd = None
_lock_path: str | None = None


def acquire_or_exit(name: str | None = None) -> None:
    """Acquire a file lock or exit if another live instance holds it.

    Args:
        name: Lock file basename (default: caller script stem).
              Lock created at /tmp/{name}.lock
    """
    global _lock_fd, _lock_path

    if name is None:
        # Derive from the __main__ script filename
        import __main__

        name = Path(getattr(__main__, "__file__", "unknown")).stem

    _lock_path = f"/tmp/{name}.lock"
    _lock_fd = open(_lock_path, "w")

    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # Check if the holding process is still alive
        try:
            with open(_lock_path) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # signal 0 = existence check
            print(f"[SKIP] Another instance (PID {old_pid}) still running (lock: {_lock_path})")
            sys.exit(0)
        except (ValueError, ProcessLookupError, FileNotFoundError, PermissionError):
            # Stale lock — force re-acquire
            print(f"[WARN] Stale lock detected, forcing acquisition (lock: {_lock_path})")
            _lock_fd.close()
            _lock_fd = open(_lock_path, "w")
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    # Write PID for stale-lock detection by future instances
    _lock_fd.write(str(os.getpid()))
    _lock_fd.flush()

    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # triggers atexit


def _cleanup() -> None:
    try:
        if _lock_fd is not None and not _lock_fd.closed:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        if _lock_path is not None:
            os.unlink(_lock_path)
    except OSError:
        pass
