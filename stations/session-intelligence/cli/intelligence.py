#!/Users/joneshong/.local/bin/python3
"""Session Intelligence CLI — cross-session analytics and insights.

Usage:
    intelligence stats [--days N]
    intelligence sessions [--days N] [--project P]
    intelligence patterns [--days N]
    intelligence trends [--weeks N]
    intelligence digest [--week-offset N]
    intelligence security [--days N]

All subcommands support --json for machine-readable output.
"""

import argparse
import json

# Allow running directly without installing the package
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "libs", "python", "src"))

from workshop.clients.session_intelligence import SessionIntelligenceClient

# ======================== Formatters ========================


def _hr(char: str = "-", width: int = 60) -> str:
    return char * width


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024**2:
        return f"{n / 1024:.1f} KB"
    elif n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.1f} GB"


def _fmt_stats(data: dict) -> str:
    lines = [
        _hr("="),
        f"  SESSION STATISTICS  (last {data.get('period_days', '?')} days)",
        _hr("="),
        f"  Total sessions      : {data.get('total_sessions', 0)}",
        f"  Total messages      : {data.get('total_messages', 0)}",
        f"  Avg session length  : {data.get('avg_session_length', 0)} messages",
        f"  Total size          : {_fmt_bytes(data.get('total_size_bytes', 0))}",
        f"  Active projects     : {data.get('active_projects_count', 0)}",
    ]

    rd = data.get("redaction_stats", {})
    if rd:
        lines.append(f"  Redactions (period) : {rd.get('total', 0)}")

    # Sessions by day (last 7 visible)
    by_day = data.get("sessions_by_day", {})
    if by_day:
        lines.append("")
        lines.append("  Sessions by day (recent):")
        for day, count in list(sorted(by_day.items()))[-7:]:
            bar = "#" * min(count, 40)
            lines.append(f"    {day}  {bar} {count}")

    lines.append(_hr("="))
    return "\n".join(lines)


def _fmt_sessions(data: dict) -> str:
    total_count = data.get("total_count", 0)
    sessions = data.get("items", [])
    if not sessions:
        return "  No sessions found."
    showing = f"showing {len(sessions)}" if len(sessions) < total_count else "all"
    lines = [
        _hr("="),
        f"  RECENT SESSIONS  ({total_count} total, {showing})",
        _hr("-"),
        f"  {'SESSION ID':<44} {'PROJECT':<28} {'MSGS':>5} {'REDACT':>6}  MODIFIED",
        _hr("-"),
    ]
    for s in sessions:
        sid = s["session_id"][:42]
        proj = s["project"][:26]
        msgs = s.get("messages", 0)
        redact = s.get("redactions", 0)
        modified = str(s.get("modified_at", ""))[:19]
        lines.append(f"  {sid:<44} {proj:<28} {msgs:>5} {redact:>6}  {modified}")
    lines.append(_hr("="))
    return "\n".join(lines)


def _fmt_patterns(data: dict) -> str:
    lines = [
        _hr("="),
        f"  PATTERN ANALYSIS  (last {data.get('period_days', '?')} days)",
        _hr("="),
        f"  Avg daily sessions  : {data.get('avg_daily_sessions', 0)}",
    ]

    # Peak hours
    peak = data.get("peak_hours", {})
    if peak:
        lines.append("")
        lines.append("  Peak hours (UTC):")
        top_hours = sorted(peak.items(), key=lambda x: -x[1])[:6]
        for hour, count in top_hours:
            bar = "#" * min(count, 30)
            lines.append(f"    {int(hour):02d}:00  {bar} {count}")

    # Common projects
    common = data.get("common_projects", [])
    if common:
        lines.append("")
        lines.append("  Most active projects:")
        for p in common[:5]:
            lines.append(f"    {p['project']:<35}  {p['sessions']} sessions")

    # Length distribution
    dist = data.get("session_length_distribution", {})
    if dist:
        lines.append("")
        lines.append("  Session length distribution:")
        for bucket, count in sorted(dist.items()):
            lines.append(f"    {bucket:>8} messages  : {count} sessions")

    # Redaction hotspots
    hotspots = data.get("redaction_hotspots", {})
    if hotspots:
        lines.append("")
        lines.append("  Redaction hotspots by category:")
        for cat, count in list(hotspots.items())[:8]:
            lines.append(f"    {cat:<30}  {count}")

    lines.append(_hr("="))
    return "\n".join(lines)


