#!/Users/joneshong/.local/bin/python3
"""CSO — Claude Session Observatory CLI.

Usage:
    cso health                                    # health check
    cso stats                                     # summary stats
    cso events [--type X] [--session X] [--tool X] [--limit N]
    cso tools [--limit N]                         # tool usage ranking
    cso sessions [--limit N]                      # session list
    cso timeline [--range 7d] [--granularity hour]
    cso ingest --type X [--data '{"key":"val"}']  # manual event push

Symlink: ln -sf ~/workshop/stations/hook-observatory/cli/cso.py ~/.local/bin/cso
"""

import argparse
import json
import sys

from sdk_client.hook_observatory import HookObservatoryClient, HookObservatoryError


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def cmd_health(args):
    client = HookObservatoryClient()
    try:
        h = client.health()
        _json_out(h, args.json)
        if not args.json:
            print(f"Status: {h.get('status', 'unknown')}")
            print(f"Spool dir: {h.get('spool_dir', 'N/A')}")
            print(f"Pending files: {h.get('pending_files', 0)}")
    except HookObservatoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_stats(args):
    client = HookObservatoryClient()
    try:
        s = client.summary()
        if args.json:
            _json_out(s, True)
        else:
            print(f"Total events: {s.get('total', 0)}")
            print(f"Today: {s.get('today', 0)}")
            print(f"Unique sessions: {s.get('unique_sessions', 0)}")
    except HookObservatoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_events(args):
    client = HookObservatoryClient()
    try:
        result = client.list_events(
            event_type=args.type,
            session_id=args.session,
            tool_name=args.tool,
            limit=args.limit,
            offset=args.offset,
        )
        if args.json:
            _json_out(result, True)
        else:
            items = result.get("items", [])
            total = result.get("total", 0)
            print(f"Showing {len(items)} of {total} events\n")
            for evt in items:
                ts = evt.get("created_at", "")
                if isinstance(ts, str) and len(ts) > 19:
                    ts = ts[:19]
                print(
                    f"  [{ts}] {evt.get('event_type', '?'):20s} "
                    f"tool={evt.get('tool_name', '-'):15s} "
                    f"session={str(evt.get('session_id', '-'))[:12]}"
                )
    except HookObservatoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_tools(args):
    client = HookObservatoryClient()
    try:
        tools = client.stats_by_tool(limit=args.limit)
        if args.json:
            _json_out(tools, True)
        else:
            print(f"Tool usage (top {args.limit}):\n")
            for t in tools:
                bar = "#" * min(t.get("count", 0) // 10, 40)
                print(f"  {t.get('tool_name', '?'):25s} {t.get('count', 0):>6d}  {bar}")
    except HookObservatoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_sessions(args):
    client = HookObservatoryClient()
    try:
        sessions = client.stats_by_session(limit=args.limit)
        if args.json:
            _json_out(sessions, True)
        else:
            print(f"Recent sessions (top {args.limit}):\n")
            for s in sessions:
                sid = str(s.get("session_id", "?"))[:16]
                count = s.get("event_count", 0)
                last = str(s.get("last_seen", ""))[:19]
                print(f"  {sid:18s} events={count:>5d}  last={last}")
    except HookObservatoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_timeline(args):
    client = HookObservatoryClient()
    try:
        buckets = client.timeline(range=args.range, granularity=args.granularity)
        if args.json:
            _json_out(buckets, True)
        else:
            print(f"Timeline ({args.range}, by {args.granularity}):\n")
            max_count = max((b.get("count", 0) for b in buckets), default=1) or 1
            for b in buckets:
                ts = str(b.get("bucket", ""))[:16]
                count = b.get("count", 0)
                bar_len = int(count / max_count * 40)
                bar = "#" * bar_len
                print(f"  {ts}  {count:>5d}  {bar}")
    except HookObservatoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_ingest(args):
    client = HookObservatoryClient()
    try:
        data = json.loads(args.data) if args.data else {}
        result = client.ingest(event_type=args.type, data=data, session_id=args.session)
        if args.json:
            _json_out(result, True)
        else:
            print(f"Event ingested: {result.get('status', 'unknown')}")
    except json.JSONDecodeError:
        print("Error: --data must be valid JSON", file=sys.stderr)
        sys.exit(1)
    except HookObservatoryError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="cso",
        description="Claude Session Observatory — hook event analytics CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # health
    p_health = sub.add_parser("health", help="Health check")
    p_health.set_defaults(func=cmd_health)

    # stats
    p_stats = sub.add_parser("stats", help="Summary statistics")
    p_stats.set_defaults(func=cmd_stats)

    # events
    p_events = sub.add_parser("events", help="List events")
    p_events.add_argument("--type", help="Filter by event_type")
    p_events.add_argument("--session", help="Filter by session_id")
    p_events.add_argument("--tool", help="Filter by tool_name")
    p_events.add_argument("--limit", type=int, default=20)
    p_events.add_argument("--offset", type=int, default=0)
    p_events.set_defaults(func=cmd_events)

    # tools
    p_tools = sub.add_parser("tools", help="Tool usage ranking")
    p_tools.add_argument("--limit", type=int, default=20)
    p_tools.set_defaults(func=cmd_tools)

    # sessions
    p_sessions = sub.add_parser("sessions", help="Session list")
    p_sessions.add_argument("--limit", type=int, default=20)
    p_sessions.set_defaults(func=cmd_sessions)

    # timeline
    p_timeline = sub.add_parser("timeline", help="Time-series event counts")
    p_timeline.add_argument("--range", default="7d", help="e.g. 7d, 24h, 60m")
    p_timeline.add_argument("--granularity", default="hour", choices=["minute", "hour", "day"])
    p_timeline.set_defaults(func=cmd_timeline)

    # ingest
    p_ingest = sub.add_parser("ingest", help="Manual event ingestion")
    p_ingest.add_argument("--type", required=True, help="Event type")
    p_ingest.add_argument("--data", help="JSON payload")
    p_ingest.add_argument("--session", help="Session ID")
    p_ingest.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
