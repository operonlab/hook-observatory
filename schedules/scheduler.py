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


def _parse_loaded_args(label: str) -> list[str] | None:
    """Read what launchd actually has loaded for `label`.

    Returns the ProgramArguments list (post-XML-decode), or None if not loaded.
    """
    uid = os.getuid()
    result = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    args: list[str] = []
    in_block = False
    for raw in result.stdout.splitlines():
        line = raw.rstrip()
        if not in_block:
            if line.lstrip().startswith("arguments = {"):
                in_block = True
            continue
        if line.lstrip().startswith("}"):
            break
        token = line.strip()
        if token:
            args.append(token)
    return args or None


def _disk_args(plist_file: Path) -> list[str] | None:
    """Read ProgramArguments from a plist file on disk (entities pre-decoded by plistlib)."""
    try:
        with open(plist_file, "rb") as f:
            data = plistlib.load(f)
    except Exception:
        return None
    args = data.get("ProgramArguments")
    if isinstance(args, list):
        return [str(a) for a in args]
    return None


def drift_check(json_out: bool = True) -> list[dict]:
    """Compare every com.joneshong.scheduler.*.plist on disk vs what launchd loaded.

    Returns a list of drift records. Empty list = all aligned.
    Why: macOS launchd does NOT auto-reload after plist edits. Every silent
    drift is one missed scheduled run. Run this before any time-sensitive
    job (e.g. auto-survey 10:00 daemon start, 13:00 LINE poller).
    """
    drift: list[dict] = []
    for plist_file in sorted(LAUNCH_AGENTS_DIR.glob(f"{LABEL_PREFIX}*.plist")):
        label = plist_file.stem
        disk = _disk_args(plist_file)
        loaded = _parse_loaded_args(label)
        if disk is None:
            continue
        if loaded is None:
            drift.append({"label": label, "reason": "not_loaded", "disk": disk})
            continue
        if disk != loaded:
            drift.append({"label": label, "reason": "mismatch", "disk": disk, "loaded": loaded})
    if json_out:
        print(json.dumps({"drift": drift, "count": len(drift)}, indent=2, ensure_ascii=False))
    return drift


def _reload_one(plist_file: Path) -> tuple[bool, str]:
    uid = os.getuid()
    label = plist_file.stem
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True, text=True)
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_file)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def reload_job(name: str):
    """Force-reload a single job by name (bootout + bootstrap)."""
    plist_file = plist_path(name)
    if not plist_file.exists():
        print(json.dumps({"error": f"plist not found: {plist_file}"}))
        sys.exit(1)
    ok, msg = _reload_one(plist_file)
    print(json.dumps({"name": name, "reloaded": ok, "msg": msg}, ensure_ascii=False))


def reload_all(only_drift: bool = True):
    """Reload all scheduler-managed plists. Default: only those that drifted."""
    targets: list[Path]
    if only_drift:
        records = drift_check(json_out=False)
        targets = [LAUNCH_AGENTS_DIR / f"{r['label']}.plist" for r in records]
    else:
        targets = sorted(LAUNCH_AGENTS_DIR.glob(f"{LABEL_PREFIX}*.plist"))

    results = []
    for p in targets:
        ok, msg = _reload_one(p)
        results.append({"name": p.stem.removeprefix(LABEL_PREFIX), "reloaded": ok, "msg": msg})

    print(
        json.dumps(
            {"mode": "drift" if only_drift else "all", "results": results, "count": len(results)},
            indent=2,
            ensure_ascii=False,
        )
    )


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
  drift-check         — Detect plist disk-vs-loaded drift (no changes)
  reload <name>       — Force-reload a single job into launchd
  reload-all [--all]  — Reload drifted jobs (default) or every plist (--all)
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
    elif cmd == "drift-check":
        records = drift_check(json_out=True)
        sys.exit(1 if records else 0)
    elif cmd == "reload":
        if len(sys.argv) < 3:
            print("Usage: scheduler.py reload <name>")
            sys.exit(1)
        reload_job(sys.argv[2])
    elif cmd == "reload-all":
        reload_all(only_drift="--all" not in sys.argv[2:])
    else:
        usage()
