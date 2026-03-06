#!/usr/bin/env python3
"""macOS Scheduler — launchd-based task scheduler with centralized registry."""

import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_outputs_root = Path(
    os.environ.get("SCHEDULER_DATA_DIR", Path.home() / "workshop" / "outputs" / "scheduler")
)
REGISTRY_DIR = _outputs_root
REGISTRY_FILE = REGISTRY_DIR / "registry.json"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LABEL_PREFIX = "com.joneshong.scheduler."


def ensure_dirs():
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def load_registry() -> list:
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text())
    return []


def save_registry(entries: list):
    ensure_dirs()
    REGISTRY_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


def plist_path(name: str) -> Path:
    return LAUNCH_AGENTS_DIR / f"{LABEL_PREFIX}{name}.plist"


def add_job(name: str, command: str, schedule: dict, description: str = ""):
    """Add a new scheduled job.

    schedule dict keys:
      - interval: int (seconds between runs)
      - calendar: dict with Hour, Minute, Weekday, Day, Month (launchd keys)
      - run_at_load: bool (run immediately when loaded)
    """
    ensure_dirs()
    entries = load_registry()

    # Check duplicate
    if any(e["name"] == name for e in entries):
        print(
            json.dumps(
                {"error": f"Job '{name}' already exists. Remove it first or use a different name."}
            )
        )
        return

    label = f"{LABEL_PREFIX}{name}"
    log_dir = REGISTRY_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    # Build plist
    plist = {
        "Label": label,
        "ProgramArguments": ["/bin/zsh", "-lc", command],
        "StandardOutPath": str(log_dir / f"{name}.log"),
        "StandardErrorPath": str(log_dir / f"{name}.err"),
    }

    if schedule.get("interval"):
        plist["StartInterval"] = schedule["interval"]
    elif schedule.get("calendar"):
        plist["StartCalendarInterval"] = schedule["calendar"]

    if schedule.get("run_at_load", False):
        plist["RunAtLoad"] = True

    if schedule.get("keep_alive", False):
        plist["KeepAlive"] = True
        plist["ThrottleInterval"] = schedule.get("throttle_interval", 10)

    # Write plist
    plist_file = plist_path(name)
    with open(plist_file, "wb") as f:
        plistlib.dump(plist, f)

    # Load into launchd
    result = subprocess.run(["launchctl", "load", str(plist_file)], capture_output=True, text=True)

    # Register
    entry = {
        "name": name,
        "label": label,
        "command": command,
        "schedule": schedule,
        "description": description,
        "plist": str(plist_file),
        "enabled": True,
        "created": datetime.now().isoformat(),
    }
    entries.append(entry)
    save_registry(entries)

    print(
        json.dumps(
            {
                "status": "added",
                "name": name,
                "plist": str(plist_file),
                "launchctl": result.returncode == 0,
                "schedule": schedule,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def resolve_plist(name: str, entry: dict | None = None) -> Path:
    """Resolve plist path: use stored path from registry if available, else compute."""
    if entry and entry.get("plist"):
        return Path(entry["plist"])
    return plist_path(name)


def remove_job(name: str):
    """Remove a scheduled job."""
    entries = load_registry()
    entry = next((e for e in entries if e["name"] == name), None)
    if not entry:
        print(json.dumps({"error": f"Job '{name}' not found."}))
        return

    # Unload from launchd
    pfile = resolve_plist(name, entry)
    if pfile.exists():
        subprocess.run(["launchctl", "unload", str(pfile)], capture_output=True)
        pfile.unlink()

    entries = [e for e in entries if e["name"] != name]
    save_registry(entries)
    print(json.dumps({"status": "removed", "name": name}))


def enable_job(name: str):
    entries = load_registry()
    entry = next((e for e in entries if e["name"] == name), None)
    if not entry:
        print(json.dumps({"error": f"Job '{name}' not found."}))
        return
    pfile = resolve_plist(name, entry)
    if pfile.exists():
        subprocess.run(["launchctl", "load", str(pfile)], capture_output=True)
    entry["enabled"] = True
    save_registry(entries)
    print(json.dumps({"status": "enabled", "name": name}))


def disable_job(name: str):
    entries = load_registry()
    entry = next((e for e in entries if e["name"] == name), None)
    if not entry:
        print(json.dumps({"error": f"Job '{name}' not found."}))
        return
    pfile = resolve_plist(name, entry)
    if pfile.exists():
        subprocess.run(["launchctl", "unload", str(pfile)], capture_output=True)
    entry["enabled"] = False
    save_registry(entries)
    print(json.dumps({"status": "disabled", "name": name}))


def list_jobs():
    entries = load_registry()
    if not entries:
        print(json.dumps({"jobs": [], "count": 0}))
        return

    # Check actual launchd status
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    loaded_labels = set(result.stdout) if result.returncode == 0 else set()

    output = []
    for e in entries:
        schedule_desc = ""
        s = e.get("schedule", {})
        if s.get("interval"):
            mins = s["interval"] // 60
            schedule_desc = f"every {mins} min" if mins > 0 else f"every {s['interval']}s"
        elif s.get("calendar"):
            cal = s["calendar"]
            parts = []
            if "Weekday" in cal:
                days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                parts.append(days[cal["Weekday"]])
            if "Hour" in cal:
                parts.append(f"{cal['Hour']:02d}:{cal.get('Minute', 0):02d}")
            schedule_desc = " ".join(parts) or "calendar"

        output.append(
            {
                "name": e["name"],
                "enabled": e.get("enabled", True),
                "schedule": schedule_desc,
                "command": e["command"][:80],
                "description": e.get("description", ""),
            }
        )

    print(json.dumps({"jobs": output, "count": len(output)}, indent=2, ensure_ascii=False))


def show_logs(name: str, lines: int = 20):
    log_file = REGISTRY_DIR / "logs" / f"{name}.log"
    err_file = REGISTRY_DIR / "logs" / f"{name}.err"
    result = {}
    if log_file.exists():
        content = log_file.read_text().strip().split("\n")
        result["stdout"] = content[-lines:]
    if err_file.exists():
        content = err_file.read_text().strip().split("\n")
        result["stderr"] = content[-lines:]
    if not result:
        result["message"] = f"No logs found for '{name}'"
    print(json.dumps(result, indent=2, ensure_ascii=False))


def usage():
    print("""Usage: python3 scheduler.py <command> [args]

Commands:
  add <name> <command> <schedule_json> [description]
    schedule_json examples:
      '{"interval": 300}'                    — every 5 minutes
      '{"calendar": {"Hour": 9, "Minute": 30}}'  — daily at 09:30
      '{"calendar": {"Weekday": 1, "Hour": 10}}' — every Monday at 10:00
      '{"interval": 60, "run_at_load": true}'     — every 60s, run immediately

  remove <name>       — Remove a job
  enable <name>       — Enable a disabled job
  disable <name>      — Disable a job (keep in registry)
  list                — List all registered jobs
  logs <name> [lines] — Show recent logs for a job
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 5:
            print("Usage: scheduler.py add <name> <command> <schedule_json> [description]")
            sys.exit(1)
        name = sys.argv[2]
        command = sys.argv[3]
        schedule = json.loads(sys.argv[4])
        desc = sys.argv[5] if len(sys.argv) > 5 else ""
        add_job(name, command, schedule, desc)
    elif cmd == "remove":
        remove_job(sys.argv[2])
    elif cmd == "enable":
        enable_job(sys.argv[2])
    elif cmd == "disable":
        disable_job(sys.argv[2])
    elif cmd == "list":
        list_jobs()
    elif cmd == "logs":
        name = sys.argv[2]
        lines = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        show_logs(name, lines)
    else:
        usage()
