"""
System Monitor V2 Scheduler — launchd plist management for periodic reports.
"""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = Path("~/.claude/data/system-monitor/logs").expanduser()

LABEL_PREFIX = "com.workshop.system-monitor"

PLIST_CONFIGS = {
    "weekly": {
        "label": f"{LABEL_PREFIX}-weekly",
        "calendar": {"Weekday": 1, "Hour": 5, "Minute": 0},  # Monday 05:00
    },
    "monthly": {
        "label": f"{LABEL_PREFIX}-monthly",
        "calendar": {"Day": 1, "Hour": 5, "Minute": 0},  # 1st of month 05:00
    },
}


class Scheduler:
    def __init__(self, config: dict | None = None):
        if config is None:
            config_path = SCRIPT_DIR / "config.json"
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
        self.config = config
        schedule = config.get("schedule", {})

        # Override calendar intervals from config
        if "weekly" in schedule:
            w = schedule["weekly"]
            PLIST_CONFIGS["weekly"]["calendar"] = {
                "Weekday": w.get("day", 1),
                "Hour": w.get("hour", 5),
                "Minute": w.get("minute", 0),
            }
        if "monthly" in schedule:
            m = schedule["monthly"]
            PLIST_CONFIGS["monthly"]["calendar"] = {
                "Day": m.get("day", 1),
                "Hour": m.get("hour", 5),
                "Minute": m.get("minute", 0),
            }

    def _build_plist(self, report_type: str) -> dict:
        """Build launchd plist dict for a report type."""
        cfg = PLIST_CONFIGS[report_type]
        python = str(Path("~/.local/bin/python3").expanduser())
        main_script = str(SCRIPT_DIR / "__main__.py")

        LOG_DIR.mkdir(parents=True, exist_ok=True)

        return {
            "Label": cfg["label"],
            "ProgramArguments": [python, main_script, "report", f"--type={report_type}"],
            "StartCalendarInterval": cfg["calendar"],
            "WorkingDirectory": str(SCRIPT_DIR),
            "StandardOutPath": str(LOG_DIR / f"{report_type}-stdout.log"),
            "StandardErrorPath": str(LOG_DIR / f"{report_type}-stderr.log"),
            "EnvironmentVariables": {
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                "HOME": str(Path.home()),
            },
        }

    def _plist_path(self, report_type: str) -> Path:
        return PLIST_DIR / f"{PLIST_CONFIGS[report_type]['label']}.plist"

    def install(self, report_type: str | None = None) -> list[str]:
        """Generate and load launchd plists. Returns list of installed labels."""
        PLIST_DIR.mkdir(parents=True, exist_ok=True)
        types = [report_type] if report_type else list(PLIST_CONFIGS.keys())
        installed = []

        for rt in types:
            plist_data = self._build_plist(rt)
            plist_path = self._plist_path(rt)
            label = PLIST_CONFIGS[rt]["label"]

            # Unload first if already loaded
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True, timeout=10,
            )

            # Write plist
            with open(plist_path, "wb") as f:
                plistlib.dump(plist_data, f)

            # Load
            r = subprocess.run(
                ["launchctl", "load", str(plist_path)],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                installed.append(label)
            else:
                print(f"Warning: failed to load {label}: {r.stderr}", file=sys.stderr)

        return installed

    def uninstall(self, report_type: str | None = None) -> list[str]:
        """Unload and remove launchd plists. Returns list of uninstalled labels."""
        types = [report_type] if report_type else list(PLIST_CONFIGS.keys())
        uninstalled = []

        for rt in types:
            plist_path = self._plist_path(rt)
            label = PLIST_CONFIGS[rt]["label"]

            if plist_path.exists():
                subprocess.run(
                    ["launchctl", "unload", str(plist_path)],
                    capture_output=True, timeout=10,
                )
                plist_path.unlink()
                uninstalled.append(label)

        return uninstalled

    def status(self) -> dict:
        """Query schedule status for all report types."""
        result = {}
        list_out = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10,
        ).stdout

        for rt, cfg in PLIST_CONFIGS.items():
            label = cfg["label"]
            plist_path = self._plist_path(rt)
            loaded = label in list_out
            result[rt] = {
                "label": label,
                "plist_exists": plist_path.exists(),
                "loaded": loaded,
                "calendar": cfg["calendar"],
            }

        return result

    def run_now(self, report_type: str = "weekly") -> str:
        """Execute a report generation immediately. Returns report path."""
        from collector import collect_all, load_config
        from reporter import SystemReporter

        config = load_config()
        data = collect_all(config)
        reporter = SystemReporter(config)
        return reporter.generate(data, report_type)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="System Monitor Scheduler")
    parser.add_argument("action", choices=["install", "uninstall", "status", "run"],
                        help="Scheduler action")
    parser.add_argument("--type", choices=["weekly", "monthly"], default=None,
                        help="Report type (default: all)")
    args = parser.parse_args()

    scheduler = Scheduler()

    if args.action == "install":
        labels = scheduler.install(args.type)
        print(f"Installed: {', '.join(labels)}")
    elif args.action == "uninstall":
        labels = scheduler.uninstall(args.type)
        print(f"Uninstalled: {', '.join(labels)}")
    elif args.action == "status":
        print(json.dumps(scheduler.status(), indent=2))
    elif args.action == "run":
        path = scheduler.run_now(args.type or "weekly")
        print(f"Report: {path}")
