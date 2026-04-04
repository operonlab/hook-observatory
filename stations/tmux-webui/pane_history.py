"""Pane snapshot store for alt-screen scrollback history.

When a pane is in alternate screen mode (TUI apps like Claude Code, vim,
Gemini CLI, htop, etc.), normal scrollback is unavailable. This module
stores periodic snapshots of unique screen states, allowing users to
scroll through previous screen content in tmux-webui.

No external dependencies — uses only stdlib.
"""

import hashlib
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Snapshot:
    content: str
    content_hash: str
    timestamp: float


class PaneSnapshotStore:
    """Per-pane snapshot history with content-hash deduplication."""

    def __init__(self, max_snapshots: int = 200):
        self._max = max_snapshots
        self._stores: dict[str, deque[Snapshot]] = {}

    def add(self, pane_id: str, content: str) -> bool:
        """Add snapshot if content differs from most recent. Returns True if stored."""
        h = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
        store = self._stores.setdefault(pane_id, deque(maxlen=self._max))
        if store and store[-1].content_hash == h:
            return False
        store.append(Snapshot(content=content, content_hash=h, timestamp=time.time()))
        return True

    def get(self, pane_id: str, offset: int = 0) -> Snapshot | None:
        """Get snapshot at offset from most recent (0=latest, 1=previous, etc.)."""
        store = self._stores.get(pane_id)
        if not store:
            return None
        idx = len(store) - 1 - offset
        if idx < 0:
            return None
        return store[idx]

    def total(self, pane_id: str) -> int:
        store = self._stores.get(pane_id)
        return len(store) if store else 0

    def clear(self, pane_id: str) -> None:
        self._stores.pop(pane_id, None)
