"""Applications collector — scan /Applications/ for GUI apps."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _get_app_version(app_path: Path) -> str:
    """Read version from Info.plist."""
    plist = app_path / "Contents" / "Info.plist"
    if not plist.exists():
        return ""
    # Use PlistBuddy to read version
    ver = _run(f'/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "{plist}" 2>/dev/null')
    return ver


def collect() -> dict:
    apps_dir = Path("/Applications")
    apps = []

    if apps_dir.is_dir():
        for entry in sorted(apps_dir.iterdir()):
            if entry.suffix == ".app" and entry.is_dir():
                name = entry.stem
                version = _get_app_version(entry)
                apps.append({"name": name, "version": version})

        # Also scan subdirectories (e.g., /Applications/Utilities/)
        utilities = apps_dir / "Utilities"
        if utilities.is_dir():
            for entry in sorted(utilities.iterdir()):
                if entry.suffix == ".app" and entry.is_dir():
                    name = f"Utilities/{entry.stem}"
                    version = _get_app_version(entry)
                    apps.append({"name": name, "version": version})

    # Mac App Store apps (mas)
    mas_apps = []
    mas_out = _run("mas list 2>/dev/null")
    if mas_out:
        for line in mas_out.splitlines():
            parts = line.split(None, 2)
            if len(parts) >= 2:
                app_id = parts[0]
                # Name is everything after the ID and version
                rest = " ".join(parts[1:])
                # Format: ID Name (version)
                name = rest.rsplit("(", 1)[0].strip() if "(" in rest else rest
                version = rest.rsplit("(", 1)[1].rstrip(")") if "(" in rest else ""
                mas_apps.append({"id": app_id, "name": name, "version": version})

    return {
        "applications": apps,
        "app_count": len(apps),
        "mas_apps": mas_apps,
        "mas_count": len(mas_apps),
    }