def _fmt_trends(data: dict) -> str:
    if not data:
        return "  No trend data available."
    lines = [
        _hr("="),
        "  PRODUCTIVITY TRENDS (by ISO week)",
        _hr("-"),
        f"  {'WEEK':<12} {'SESSIONS':>9} {'MESSAGES':>10}"
        f" {'AVG LEN':>8} {'PROJECTS':>9} {'REDACTS':>8}",
        _hr("-"),
    ]
    for wk in sorted(data.keys()):
        d = data[wk]
        lines.append(
            f"  {wk:<12} {d['sessions_count']:>9} {d['total_messages']:>10} "
            f"{d['avg_session_length']:>8.1f} {d['unique_projects']:>9} {d['redactions_count']:>8}"
        )
    lines.append(_hr("="))
    return "\n".join(lines)


def _fmt_digest(data: dict) -> str:
    period = data.get("period", {})
    stats = data.get("summary_stats", {})
    comp = data.get("comparison_vs_previous_week", {})
    lines = [
        _hr("="),
        f"  WEEKLY DIGEST  {period.get('iso_week', '')}",
        f"  {period.get('start', '')[:10]} to {period.get('end', '')[:10]}",
        _hr("="),
        f"  Sessions          : {stats.get('total_sessions', 0)}"
        f"  ({comp.get('sessions_change', 'N/A')} vs prev week)",
        f"  Messages          : {stats.get('total_messages', 0)}"
        f"  ({comp.get('messages_change', 'N/A')} vs prev week)",
        f"  Avg length        : {stats.get('avg_session_length', 0)} msgs",
        f"  Unique projects   : {stats.get('unique_projects', 0)}",
        f"  Redactions        : {stats.get('total_redactions', 0)}"
        f"  ({comp.get('redactions_change', 'N/A')} vs prev week)",
    ]

    top = data.get("top_projects", [])
    if top:
        lines.append("")
        lines.append("  Top projects this week:")
        for p in top:
            lines.append(f"    {p['project']:<35}  {p['sessions']} sessions")

    notable = data.get("notable_sessions", [])
    if notable:
        lines.append("")
        lines.append("  Notable sessions (by message count):")
        for s in notable:
            lines.append(f"    {s['session_id'][:30]:<32}  {s['messages']:>5} msgs  {s['project']}")

    sec = data.get("security_report", {})
    cats = sec.get("categories", {})
    if cats:
        lines.append("")
        lines.append("  Security — redaction categories this week:")
        for cat, count in list(cats.items())[:5]:
            lines.append(f"    {cat:<30}  {count}")

    lines.append("")
    lines.append("  Previous week:")
    lines.append(f"    Sessions  : {comp.get('previous_week_sessions', 0)}")
    lines.append(f"    Messages  : {comp.get('previous_week_messages', 0)}")
    lines.append(_hr("="))
    return "\n".join(lines)


def _fmt_security(data: dict) -> str:
    lines = [
        _hr("="),
        f"  SECURITY REPORT  (last {data.get('period_days', '?')} days)",
        _hr("="),
        f"  Total redactions    : {data.get('total_redactions', 0)}",
    ]

    cats = data.get("categories_breakdown", {})
    if cats:
        lines.append("")
        lines.append("  Categories breakdown:")
        for cat, count in list(cats.items())[:10]:
            lines.append(f"    {cat:<35}  {count:>6}")

    trend = data.get("trend_by_day", {})
    if trend:
        lines.append("")
        lines.append("  Trend by day (recent):")
        for day, count in list(sorted(trend.items()))[-7:]:
            bar = "#" * min(count, 30)
            lines.append(f"    {day}  {bar} {count}")

    affected = data.get("most_affected_projects", [])
    if affected:
        lines.append("")
        lines.append("  Most affected projects:")
        for p in affected[:5]:
            lines.append(f"    {p['project']:<40}  {p['total_redactions']} redactions")

    unproc = data.get("unprocessed_sessions", {})
    unproc_count = unproc.get("count", 0)
    lines.append("")
    lines.append(f"  Unprocessed sessions  : {unproc_count}")
    if unproc_count > 0:
        for s in unproc.get("sessions", [])[:5]:
            lines.append(f"    {s['session_id'][:32]:<34}  {s['messages']:>5} msgs  {s['project']}")

    lines.append(_hr("="))
    return "\n".join(lines)


# ======================== Subcommand Handlers ========================


