"""Scan ~/.claude/projects/ to extract session metadata from JSONL files.

Walks all JSONL files and archived stubs, extracting metadata into
SessionMeta dataclasses for downstream scoring and archival.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog

from session_archiver.config import Config
from session_archiver.models import SessionMeta

log = structlog.get_logger(__name__)


def scan_sessions(config: Config) -> list[SessionMeta]:
    """Scan all sessions under the configured projects directory.

    Returns a list of SessionMeta for every discoverable session:
    - Live JSONL files (tier=hot)
    - Archived stubs (.archived.json, tier=cold)
    """
    projects_dir = Path(config.projects_dir)
    if not projects_dir.is_dir():
        log.warning("projects_dir_not_found", path=str(projects_dir))
        return []

    results: list[SessionMeta] = []

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        project_path = project_dir.name  # e.g. "-Users-joneshong-workshop"

        # Pass 1: Live JSONL files
        for jsonl_path in sorted(project_dir.glob("*.jsonl")):
            meta = _scan_jsonl(jsonl_path, project_path)
            if meta is not None:
                results.append(meta)

        # Pass 2: Archived stubs (.archived.json)
        for stub_path in sorted(project_dir.glob("*.archived.json")):
            meta = _parse_archived_stub(stub_path, project_path)
            if meta is not None:
                results.append(meta)

    log.info(
        "scan_complete",
        total=len(results),
        live=sum(1 for m in results if m.companion_path is not None or m.file_size_bytes > 0),
        archived=sum(1 for m in results if _is_cold(m)),
    )
    return results


def _is_cold(meta: SessionMeta) -> bool:
    """Check if a session meta represents a cold/archived session."""
    # Archived stubs have file_size_bytes from the original, but the jsonl_path
    # points to the stub, not a real JSONL.  We detect them by the .archived.json suffix.
    return str(meta.jsonl_path).endswith(".archived.json")


# ---------------------------------------------------------------------------
# JSONL scanning
# ---------------------------------------------------------------------------


def _scan_jsonl(jsonl_path: Path, project_path: str) -> SessionMeta | None:
    """Extract metadata from a single JSONL session file.

    Reads the file line-by-line (streaming) to avoid loading large files into
    memory.  The first and last lines are parsed for timestamps; intermediate
    lines are only inspected for type counting.
    """
    try:
        stat = jsonl_path.stat()
    except OSError:
        log.warning("stat_failed", path=str(jsonl_path))
        return None

    if stat.st_size == 0:
        log.debug("empty_jsonl", path=str(jsonl_path))
        return None

    # Derive session_id from filename stem (UUID)
    session_id_from_name = jsonl_path.stem

    # Companion directory: same name without .jsonl extension
    companion_dir = jsonl_path.with_suffix("")
    has_companion = companion_dir.is_dir()
    companion_size = _dir_size(companion_dir) if has_companion else 0

    # Extract metadata by streaming through the file
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    session_id: str | None = None
    claude_version: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    event_count = 0
    turn_count = 0
    user_event_bytes = 0
    metadata_extracted = False

    try:
        # Read last line efficiently by seeking from the end
        last_line_data = _read_last_line(jsonl_path)
        if last_line_data is not None:
            last_timestamp = last_line_data.get("timestamp")

        # Stream through all lines for counting + metadata extraction
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue

                event_count += 1

                try:
                    event = json.loads(stripped)
                except (json.JSONDecodeError, ValueError):
                    log.warning(
                        "malformed_jsonl_line",
                        path=str(jsonl_path),
                        line_num=event_count,
                    )
                    continue

                # Extract metadata from the first event that has sessionId
                if not metadata_extracted:
                    sid = event.get("sessionId")
                    if sid:
                        session_id = sid
                        claude_version = event.get("version")
                        cwd = event.get("cwd")
                        git_branch = event.get("gitBranch")
                        metadata_extracted = True

                # Capture first timestamp from the first event that has one
                if first_timestamp is None:
                    ts = event.get("timestamp")
                    if ts:
                        first_timestamp = ts

                # Count user events and their byte sizes
                if event.get("type") == "user":
                    turn_count += 1
                    user_event_bytes += len(line.encode("utf-8"))

    except OSError as exc:
        log.warning("read_failed", path=str(jsonl_path), error=str(exc))
        return None

    # Fallback: use filename stem if no sessionId found in file content
    if not session_id:
        session_id = session_id_from_name

    last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    return SessionMeta(
        session_id=session_id,
        project_path=project_path,
        jsonl_path=jsonl_path,
        file_size_bytes=stat.st_size,
        event_count=event_count,
        turn_count=turn_count,
        has_companion=has_companion,
        companion_path=companion_dir if has_companion else None,
        companion_size=companion_size,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        last_modified=last_modified,
        claude_version=claude_version,
        git_branch=git_branch,
        cwd=cwd,
        user_event_bytes=user_event_bytes,
    )


def _read_last_line(path: Path) -> dict | None:
    """Read and parse the last non-empty line of a file without loading the
    entire file into memory.

    Seeks backwards from EOF to find the last newline, then reads forward.
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()

            if file_size == 0:
                return None

            # Start from the end, skip trailing newlines
            pos = file_size - 1
            while pos > 0:
                f.seek(pos)
                byte = f.read(1)
                if byte != b"\n" and byte != b"\r":
                    break
                pos -= 1

            if pos == 0:
                # Entire file might be one line
                f.seek(0)
                raw = f.readline()
            else:
                # Walk backwards to find start of last line
                while pos > 0:
                    f.seek(pos)
                    byte = f.read(1)
                    if byte == b"\n":
                        # pos+1 is start of the last line
                        break
                    pos -= 1

                if pos == 0:
                    f.seek(0)
                else:
                    f.seek(pos + 1)

                raw = f.readline()

            line = raw.decode("utf-8").strip()
            if not line:
                return None

            return json.loads(line)

    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.debug("last_line_read_failed", path=str(path), error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Archived stub parsing
# ---------------------------------------------------------------------------


def _parse_archived_stub(stub_path: Path, project_path: str) -> SessionMeta | None:
    """Parse a .archived.json stub into a SessionMeta with cold-tier info.

    Stub format (as defined in SPEC):
    {
        "_type": "archived-session",
        "sessionId": "0b65102b-...",
        "tier": "cold",
        ...
    }
    """
    try:
        with open(stub_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("stub_parse_failed", path=str(stub_path), error=str(exc))
        return None

    if data.get("_type") != "archived-session":
        log.debug("not_archived_stub", path=str(stub_path))
        return None

    session_id = data.get("sessionId")
    if not session_id:
        log.warning("stub_missing_session_id", path=str(stub_path))
        return None

    # Parse archivedAt as last_modified
    archived_at_str = data.get("archivedAt")
    if archived_at_str:
        try:
            last_modified = datetime.fromisoformat(archived_at_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            last_modified = datetime.now(tz=timezone.utc)
    else:
        last_modified = datetime.now(tz=timezone.utc)

    return SessionMeta(
        session_id=session_id,
        project_path=project_path,
        jsonl_path=stub_path,
        file_size_bytes=data.get("originalSize", 0),
        event_count=data.get("eventCount", 0),
        turn_count=data.get("turnCount", 0),
        has_companion=False,
        companion_path=None,
        companion_size=0,
        first_timestamp=data.get("firstTimestamp"),
        last_timestamp=data.get("lastTimestamp"),
        last_modified=last_modified,
        claude_version=None,
        git_branch=None,
        cwd=None,
        user_event_bytes=0,
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _dir_size(path: Path) -> int:
    """Calculate total size of a directory recursively."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except OSError as exc:
        log.debug("dir_size_failed", path=str(path), error=str(exc))
    return total
