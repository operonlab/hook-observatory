"""File-based fallback for Agent Metrics — atomic write to /tmp."""

from __future__ import annotations

import json
import os
import tempfile

import structlog

from .config import settings

log = structlog.get_logger()


def write_fallback(data: dict) -> None:
    """Atomically write current state to the fallback file."""
    try:
        parent = os.path.dirname(settings.FALLBACK_PATH)
        fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".agent-metrics-", suffix=".tmp")
        try:
            os.write(fd, json.dumps(data).encode())
            os.close(fd)
            os.rename(tmp_path, settings.FALLBACK_PATH)
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except Exception:
        log.warning("file_fallback_write_failed", exc_info=True)


def read_fallback() -> dict | None:
    """Read current state from the fallback file."""
    try:
        with open(settings.FALLBACK_PATH) as f:
            return json.loads(f.read())
    except Exception:
        return None
