"""Homebrew collector — formulae and casks."""

from __future__ import annotations

import shutil
import subprocess


def _run(cmd: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _brew_available() -> bool:
    return shutil.which("brew") is not None


def collect_formulae() -> dict:
    if not _brew_available():
        return {"available": False, "packages": []}

    out = _run(["brew", "list", "--formulae", "--versions"])
    packages = []
    for line in out.splitlines():
        parts = line.split()
        if parts:
            name = parts[0]
            version = parts[1] if len(parts) > 1 else ""
            packages.append({"name": name, "version": version})

    return {
        "available": True,
        "count": len(packages),
        "packages": packages,
    }


def collect_casks() -> dict:
    if not _brew_available():
        return {"available": False, "packages": []}

    out = _run(["brew", "list", "--cask", "--versions"])
    packages = []
    for line in out.splitlines():
        parts = line.split()
        if parts:
            name = parts[0]
            version = parts[1] if len(parts) > 1 else ""
            packages.append({"name": name, "version": version})

    return {
        "available": True,
        "count": len(packages),
        "packages": packages,
    }
