"""Walk an Obsidian vault and yield markdown files, with hashing matching docvault server."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".obsidian",
    ".git",
    ".trash",
    "node_modules",
    ".DS_Store",
    "assets",
})


def walk_vault(vault_path: Path) -> Iterator[Path]:
    """Yield .md files under vault_path, skipping Obsidian internals and asset folders.

    Order is sorted by relative path (stable across runs for deterministic dry-run output).
    """
    vault_path = Path(vault_path).resolve()
    if not vault_path.is_dir():
        raise NotADirectoryError(f"vault path is not a directory: {vault_path}")

    candidates: list[Path] = []
    for path in vault_path.rglob("*.md"):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(vault_path).parts):
            continue
        if path.is_file():
            candidates.append(path)
    candidates.sort(key=lambda p: p.relative_to(vault_path).as_posix())
    yield from candidates


def compute_hash(path: Path) -> str:
    """Compute the 16-hex-char SHA-256 prefix matching docvault server-side hashing.

    Mirrors core/src/modules/docvault/routes.py: hashlib.sha256(bytes).hexdigest()[:16].
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
