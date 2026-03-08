#!/Users/joneshong/.local/bin/python3
"""Intelflow CLI — intelligence report & briefing management.

Usage:
    intelflow reports list [--topic T] [--tag T] [--limit N]
    intelflow reports get <id>
    intelflow reports search <query> [--limit N]
    intelflow reports check <query> [--threshold 0.7]
    intelflow reports create --title T --query Q --content C [--tags t1,t2] [--sources JSON] [--skill S]
    intelflow topics list
    intelflow topics graph
    intelflow briefings list [--date-from D] [--date-to D]
    intelflow briefings get <date> <domain>
    intelflow dashboard
    intelflow status

Symlink: ln -sf ~/workshop/core/cli/intelflow.py ~/.local/bin/intelflow
"""

import argparse
import json
import sys

from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.intelflow import IntelflowClient


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def cmd_reports_list(args):
    client = IntelflowClient()
    try:
        result = client.list_reports(
            page=args.page,
            page_size=args.limit,
            tag=args.tag,
            topic_id=args.topic,
        )
        if args.json:
            _json_out(result, True)
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Reports ({len(items)} of {total}):\n")
        for r in items:
            date = str(r.get("created_at", ""))[:10]
            tags = ", ".join(r.get("tags", [])[:3])
            print(f"  [{date}] {r.get('title', '?')[:60]}")
            if tags:
                print(f"           tags: {tags}")
            print(f"           id={r.get('id', '?')[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reports_get(args):
    client = IntelflowClient()
    try:
        r = client.get_report(args.id)
        if args.json:
            _json_out(r, True)
            return
        print(f"Title: {r.get('title', '?')}")
        print(f"Query: {r.get('query', '-')}")
        print(f"Tags: {', '.join(r.get('tags', []))}")
        print(f"Created: {str(r.get('created_at', ''))[:19]}")
        print(f"\n{r.get('content', '')[:2000]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reports_search(args):
    client = IntelflowClient()
    try:
        results = client.semantic_search(args.query, limit=args.limit)
        if args.json:
            _json_out(results, True)
            return
        if not results:
            print("No results found.")
            return
        items = results if isinstance(results, list) else results.get("items", [])
        print(f"Search results for '{args.query}':\n")
        for r in items:
            score = r.get("score", r.get("similarity", 0))
            print(f"  [{score:.3f}] {r.get('title', '?')[:60]}")
            print(f"           id={r.get('id', r.get('report_id', '?'))[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reports_check(args):
    client = IntelflowClient()
    try:
        result = client.check_duplicate(args.query, threshold=args.threshold)
        if args.json:
            _json_out(result, True)
            return
        if result.get("exists"):
            matches = result.get("matches", [])
            print(f"Found {len(matches)} similar report(s):\n")
            for m in matches:
                score = m.get("score", 0)
                rpt = m.get("report", m)
                print(f"  [{score:.3f}] {rpt.get('title', '?')[:60]}")
                print(f"           id={rpt.get('id', '?')[:12]}")
        else:
            print("No similar reports found.")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reports_create(args):
    client = IntelflowClient()
    try:
        sources = json.loads(args.sources) if args.sources else []
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
        result = client.create_report(
            title=args.title,
            query=args.query,
            content=args.content,
            sources=sources,
            tags=tags,
            skill_name=args.skill,
        )
        if args.json:
            _json_out(result, True)
            return
        print(f"Report created: {result.get('id', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_topics_list(args):
    client = IntelflowClient()
    try:
        result = client.list_topics(page_size=args.limit)
        if args.json:
            _json_out(result, True)
            return
        items = result.get("items", []) if isinstance(result, dict) else result
        print(f"Topics ({len(items)}):\n")
        for t in items:
            count = t.get("report_count", 0)
            print(f"  {t.get('name', '?'):30s}  reports: {count:>4d}  id={t.get('id', '?')[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_topics_graph(args):
    client = IntelflowClient()
    try:
        graph = client.get_topic_graph()
        _json_out(graph, True)
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_briefings_list(args):
    client = IntelflowClient()
    try:
        result = client.list_briefings(
            date_from=args.date_from,
            date_to=args.date_to,
            page_size=args.limit,
        )
        if args.json:
            _json_out(result, True)
            return
        items = result.get("items", []) if isinstance(result, dict) else result
        print(f"Briefings ({len(items)}):\n")
        for b in items:
            date = str(b.get("briefing_date", b.get("created_at", "")))[:10]
            domain = b.get("domain", "?")
            print(f"  [{date}] {domain:20s}  id={b.get('id', '?')[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_briefings_get(args):
    client = IntelflowClient()
    try:
        b = client.get_briefing(args.date, args.domain)
        if args.json:
            _json_out(b, True)
            return
        print(f"Date: {args.date}")
        print(f"Domain: {args.domain}")
        content = b.get("content", b.get("summary", ""))
        print(f"\n{content[:3000]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dashboard(args):
    client = IntelflowClient()
    try:
        d = client.get_dashboard()
        if args.json:
            _json_out(d, True)
            return
        print("Intelflow Dashboard")
        print("=" * 40)
        for k, v in d.items():
            print(f"  {k}: {v}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    client = IntelflowClient()
    try:
        s = client.status()
        _json_out(s, args.json)
        if not args.json:
            print(f"Status: {s.get('status', 'unknown')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="intelflow",
        description="Intelflow — intelligence report & briefing CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # reports
    p_reports = sub.add_parser("reports", help="Report management")
    rsub = p_reports.add_subparsers(dest="reports_cmd", required=True)

    p_rlist = rsub.add_parser("list", help="List reports")
    p_rlist.add_argument("--topic", help="Filter by topic ID")
    p_rlist.add_argument("--tag", help="Filter by tag")
    p_rlist.add_argument("--limit", type=int, default=20)
    p_rlist.add_argument("--page", type=int, default=1)
    p_rlist.set_defaults(func=cmd_reports_list)

    p_rget = rsub.add_parser("get", help="Get report by ID")
    p_rget.add_argument("id", help="Report ID")
    p_rget.set_defaults(func=cmd_reports_get)

    p_rsearch = rsub.add_parser("search", help="Semantic search")
    p_rsearch.add_argument("query", help="Search query")
    p_rsearch.add_argument("--limit", type=int, default=5)
    p_rsearch.set_defaults(func=cmd_reports_search)

    p_rcheck = rsub.add_parser("check", help="Check for duplicate reports")
    p_rcheck.add_argument("query", help="Query to check")
    p_rcheck.add_argument("--threshold", type=float, default=0.7)
    p_rcheck.set_defaults(func=cmd_reports_check)

    p_rcreate = rsub.add_parser("create", help="Create a new report")
    p_rcreate.add_argument("--title", required=True, help="Report title")
    p_rcreate.add_argument("--query", required=True, help="Original query")
    p_rcreate.add_argument("--content", required=True, help="Report content (Markdown)")
    p_rcreate.add_argument("--tags", help="Comma-separated tags")
    p_rcreate.add_argument(
        "--sources", help='JSON array of sources, e.g. [{"url":"...","title":"..."}]'
    )
    p_rcreate.add_argument("--skill", help="Skill name (e.g. smart-search)")
    p_rcreate.set_defaults(func=cmd_reports_create)

    # topics
    p_topics = sub.add_parser("topics", help="Topic management")
    tsub = p_topics.add_subparsers(dest="topics_cmd", required=True)

    p_tlist = tsub.add_parser("list", help="List topics")
    p_tlist.add_argument("--limit", type=int, default=50)
    p_tlist.set_defaults(func=cmd_topics_list)

    p_tgraph = tsub.add_parser("graph", help="Topic relationship graph (JSON)")
    p_tgraph.set_defaults(func=cmd_topics_graph)

    # briefings
    p_briefings = sub.add_parser("briefings", help="Briefing management")
    bsub = p_briefings.add_subparsers(dest="briefings_cmd", required=True)

    p_blist = bsub.add_parser("list", help="List briefings")
    p_blist.add_argument("--date-from", help="Start date (YYYY-MM-DD)")
    p_blist.add_argument("--date-to", help="End date (YYYY-MM-DD)")
    p_blist.add_argument("--limit", type=int, default=20)
    p_blist.set_defaults(func=cmd_briefings_list)

    p_bget = bsub.add_parser("get", help="Get briefing by date and domain")
    p_bget.add_argument("date", help="Date (YYYY-MM-DD)")
    p_bget.add_argument("domain", help="Domain name")
    p_bget.set_defaults(func=cmd_briefings_get)

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Dashboard summary")
    p_dash.set_defaults(func=cmd_dashboard)

    # status
    p_status = sub.add_parser("status", help="Module status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
