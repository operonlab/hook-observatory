#!/Users/joneshong/.local/bin/python3
"""sysmon -- Workshop System Monitor CLI.

Usage:
    sysmon status                          # current metrics + pressure level
    sysmon history                         # historical snapshots
    sysmon services list                   # all services
    sysmon services logs <label> [--lines 50]
    sysmon services restart <label>
    sysmon disk summary                    # quick disk info
    sysmon disk scan                       # full scan (~30s)
    sysmon alerts                          # pressure alerts
    sysmon guardian                        # memory guardian log
    sysmon reports list [--type T] [--limit N]
    sysmon reports get <filename>
    sysmon health                          # health check

Symlink: ln -sf ~/workshop/stations/system-monitor-cli/sysmon.py ~/.local/bin/sysmon
"""

import argparse
import json
import sys

from workshop.clients.system_monitor import SystemMonitorClient, SystemMonitorError


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def _err(e):
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


def _fmt_bytes(n):
    """Format bytes to human-readable string."""
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


PRESSURE_ICONS = {
    "low": "+",
    "normal": "+",
    "moderate": "~",
    "warning": "!",
    "high": "!",
    "critical": "X",
}


# ======================== Commands ========================


def cmd_health(args):
    client = SystemMonitorClient()
    try:
        result = client.health()
        if args.json:
            _json_out(result, True)
        else:
            print(f"Status: {result.get('status', '?')}")
            if result.get("version"):
                print(f"Version: {result['version']}")
            if result.get("service"):
                print(f"Service: {result['service']}")
    except SystemMonitorError as e:
        _err(e)


def cmd_status(args):
    client = SystemMonitorClient()
    try:
        result = client.get_status()
        if args.json:
            _json_out(result, True)
            return

        pressure = result.get("pressure_level", "unknown")
        icon = PRESSURE_ICONS.get(pressure, "?")
        print(f"[{icon}] Pressure: {pressure}")
        ts = result.get("timestamp", "?")
        print(f"    Timestamp: {ts}")
        print()

        # Hardware
        hw = result.get("hardware", {})
        cpu = hw.get("cpu", {})
        mem = hw.get("memory", {})
        if cpu:
            print(f"  CPU:    {cpu.get('usage_pct', '?')}%  ({cpu.get('cores', '?')} cores)")
        if mem:
            used = _fmt_bytes(mem.get("used_bytes"))
            total = _fmt_bytes(mem.get("total_bytes"))
            print(f"  Memory: {mem.get('usage_pct', '?')}%  ({used} / {total})")

        # Disk
        disk = result.get("disk", {})
        if disk:
            used = _fmt_bytes(disk.get("used_bytes"))
            total = _fmt_bytes(disk.get("total_bytes"))
            print(f"  Disk:   {disk.get('usage_pct', '?')}%  ({used} / {total})")
    except SystemMonitorError as e:
        _err(e)


def cmd_history(args):
    client = SystemMonitorClient()
    try:
        result = client.get_history()
        if args.json:
            _json_out(result, True)
            return

        snapshots = result.get("snapshots", [])
        if not snapshots:
            print("No historical snapshots.")
            return

        print(f"Historical Snapshots ({result.get('total', len(snapshots))} total)")
        print(f"{'Timestamp':<22} {'Pressure':<12} {'CPU%':>6} {'Mem%':>6} {'Disk%':>6}")
        print("-" * 58)
        for s in snapshots:
            ts = (s.get("timestamp") or "?")[:19]
            pressure = s.get("pressure_level", "?")
            cpu = s.get("cpu_usage_pct")
            mem = s.get("memory_usage_pct")
            disk = s.get("disk_usage_pct")
            print(f"{ts:<22} {pressure:<12} {cpu or '-':>6} {mem or '-':>6} {disk or '-':>6}")
    except SystemMonitorError as e:
        _err(e)


def cmd_services_list(args):
    client = SystemMonitorClient()
    try:
        result = client.list_services()
        if args.json:
            _json_out(result, True)
            return

        services = result.get("services", [])
        if not services:
            print("No services found.")
            return

        total = result.get("total", len(services))
        print(f"Services ({total} total)")
        print(f"{'Label':<40} {'Status':<12} {'Type':<10} PID")
        print("-" * 70)
        for s in services:
            label = s.get("label", s.get("name", "?"))
            status = s.get("status", "?")
            stype = s.get("type", "?")
            pid = s.get("pid", "-")
            print(f"{label:<40} {status:<12} {stype:<10} {pid}")
    except SystemMonitorError as e:
        _err(e)


