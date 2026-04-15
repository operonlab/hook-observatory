"""CLI dictionary probe — version drift detection + --help diff.

Checks remote registries (npm, brew) for latest versions, compares with
local installed versions and cli-rosetta known_version. On drift, parses
--help output to detect flag changes.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass, field

from cli_rosetta.base import CLIEntry
from cli_rosetta.registry import list_entries


@dataclass
class VersionInfo:
    """Version comparison for a single CLI."""

    cli_name: str
    installed: str = ""
    remote: str = ""
    known: str = ""  # from cli-rosetta entry

    @property
    def has_drift(self) -> bool:
        """True if installed != remote (update available)."""
        return bool(self.installed and self.remote and self.installed != self.remote)

    @property
    def entry_stale(self) -> bool:
        """True if cli-rosetta known_version != installed."""
        return bool(self.known and self.installed and self.known != self.installed)


@dataclass
class HelpDiff:
    """Diff of --help flags between previous snapshot and current binary.

    Compares against saved help snapshot (state.json), not cli-rosetta entry fields.
    This avoids false positives from alias flags and subcommand-only flags.
    """

    cli_name: str
    previous_flags: set[str] = field(default_factory=set)
    current_flags: set[str] = field(default_factory=set)

    @property
    def new_flags(self) -> set[str]:
        if not self.previous_flags:
            return set()  # First run — no baseline to diff against
        return self.current_flags - self.previous_flags

    @property
    def removed_flags(self) -> set[str]:
        if not self.previous_flags:
            return set()
        return self.previous_flags - self.current_flags

    @property
    def has_changes(self) -> bool:
        return bool(self.new_flags or self.removed_flags)


@dataclass
class ProbeReport:
    """Full probe result for a CLI."""

    cli_name: str
    old_version: str
    new_version: str
    help_diff: HelpDiff | None = None
    changelog_url: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        d = {
            "cli_name": self.cli_name,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "changelog_url": self.changelog_url,
        }
        if self.help_diff and self.help_diff.has_changes:
            d["new_flags"] = sorted(self.help_diff.new_flags)
            d["removed_flags"] = sorted(self.help_diff.removed_flags)
        if self.notes:
            d["notes"] = self.notes
        return d


# ── Remote version lookup ──


def _npm_latest(package: str) -> str:
    """Fetch latest version from npm registry."""
    url = f"https://registry.npmjs.org/{package}/latest"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("version", "")
    except Exception:
        return ""


def _brew_latest(package: str) -> str:
    """Fetch latest version from Homebrew."""
    try:
        r = subprocess.run(
            ["brew", "info", "--json=v2", package],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return ""
        data = json.loads(r.stdout)
        formulae = data.get("formulae", [])
        casks = data.get("casks", [])
        if formulae:
            return formulae[0].get("versions", {}).get("stable", "")
        if casks:
            return casks[0].get("version", "")
        return ""
    except Exception:
        return ""


def check_remote_version(entry: CLIEntry) -> str:
    """Check the latest remote version for a CLI entry."""
    if entry.npm_package:
        return _npm_latest(entry.npm_package)
    if entry.brew_package:
        return _brew_latest(entry.brew_package)
    return ""


def check_all_versions() -> list[VersionInfo]:
    """Check installed + remote versions for all CLIs."""
    from cli_rosetta.health import check_one

    results = []
    for entry in list_entries():
        health = check_one(entry)
        remote = check_remote_version(entry)
        results.append(
            VersionInfo(
                cli_name=entry.name,
                installed=health.current_version,
                remote=remote,
                known=entry.known_version,
            )
        )
    return results


# ── --help flag parsing ──

_FLAG_PATTERN = re.compile(r"--([a-z][a-z0-9-]+)")


def parse_help_flags(binary: str) -> set[str]:
    """Run {binary} --help and extract all --flag-name patterns."""
    try:
        r = subprocess.run(
            [binary, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return set(_FLAG_PATTERN.findall(r.stdout + r.stderr))
    except Exception:
        return set()


def probe_help(entry: CLIEntry, previous_flags: set[str] | None = None) -> HelpDiff:
    """Run --help and diff against previous snapshot.

    Args:
        entry: CLI entry to probe.
        previous_flags: Flags from last snapshot (state.json). None = first run.
    """
    current = parse_help_flags(entry.binary)
    return HelpDiff(
        cli_name=entry.name,
        previous_flags=previous_flags or set(),
        current_flags=current,
    )


# ── Full probe ──

_CHANGELOG_URLS = {
    "claude-code": "https://github.com/anthropics/claude-code/releases",
    "codex-cli": "https://github.com/openai/codex/releases",
    "gemini-cli": "https://github.com/google-gemini/gemini-cli/releases",
    "qwen-code": "https://github.com/nicepkg/qwen-code/releases",
    "copilot-cli": "https://github.com/github/copilot-cli/releases",
}


def probe_cli(
    entry: CLIEntry, new_version: str, *, previous_flags: set[str] | None = None
) -> ProbeReport:
    """Full probe: help diff + changelog URL.

    Args:
        previous_flags: Flags from last snapshot (state.json). None = first run, no diff.
    """
    help_diff = probe_help(entry, previous_flags=previous_flags)
    changelog = _CHANGELOG_URLS.get(entry.name, "")

    notes_parts = []
    if help_diff.new_flags:
        notes_parts.append(f"New flags: {', '.join(sorted(help_diff.new_flags))}")
    if help_diff.removed_flags:
        notes_parts.append(f"Removed flags: {', '.join(sorted(help_diff.removed_flags))}")

    return ProbeReport(
        cli_name=entry.name,
        old_version=entry.known_version,
        new_version=new_version,
        help_diff=help_diff,
        changelog_url=changelog,
        notes="; ".join(notes_parts),
    )
