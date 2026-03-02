"""
System Monitor V2 — CLI entry point.

Usage:
    python3 stations/system-monitor collect [--hardware-only] [--disk-only] [--compact]
    python3 stations/system-monitor report [--type weekly|monthly]
    python3 stations/system-monitor status
    python3 stations/system-monitor serve [--port PORT]
    python3 stations/system-monitor schedule install|uninstall|status
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


def cmd_collect(args: argparse.Namespace) -> None:
    """Execute a one-time collection."""
    from collector import collect_all, load_config

    config = load_config()
    do_disk = not args.hardware_only
    do_hw = not args.disk_only
    data = collect_all(config, disk=do_disk, hardware=do_hw)

    # Save snapshot for history
    output_dir = Path(
        config.get("output_dir", "~/.claude/data/system-monitor")
    ).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
    snapshot_path = output_dir / f"snapshot-{date_str}.json"
    snapshot_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Check pressure and notify
    from notifier import PressureNotifier
    notifier = PressureNotifier(config)
    alerts = notifier.check_and_alert(data)
    if alerts:
        print(f"Pressure alerts triggered: {len(alerts)}", file=sys.stderr)

    indent = None if args.compact else 2
    print(json.dumps(data, indent=indent, ensure_ascii=False))


def cmd_report(args: argparse.Namespace) -> None:
    """Generate an AI report."""
    from collector import collect_all, load_config
    from reporter import SystemReporter

    config = load_config()
    data = collect_all(config)

    reporter = SystemReporter(config)
    path = reporter.generate(data, args.type)
    print(f"Report saved to {path}")

    # Cleanup old reports
    deleted = reporter.cleanup_old_reports()
    if deleted:
        print(f"Cleaned up {deleted} old report(s)")


def cmd_status(args: argparse.Namespace) -> None:
    """Show latest status (hardware-only for speed)."""
    from collector import collect_all, load_config

    config = load_config()
    data = collect_all(config, disk=False, hardware=True)

    pressure = data.get("pressure_level", "unknown")
    hw = data.get("hardware", {})
    cpu = hw.get("cpu", {})
    mem = hw.get("memory", {})
    swap = hw.get("swap", {})
    batt = hw.get("battery", {})

    print(f"Pressure: {pressure}")
    print(f"CPU:      {cpu.get('usage_pct', '?')}% (load: {cpu.get('load_avg_1m', '?')})")
    print(f"Memory:   {mem.get('usage_pct', '?')}% ({mem.get('used_gb', '?')}/{mem.get('total_gb', '?')} GB)")
    print(f"Swap:     {swap.get('used_gb', '?')} GB")
    if batt.get("available"):
        print(f"Battery:  {batt.get('percent', '?')}% ({'charging' if batt.get('charging') else 'on battery'})")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the API server."""
    import uvicorn
    from api import app
    from collector import load_config
    config = load_config()
    host = args.host or config.get("api", {}).get("host", "127.0.0.1")
    port = args.port or config.get("api", {}).get("port", 9526)

    print(f"Starting System Monitor API on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


def cmd_schedule(args: argparse.Namespace) -> None:
    """Manage launchd schedules."""
    from scheduler import Scheduler

    scheduler = Scheduler()

    if args.schedule_action == "install":
        labels = scheduler.install(args.type)
        print(f"Installed: {', '.join(labels)}")
    elif args.schedule_action == "uninstall":
        labels = scheduler.uninstall(args.type)
        print(f"Uninstalled: {', '.join(labels)}")
    elif args.schedule_action == "status":
        print(json.dumps(scheduler.status(), indent=2))
    else:
        print(f"Unknown schedule action: {args.schedule_action}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="system-monitor",
        description="System Monitor V2 — macOS system health monitoring station",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # collect
    p_collect = sub.add_parser("collect", help="Execute a one-time collection")
    p_collect.add_argument("--hardware-only", action="store_true")
    p_collect.add_argument("--disk-only", action="store_true")
    p_collect.add_argument("--compact", action="store_true")

    # report
    p_report = sub.add_parser("report", help="Generate AI system report")
    p_report.add_argument("--type", choices=["weekly", "monthly"], default="weekly")

    # status
    sub.add_parser("status", help="Show latest system status")

    # serve
    p_serve = sub.add_parser("serve", help="Start API server")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)

    # schedule
    p_sched = sub.add_parser("schedule", help="Manage launchd schedules")
    p_sched.add_argument("schedule_action", choices=["install", "uninstall", "status"])
    p_sched.add_argument("--type", choices=["weekly", "monthly"], default=None)

    args = parser.parse_args()

    commands = {
        "collect": cmd_collect,
        "report": cmd_report,
        "status": cmd_status,
        "serve": cmd_serve,
        "schedule": cmd_schedule,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
