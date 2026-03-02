#!/usr/bin/env python3
"""
Scheduler — manages launchd LaunchAgent for periodic LLM usage collection.

Replaces V1's Node.js-based LaunchAgent with a Python unified collector.

Usage:
    python3 scheduler.py install    # Generate + load launchd plist
    python3 scheduler.py uninstall  # Unload + remove plist
    python3 scheduler.py status     # Show schedule status
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"
LABEL = "com.workshop.llm-usage"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


class Scheduler:
    """Manages launchd LaunchAgent for periodic collection."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or _load_config()
        coll = self.config.get("collection", {})
        self.interval = coll.get("interval_seconds", 1800)
        self.python = self._find_python()
        self.collector_script = SCRIPT_DIR / "collector.py"
        self.log_dir = Path.home() / ".claude" / "data" / "llm-usage" / "logs"

    def install(self) -> None:
        """Generate and load the LaunchAgent plist."""
        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        plist = {
            "Label": LABEL,
            "ProgramArguments": [
                self.python,
                str(self.collector_script),
                "--compact",
            ],
            "StartInterval": self.interval,
            "WorkingDirectory": str(SCRIPT_DIR),
            "StandardOutPath": str(self.log_dir / "stdout.log"),
            "StandardErrorPath": str(self.log_dir / "stderr.log"),
            "EnvironmentVariables": self._collect_env_vars(),
            "RunAtLoad": True,
            "ProcessType": "Background",
        }

        # Write plist
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PLIST_PATH, "wb") as f:
            plistlib.dump(plist, f)

        print(f"Plist written: {PLIST_PATH}")

        # Unload first if already loaded (ignore errors)
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True,
        )

        # Load
        result = subprocess.run(
            ["launchctl", "load", str(PLIST_PATH)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"LaunchAgent loaded: {LABEL}")
            print(f"  Interval: every {self.interval}s ({self.interval // 60} min)")
            print(f"  Python: {self.python}")
            print(f"  Logs: {self.log_dir}")
        else:
            print(f"Failed to load: {result.stderr}", file=sys.stderr)
            sys.exit(1)

    def uninstall(self) -> None:
        """Unload and remove the LaunchAgent plist."""
        if not PLIST_PATH.exists():
            print(f"Plist not found: {PLIST_PATH}")
            return

        result = subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"LaunchAgent unloaded: {LABEL}")
        else:
            print(f"Unload warning: {result.stderr}", file=sys.stderr)

        PLIST_PATH.unlink(missing_ok=True)
        print(f"Plist removed: {PLIST_PATH}")

    def status(self) -> dict:
        """Query schedule status."""
        info = {
            "label": LABEL,
            "plist_exists": PLIST_PATH.exists(),
            "plist_path": str(PLIST_PATH),
            "interval_seconds": self.interval,
            "interval_minutes": self.interval // 60,
            "python": self.python,
            "collector_script": str(self.collector_script),
            "loaded": False,
            "pid": None,
        }

        # Check if loaded via launchctl
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if LABEL in line:
                info["loaded"] = True
                parts = line.split()
                if parts and parts[0] != "-":
                    try:
                        info["pid"] = int(parts[0])
                    except ValueError:
                        pass
                break

        # Check log files
        stdout_log = self.log_dir / "stdout.log"
        stderr_log = self.log_dir / "stderr.log"
        if stdout_log.exists():
            info["stdout_log_size"] = stdout_log.stat().st_size
        if stderr_log.exists():
            info["stderr_log_size"] = stderr_log.stat().st_size

        return info

    def _find_python(self) -> str:
        """Find the best Python 3 interpreter."""
        # Prefer uv-managed python
        uv_python = os.path.expanduser("~/.local/bin/python3")
        if os.path.exists(uv_python):
            return uv_python
        # Fallback to system python3
        return "/usr/bin/python3"

    def _collect_env_vars(self) -> dict:
        """Collect environment variables needed by collectors."""
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"}
        # Pass through LiteLLM master key if set
        master_key_env = (
            self.config.get("api", {})
            .get("litellm", {})
            .get("master_key_env", "LITELLM_MASTER_KEY")
        )
        val = os.environ.get(master_key_env)
        if val:
            env[master_key_env] = val
        return env


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="LLM Usage Scheduler")
    parser.add_argument(
        "command",
        choices=["install", "uninstall", "status"],
        help="Schedule management command",
    )
    parser.add_argument("--config", type=str, help="Config file path")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    config = _load_config(config_path)
    scheduler = Scheduler(config)

    if args.command == "install":
        scheduler.install()
    elif args.command == "uninstall":
        scheduler.uninstall()
    elif args.command == "status":
        info = scheduler.status()
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
