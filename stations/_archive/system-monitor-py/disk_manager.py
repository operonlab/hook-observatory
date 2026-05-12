"""
Disk Manager — safe disk operations for system-monitor station.

Provides validated delete, cache-clean, and trash-empty operations
with 6-layer path safety checks (ported from V1 disk-report server.py).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

HOME_DIR = str(Path.home())
TRASH_DIR = os.path.join(HOME_DIR, ".Trash")

# Paths that must NEVER be deleted
PROTECTED_PREFIXES = (
    "/System",
    "/Library",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/private",
    "/etc",
    "/tmp",
)

PROTECTED_HOME_DIRS = [
    os.path.join(HOME_DIR, d)
    for d in (
        ".claude",
        ".ssh",
        ".gnupg",
        "Library/Application Support",
    )
]


class DiskManager:
    """Safe disk operations with multi-layer path validation."""

    def validate_path(self, path: str) -> str | None:
        """Return an error message if *path* is not safe to delete, else None."""
        if not os.path.isabs(path):
            return "Path must be absolute"

        resolved = os.path.realpath(path)

        # Must be under user home
        user_prefix = os.path.join("/Users", os.path.basename(HOME_DIR), "")
        if not resolved.startswith(user_prefix) and resolved != user_prefix.rstrip("/"):
            return f"Path must be under {user_prefix}"

        # System path blacklist
        for prefix in PROTECTED_PREFIXES:
            if resolved.startswith(prefix):
                return f"Cannot delete system path: {prefix}"

        # Sensitive home directories
        for protected in PROTECTED_HOME_DIRS:
            prot_resolved = os.path.realpath(protected)
            if resolved == prot_resolved or resolved.startswith(prot_resolved + "/"):
                return f"Cannot delete protected path: {protected}"

        # .app bundle protection
        if ".app/" in resolved or resolved.endswith(".app"):
            return "Cannot delete .app bundles or their contents"

        return None

    def delete_file(self, path: str, file_type: str) -> dict:
        """Delete a file or directory after validation.

        Args:
            path: Absolute path to delete.
            file_type: "file" or "directory".

        Returns:
            dict with status, freed_bytes, and path.

        Raises:
            ValueError: If path fails validation.
            FileNotFoundError: If path does not exist.
        """
        error = self.validate_path(path)
        if error:
            raise ValueError(error)

        if not os.path.exists(path):
            raise FileNotFoundError(f"Path not found: {path}")

        if file_type == "file":
            freed = _file_size(path)
            os.remove(path)
        else:
            freed = _dir_size(path)
            shutil.rmtree(path)

        logger.info("Deleted %s (%d bytes): %s", file_type, freed, path)
        return {"status": "deleted", "freed_bytes": freed, "path": path}

    def clean_cache_dir(self, path: str) -> dict:
        """Remove all contents of a cache directory (preserving the dir itself).

        Returns:
            dict with freed_bytes and warnings list.
        """
        error = self.validate_path(path)
        if error:
            raise ValueError(error)

        if not os.path.isdir(path):
            raise FileNotFoundError(f"Directory not found: {path}")

        freed = 0
        warnings: list[str] = []

        for entry in os.scandir(path):
            try:
                if entry.is_dir(follow_symlinks=False):
                    size = _dir_size(entry.path)
                    shutil.rmtree(entry.path)
                else:
                    size = entry.stat(follow_symlinks=False).st_size
                    os.remove(entry.path)
                freed += size
            except OSError as e:
                if len(warnings) < 10:
                    warnings.append(f"{entry.name}: {e}")

        logger.info("Cleaned cache dir (%d bytes freed): %s", freed, path)
        return {"status": "cleaned", "freed_bytes": freed, "path": path, "warnings": warnings}

    def empty_trash(self) -> dict:
        """Empty ~/.Trash directory.

        Returns:
            dict with freed_bytes.
        """
        if not os.path.isdir(TRASH_DIR):
            return {"status": "ok", "freed_bytes": 0, "message": "Trash is empty"}

        freed = 0
        warnings: list[str] = []

        for entry in os.scandir(TRASH_DIR):
            try:
                if entry.is_dir(follow_symlinks=False):
                    size = _dir_size(entry.path)
                    shutil.rmtree(entry.path)
                else:
                    size = entry.stat(follow_symlinks=False).st_size
                    os.remove(entry.path)
                freed += size
            except OSError as e:
                if len(warnings) < 10:
                    warnings.append(f"{entry.name}: {e}")

        logger.info("Emptied trash (%d bytes freed)", freed)
        return {"status": "emptied", "freed_bytes": freed, "warnings": warnings}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _dir_size(path: str) -> int:
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    return total
