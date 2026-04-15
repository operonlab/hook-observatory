"""CLI dictionary auto-updater — update entry .py files on version drift."""

from __future__ import annotations

import re
from pathlib import Path

from cli_rosetta.probe import ProbeReport

_ENTRY_DIR = Path(__file__).parent

# Map canonical CLI name → entry file name
_ENTRY_FILES = {
    "claude-code": "claude_code.py",
    "codex-cli": "codex_cli.py",
    "copilot-cli": "copilot_cli.py",
    "gemini-cli": "gemini_cli.py",
    "qwen-code": "qwen_code.py",
}


def update_known_version(cli_name: str, new_version: str) -> bool:
    """Update known_version in the entry .py file. Returns True if changed."""
    filename = _ENTRY_FILES.get(cli_name)
    if not filename:
        return False

    filepath = _ENTRY_DIR / filename
    if not filepath.exists():
        return False

    content = filepath.read_text()
    pattern = r'known_version="[^"]*"'
    replacement = f'known_version="{new_version}"'

    new_content, count = re.subn(pattern, replacement, content)
    if count == 0:
        return False

    filepath.write_text(new_content)
    return True


def apply_probe_report(report: ProbeReport) -> dict:
    """Apply probe results. Auto-updates version, flags pending review.

    Returns {updated: [...], pending: [...]}.
    """
    result = {"updated": [], "pending": []}

    # Auto-update known_version (safe — just a record)
    if update_known_version(report.cli_name, report.new_version):
        result["updated"].append(f"known_version: {report.old_version} → {report.new_version}")

    # Flag changes → pending review (needs human/LLM judgment)
    if report.help_diff and report.help_diff.has_changes:
        if report.help_diff.new_flags:
            result["pending"].append(
                {
                    "field": "new_flags",
                    "detail": sorted(report.help_diff.new_flags),
                }
            )
        if report.help_diff.removed_flags:
            result["pending"].append(
                {
                    "field": "removed_flags",
                    "detail": sorted(report.help_diff.removed_flags),
                }
            )

    return result
