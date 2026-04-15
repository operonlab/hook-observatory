"""CLI dictionary state management — version tracking + pending review."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "data" / "cli-rosetta"
STATE_FILE = STATE_DIR / "state.json"


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    """Load state from disk. Returns empty dict if no state file."""
    if not STATE_FILE.exists():
        return {"versions": {}, "pending_review": []}
    return json.loads(STATE_FILE.read_text())


def save(state: dict) -> None:
    """Save state to disk."""
    _ensure_dir()
    state["last_check"] = datetime.now(UTC).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def update_version(
    state: dict,
    cli_name: str,
    *,
    installed: str = "",
    remote: str = "",
    help_flags: set[str] | None = None,
) -> None:
    """Update version info for a CLI in state."""
    versions = state.setdefault("versions", {})
    entry = versions.setdefault(cli_name, {})
    if installed:
        entry["installed"] = installed
    if remote:
        entry["remote"] = remote
    if help_flags is not None:
        entry["help_flags"] = sorted(help_flags)
    entry["checked_at"] = datetime.now(UTC).isoformat()


def get_help_flags(state: dict, cli_name: str) -> set[str] | None:
    """Get previously saved help flags for a CLI. Returns None if no snapshot."""
    entry = state.get("versions", {}).get(cli_name, {})
    flags = entry.get("help_flags")
    if flags is None:
        return None
    return set(flags)


def add_pending_review(state: dict, cli_name: str, field: str, old: str, new: str) -> None:
    """Add a pending review item for human/LLM judgment."""
    pending = state.setdefault("pending_review", [])
    pending.append(
        {
            "cli": cli_name,
            "field": field,
            "old": old,
            "new": new,
            "detected_at": datetime.now(UTC).isoformat(),
        }
    )


def get_drifted(state: dict) -> list[tuple[str, str, str]]:
    """Return list of (cli_name, installed, remote) where versions differ."""
    drifted = []
    for name, info in state.get("versions", {}).items():
        installed = info.get("installed", "")
        remote = info.get("remote", "")
        if installed and remote and installed != remote:
            drifted.append((name, installed, remote))
    return drifted
