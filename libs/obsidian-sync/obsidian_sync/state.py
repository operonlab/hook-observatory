"""Per-vault sync state — content_hash incremental + flock for concurrent-run safety.

State file shape:
{
  "version": 1,
  "vault_path": "/abs/path/to/vault",
  "space_id": "obsidian-blog",
  "entries": {
    "<rel_path>": {
      "hash": "abcd1234...",
      "document_id": "019e...",
      "last_synced_at": "2026-05-15T20:30:00"
    }
  }
}
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


@contextmanager
def _flock_exclusive(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class State:
    def __init__(self, path: Path, data: dict[str, Any]):
        self.path = Path(path)
        self._data = data

    @classmethod
    def load(cls, path: Path, vault_path: Path, space_id: str) -> "State":
        path = Path(path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            data = {
                "version": SCHEMA_VERSION,
                "vault_path": str(Path(vault_path).resolve()),
                "space_id": space_id,
                "entries": {},
            }
        else:
            data.setdefault("entries", {})
            data["vault_path"] = str(Path(vault_path).resolve())
            data["space_id"] = space_id
        return cls(path, data)

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        return self._data["entries"]

    def is_changed(self, rel_path: str, current_hash: str) -> bool:
        prev = self.entries.get(rel_path)
        return prev is None or prev.get("hash") != current_hash

    def record(self, rel_path: str, content_hash: str, document_id: str) -> None:
        self.entries[rel_path] = {
            "hash": content_hash,
            "document_id": document_id,
            "last_synced_at": datetime.now().isoformat(timespec="seconds"),
        }

    def forget(self, rel_path: str) -> str | None:
        prev = self.entries.pop(rel_path, None)
        return prev["document_id"] if prev else None

    def known_rel_paths(self) -> set[str]:
        return set(self.entries.keys())

    def save(self) -> None:
        with _flock_exclusive(self.path.with_suffix(self.path.suffix + ".lock")):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                prefix=self.path.name + ".",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
