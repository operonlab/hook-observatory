"""CLI health check — version detection + staleness check."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from cli_dic.base import CLIEntry
from cli_dic.registry import list_entries


@dataclass
class HealthResult:
    """Result of a CLI health check."""

    entry: CLIEntry
    installed: bool
    path: str
    current_version: str
    outdated: bool

    @property
    def status(self) -> str:
        if not self.installed:
            return "not_installed"
        if self.outdated:
            return "outdated"
        return "ok"


def check_one(entry: CLIEntry) -> HealthResult:
    """Check a single CLI tool's health."""
    path = shutil.which(entry.binary) or ""
    if not path:
        return HealthResult(
            entry=entry, installed=False, path="", current_version="", outdated=False
        )

    current_version = ""
    try:
        r = subprocess.run(
            [entry.binary, entry.version_flag],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = r.stdout.strip() or r.stderr.strip()
        match = re.search(entry.version_pattern, output)
        if match:
            current_version = match.group(0)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    outdated = bool(
        entry.known_version and current_version and current_version != entry.known_version
    )

    return HealthResult(
        entry=entry,
        installed=True,
        path=path,
        current_version=current_version,
        outdated=outdated,
    )


def check_all() -> list[HealthResult]:
    """Check all registered CLI tools."""
    return [check_one(e) for e in list_entries()]