def cmd_stats(args: argparse.Namespace, client: SessionIntelligenceClient) -> None:
    data = client.session_stats(days=args.days)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
    else:
        print(_fmt_stats(data))


def cmd_sessions(args: argparse.Namespace, client: SessionIntelligenceClient) -> None:
    data = client.session_list(days=args.days, project=args.project, limit=args.limit)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
    else:
        print(_fmt_sessions(data))


def cmd_patterns(args: argparse.Namespace, client: SessionIntelligenceClient) -> None:
    data = client.pattern_analysis(days=args.days)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
    else:
        print(_fmt_patterns(data))


def cmd_trends(args: argparse.Namespace, client: SessionIntelligenceClient) -> None:
    data = client.productivity_trends(weeks=args.weeks)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
    else:
        print(_fmt_trends(data))


def cmd_digest(args: argparse.Namespace, client: SessionIntelligenceClient) -> None:
    data = client.weekly_digest(week_offset=args.week_offset)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
    else:
        print(_fmt_digest(data))

    # Flywheel bridge: push digest to Core memvault (best-effort)
    if not args.no_publish:
        _publish_digest_to_memvault(data)


def _publish_digest_to_memvault(data: dict) -> None:
    """Best-effort push digest to Core memvault intelligence/ingest endpoint."""
    try:
        from workshop.clients.memvault import MemvaultClient

        period = data.get("period", {})
        iso_week = period.get("iso_week", "")
        content = json.dumps(data, ensure_ascii=False, default=str)

        mc = MemvaultClient()
        result = mc.intelligence_ingest(
            content=content,
            digest_type="weekly",
            period=iso_week,
        )
        print(f"  [flywheel] Digest published to memvault: {result.get('status', 'ok')}")
    except Exception as exc:
        print(f"  [flywheel] Digest publish skipped: {exc}", file=sys.stderr)


def cmd_security(args: argparse.Namespace, client: SessionIntelligenceClient) -> None:
    data = client.security_report(days=args.days)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
    else:
        print(_fmt_security(data))


# ======================== Argument Parser ========================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intelligence",
        description="Session Intelligence — cross-session analytics and insights.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON (pipeable to jq)",
    )
    parser.add_argument(
        "--redactor-db",
        default=None,
        help="Path to session_redactor.sqlite (overrides REDACTOR_DB_PATH env)",
    )
    parser.add_argument(
        "--projects-dir",
        default=None,
        help="Path to Claude Code projects directory (overrides default ~/.claude/projects)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # stats
    p_stats = sub.add_parser("stats", help="Session statistics")
    p_stats.add_argument("--days", type=int, default=30, help="Look-back period (default: 30)")
    p_stats.set_defaults(func=cmd_stats)

    # sessions
    p_sessions = sub.add_parser("sessions", help="List recent sessions")
    p_sessions.add_argument("--days", type=int, default=7, help="Look-back period (default: 7)")
    p_sessions.add_argument(
        "--project", default=None, help="Filter by project name (partial match)"
    )
    p_sessions.add_argument(
        "--limit", type=int, default=0, help="Max sessions to return (default: 0 = all)"
    )
    p_sessions.set_defaults(func=cmd_sessions)

    # patterns
    p_patterns = sub.add_parser("patterns", help="Pattern analysis")
    p_patterns.add_argument("--days", type=int, default=30, help="Look-back period (default: 30)")
    p_patterns.set_defaults(func=cmd_patterns)

    # trends
    p_trends = sub.add_parser("trends", help="Productivity trends by week")
    p_trends.add_argument("--weeks", type=int, default=4, help="Number of weeks (default: 4)")
    p_trends.set_defaults(func=cmd_trends)

    # digest
    p_digest = sub.add_parser("digest", help="Weekly digest")
    p_digest.add_argument(
        "--week-offset",
        type=int,
        default=0,
        help="0=current week, 1=last week, etc. (default: 0)",
    )
    p_digest.add_argument(
        "--no-publish",
        action="store_true",
        help="Skip publishing digest to memvault (flywheel bridge)",
    )
    p_digest.set_defaults(func=cmd_digest)

    # security
    p_security = sub.add_parser("security", help="Security report")
    p_security.add_argument("--days", type=int, default=30, help="Look-back period (default: 30)")
    p_security.set_defaults(func=cmd_security)

    return parser


# ======================== Main ========================


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    client = SessionIntelligenceClient(
        redactor_db=args.redactor_db,
        projects_dir=args.projects_dir,
    )

    try:
        args.func(args, client)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