def cmd_services_logs(args):
    client = SystemMonitorClient()
    try:
        result = client.get_service_logs(args.label, lines=args.lines)
        if args.json:
            _json_out(result, True)
            return

        logs = result.get("logs", result.get("lines", []))
        if isinstance(logs, list):
            for line in logs:
                print(line)
        elif isinstance(logs, str):
            print(logs)
        else:
            print("No logs available.")
    except SystemMonitorError as e:
        _err(e)


def cmd_services_restart(args):
    client = SystemMonitorClient()
    try:
        result = client.restart_service(args.label)
        if args.json:
            _json_out(result, True)
        else:
            status = result.get("status", "?")
            label = result.get("label", args.label)
            print(f"[{'+' if status == 'ok' else 'X'}] {label}: {result.get('action', status)}")
            if result.get("detail"):
                print(f"    {result['detail']}")
    except SystemMonitorError as e:
        _err(e)


def cmd_disk_summary(args):
    client = SystemMonitorClient()
    try:
        result = client.disk_summary()
        if args.json:
            _json_out(result, True)
            return

        used = _fmt_bytes(result.get("used_bytes"))
        total = _fmt_bytes(result.get("total_bytes"))
        free = _fmt_bytes(result.get("free_bytes"))
        pct = result.get("usage_pct", "?")
        print(f"Disk Usage: {pct}%")
        print(f"  Used:  {used}")
        print(f"  Free:  {free}")
        print(f"  Total: {total}")

        volumes = result.get("volumes", [])
        if volumes:
            print(f"\nVolumes ({len(volumes)}):")
            for v in volumes:
                vname = v.get("name", v.get("mount", "?"))
                vused = _fmt_bytes(v.get("used_bytes"))
                vtotal = _fmt_bytes(v.get("total_bytes"))
                vpct = v.get("usage_pct", "?")
                print(f"  {vname:<30} {vpct:>5}%  {vused} / {vtotal}")
    except SystemMonitorError as e:
        _err(e)


def cmd_disk_scan(args):
    client = SystemMonitorClient()
    try:
        result = client.disk_scan()
        if args.json:
            _json_out(result, True)
            return

        # Large files
        large = result.get("large_files", [])
        if large:
            print(f"Large Files ({len(large)}):")
            for f in large[:10]:
                size = _fmt_bytes(f.get("size_bytes", f.get("size", 0)))
                print(f"  {size:>10}  {f.get('path', '?')}")
            print()

        # Caches
        caches = result.get("caches", [])
        if caches:
            print(f"Caches ({len(caches)}):")
            for c in caches:
                size = _fmt_bytes(c.get("size_bytes", c.get("size", 0)))
                print(f"  {size:>10}  {c.get('path', c.get('name', '?'))}")
            print()

        # Summary
        total_reclaimable = result.get("total_reclaimable_bytes")
        if total_reclaimable:
            print(f"Total Reclaimable: {_fmt_bytes(total_reclaimable)}")
    except SystemMonitorError as e:
        _err(e)


def cmd_alerts(args):
    client = SystemMonitorClient()
    try:
        result = client.list_alerts()
        if args.json:
            _json_out(result, True)
            return

        alerts = result.get("alerts", [])
        if not alerts:
            print("No pressure alerts.")
            return

        print(f"Pressure Alerts ({result.get('total', len(alerts))} total)")
        for a in alerts:
            level = a.get("overall_pressure", a.get("level", "?"))
            icon = PRESSURE_ICONS.get(level, "?")
            ts = (a.get("timestamp", "?"))[:19] if a.get("timestamp") else "?"
            print(f"  [{icon}] {ts}  {level}")
            sub_alerts = a.get("alerts", [])
            for sa in sub_alerts:
                sub_icon = PRESSURE_ICONS.get(sa.get("pressure", "?"), "?")
                print(f"      [{sub_icon}] {sa.get('subsystem', '?')}: {sa.get('detail', '')}")
    except SystemMonitorError as e:
        _err(e)


