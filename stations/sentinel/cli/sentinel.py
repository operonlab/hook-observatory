#!/Users/joneshong/.local/bin/python3
"""sentinel -- Workshop Sentinel health monitoring CLI.

Usage:
    sentinel status              # overview dashboard
    sentinel service <name>      # single service status
    sentinel incidents [--page N] [--limit N]
    sentinel incident <id>       # single incident detail
    sentinel operations          # active operations
    sentinel uptime [--days N]   # per-service uptime
    sentinel health              # raw health check

Symlink: ln -sf ~/workshop/stations/sentinel/cli/sentinel.py ~/.local/bin/sentinel
"""

import argparse
import json
import sys

from workshop.clients.sentinel import SentinelClient, SentinelError


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def _err(e):
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


STATUS_ICONS = {
    "operational": "+",
    "all_operational": "+",
    "degraded": "~",
    "partial_outage": "!",
    "major_outage": "X",
    "maintenance": "M",
    "unknown": "?",
}


# ======================== Commands ========================


def cmd_status(args):
    client = SentinelClient()
    try:
        result = client.get_status_summary()
        if args.json:
            _json_out(result, True)
        else:
            overall = result.get("status", "unknown")
            icon = STATUS_ICONS.get(overall, "?")
            print(f"[{icon}] Overall: {overall}")
            print(f"    Checked: {result.get('checked_at', '?')}")
            print()

            services = result.get("services", [])
            if not services:
                print("  No services registered.")
                return

            # Group by group
            groups: dict[str, list] = {}
            for s in services:
                g = s.get("group") or "ungrouped"
                groups.setdefault(g, []).append(s)

            for group_name, group_services in sorted(groups.items()):
                print(f"  [{group_name}]")
                for s in group_services:
                    svc_icon = STATUS_ICONS.get(s.get("status", "unknown"), "?")
                    ms = f"{s.get('response_ms', 0):.0f}ms" if s.get("response_ms") else "-"
                    last = s.get("last_check", "-")
                    print(
                        f"    {svc_icon} {s.get('service', '?'):<22} {s.get('status', '?'):<16} {ms:>8}  {last}"
                    )
                print()
    except SentinelError as e:
        _err(e)


def cmd_service(args):
    client = SentinelClient()
    try:
        s = client.get_service_status(args.name)
        if args.json:
            _json_out(s, True)
        else:
            icon = STATUS_ICONS.get(s.get("status", "unknown"), "?")
            print(f"[{icon}] {s.get('service', '?')}: {s.get('status', '?')}")
            if s.get("group"):
                print(f"    Group: {s['group']}")
            if s.get("light_status"):
                print(f"    Light: {s['light_status']}")
            if s.get("deep_status"):
                print(f"    Deep:  {s['deep_status']}")
            if s.get("response_ms"):
                print(f"    Response: {s['response_ms']:.0f}ms")
            if s.get("last_check"):
                print(f"    Last check: {s['last_check']}")
    except SentinelError as e:
        _err(e)


def cmd_incidents(args):
    client = SentinelClient()
    try:
        result = client.list_incidents(page=args.page, page_size=args.limit)
        if args.json:
            _json_out(result, True)
        else:
            items = result.get("items", [])
            total = result.get("total", 0)
            if not items:
                print("No incidents found.")
                return

            print(f"Incidents (page {result.get('page', 1)}, {total} total)")
            print(f"{'ID':<18} {'Service':<18} {'Severity':<10} {'Status':<14} Created")
            print("-" * 85)
            for i in items:
                print(
                    f"{i.get('id', '?'):<18} {i.get('service', '?'):<18} "
                    f"{i.get('severity', '?'):<10} {i.get('status', '?'):<14} "
                    f"{i.get('created_at', '?')}"
                )
    except SentinelError as e:
        _err(e)


def cmd_incident(args):
    client = SentinelClient()
    try:
        inc = client.get_incident(args.id)
        if args.json:
            _json_out(inc, True)
        else:
            print(f"Incident: {inc.get('id', '?')}")
            print(f"  Service:  {inc.get('service', '?')}")
            print(f"  Severity: {inc.get('severity', '?')}")
            print(f"  Status:   {inc.get('status', '?')}")
            print(f"  Title:    {inc.get('title', '-')}")
            if inc.get("detail"):
                print(f"  Detail:   {inc['detail']}")
            print(f"  Created:  {inc.get('created_at', '?')}")
            if inc.get("resolved_at"):
                print(f"  Resolved: {inc['resolved_at']}")
    except SentinelError as e:
        _err(e)


def cmd_operations(args):
    client = SentinelClient()
    try:
        ops = client.list_operations()
        if args.json:
            _json_out(ops, True)
        else:
            if not ops:
                print("No active operations.")
                return

            print(f"{'ID':<18} {'Service':<18} {'Agent':<18} {'Action':<15} Created")
            print("-" * 85)
            for o in ops:
                print(
                    f"{o.get('id', '?'):<18} {o.get('service', '?'):<18} "
                    f"{o.get('agent_id', '?'):<18} {o.get('action', '?'):<15} "
                    f"{o.get('created_at', '?')}"
                )
    except SentinelError as e:
        _err(e)


def cmd_uptime(args):
    client = SentinelClient()
    try:
        result = client.get_uptime(days=args.days)
        if args.json:
            _json_out(result, True)
        else:
            services = result.get("services", [])
            if not services:
                print("No uptime data available.")
                return

            for svc in services:
                name = svc.get("service", "?")
                days_data = svc.get("days", [])
                if not days_data:
                    print(f"  {name}: no data")
                    continue

                avg_pct = sum(d.get("uptime_pct", 0) for d in days_data) / len(days_data)
                print(f"  {name:<22} {avg_pct:6.2f}% avg ({len(days_data)} days)")
    except SentinelError as e:
        _err(e)


def cmd_health(args):
    client = SentinelClient()
    try:
        result = client.health()
        if args.json:
            _json_out(result, True)
        else:
            print(f"Status: {result.get('status', '?')}")
            if result.get("version"):
                print(f"Version: {result['version']}")
    except SentinelError as e:
        _err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Workshop Sentinel health monitoring CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # status
    p_status = sub.add_parser("status", help="Overview dashboard")
    p_status.set_defaults(func=cmd_status)

    # service
    p_service = sub.add_parser("service", help="Single service status")
    p_service.add_argument("name", help="Service name")
    p_service.set_defaults(func=cmd_service)

    # incidents
    p_incidents = sub.add_parser("incidents", help="List incidents")
    p_incidents.add_argument("--page", type=int, default=1, help="Page number")
    p_incidents.add_argument("--limit", type=int, default=20, help="Page size")
    p_incidents.set_defaults(func=cmd_incidents)

    # incident
    p_incident = sub.add_parser("incident", help="Get incident detail")
    p_incident.add_argument("id", help="Incident ID")
    p_incident.set_defaults(func=cmd_incident)

    # operations
    p_ops = sub.add_parser("operations", help="List active operations")
    p_ops.set_defaults(func=cmd_operations)

    # uptime
    p_uptime = sub.add_parser("uptime", help="Per-service uptime")
    p_uptime.add_argument("--days", type=int, default=90, help="Number of days (max 365)")
    p_uptime.set_defaults(func=cmd_uptime)

    # health
    p_health = sub.add_parser("health", help="Raw health check")
    p_health.set_defaults(func=cmd_health)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