def cmd_guardian(args):
    client = SystemMonitorClient()
    try:
        result = client.get_guardian_log()
        if args.json:
            _json_out(result, True)
            return

        entries = result.get("entries", [])
        if not entries:
            print("No guardian log entries.")
            return

        print(f"Memory Guardian Log ({result.get('total', len(entries))} entries)")
        for e in entries:
            ts = (e.get("timestamp", "?"))[:19] if e.get("timestamp") else "?"
            action = e.get("action", "?")
            detail = e.get("detail", e.get("message", ""))
            print(f"  {ts}  {action}: {detail}")
    except SystemMonitorError as e:
        _err(e)


def cmd_reports_list(args):
    client = SystemMonitorClient()
    try:
        result = client.list_reports(type=args.type, limit=args.limit)
        if args.json:
            _json_out(result, True)
            return

        reports = result.get("reports", [])
        if not reports:
            print("No reports found.")
            return

        total = result.get("total", len(reports))
        print(f"Reports ({total} total)")
        print(f"{'Filename':<45} {'Type':<10} {'Size':>10}  Created")
        print("-" * 85)
        for r in reports:
            size = _fmt_bytes(r.get("size_bytes", 0))
            print(
                f"{r.get('filename', '?'):<45} {r.get('type', '?'):<10} "
                f"{size:>10}  {(r.get('created', '?'))[:19]}"
            )
    except SystemMonitorError as e:
        _err(e)


def cmd_reports_get(args):
    client = SystemMonitorClient()
    try:
        result = client.get_report(args.filename)
        if args.json:
            _json_out(result, True)
        else:
            print(result.get("content", ""))
    except SystemMonitorError as e:
        _err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="sysmon",
        description="Workshop System Monitor CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # health
    p_health = sub.add_parser("health", help="Health check")
    p_health.set_defaults(func=cmd_health)

    # status
    p_status = sub.add_parser("status", help="Current metrics + pressure level")
    p_status.set_defaults(func=cmd_status)

    # history
    p_history = sub.add_parser("history", help="Historical snapshots")
    p_history.set_defaults(func=cmd_history)

    # services (subparser group)
    p_services = sub.add_parser("services", help="Service management")
    svc_sub = p_services.add_subparsers(dest="svc_cmd", required=True)

    p_svc_list = svc_sub.add_parser("list", help="List all services")
    p_svc_list.set_defaults(func=cmd_services_list)

    p_svc_logs = svc_sub.add_parser("logs", help="Get service logs")
    p_svc_logs.add_argument("label", help="Service label")
    p_svc_logs.add_argument("--lines", type=int, default=50, help="Number of log lines")
    p_svc_logs.set_defaults(func=cmd_services_logs)

    p_svc_restart = svc_sub.add_parser("restart", help="Restart a service")
    p_svc_restart.add_argument("label", help="Service label")
    p_svc_restart.set_defaults(func=cmd_services_restart)

    # disk (subparser group)
    p_disk = sub.add_parser("disk", help="Disk management")
    disk_sub = p_disk.add_subparsers(dest="disk_cmd", required=True)

    p_disk_summary = disk_sub.add_parser("summary", help="Quick disk info")
    p_disk_summary.set_defaults(func=cmd_disk_summary)

    p_disk_scan = disk_sub.add_parser("scan", help="Full disk scan (~30s)")
    p_disk_scan.set_defaults(func=cmd_disk_scan)

    # alerts
    p_alerts = sub.add_parser("alerts", help="Pressure alerts")
    p_alerts.set_defaults(func=cmd_alerts)

    # guardian
    p_guardian = sub.add_parser("guardian", help="Memory guardian log")
    p_guardian.set_defaults(func=cmd_guardian)

    # reports (subparser group)
    p_reports = sub.add_parser("reports", help="Report management")
    rpt_sub = p_reports.add_subparsers(dest="rpt_cmd", required=True)

    p_rpt_list = rpt_sub.add_parser("list", help="List reports")
    p_rpt_list.add_argument("--type", help="Filter by type (daily/weekly/monthly)")
    p_rpt_list.add_argument("--limit", type=int, default=50, help="Max results")
    p_rpt_list.set_defaults(func=cmd_reports_list)

    p_rpt_get = rpt_sub.add_parser("get", help="Read a specific report")
    p_rpt_get.add_argument("filename", help="Report filename")
    p_rpt_get.set_defaults(func=cmd_reports_get)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
