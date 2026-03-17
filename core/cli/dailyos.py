#!/Users/joneshong/.local/bin/python3
"""DailyOS CLI — daily method & plan management.

Usage:
    dailyos methods list [--include-presets] [--limit N] [--json]
    dailyos methods get <id> [--json]
    dailyos methods create --slug S --name N [--name-zh Z] [--description D] [--icon I] [--config JSON] [--json]
    dailyos methods clone <id> [--json]
    dailyos methods delete <id>

    dailyos config active [--context C] [--json]
    dailyos config activate <method_id> [--context C] [--overrides JSON] [--json]
    dailyos config deactivate <selection_id> [--json]
    dailyos config guide [--context C]
    dailyos config history [--context C] [--limit N] [--json]

    dailyos plans list [--limit N] [--date-from D] [--date-to D] [--json]
    dailyos plans today [--context C] [--json]
    dailyos plans get <id> [--json]
    dailyos plans update <id> --items JSON [--json]
    dailyos plans transition <id> --status S [--comment C] [--json]

    dailyos status

Symlink: ln -sf ~/workshop/core/cli/dailyos.py ~/.local/bin/dailyos
"""

import argparse
import json
import sys

from cli.cli_utils import resolve_text_arg
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.dailyos import DailyOSClient



# ======================== Methods ========================


def cmd_methods_list(args):
    client = DailyOSClient()
    try:
        result = client.list_methods(
            include_presets=args.include_presets,
            page_size=args.limit,
        )
        if args.json:
            json_out(result, True)
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"📋 Methods ({len(items)} of {total}):\n")
        for m in items:
            preset = " [preset]" if m.get("is_preset") else ""
            icon = m.get("icon") or "•"
            print(f"  {icon}  {m.get('name', '?'):30s}{preset}")
            if m.get("name_zh"):
                print(f"      {m['name_zh']}")
            print(f"      slug={m.get('slug', '?')}  id={str(m.get('id', '?'))[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_methods_get(args):
    client = DailyOSClient()
    try:
        m = client.get_method(args.id)
        if args.json:
            json_out(m, True)
            return
        print(f"Name:        {m.get('name', '?')}")
        if m.get("name_zh"):
            print(f"Name (zh):   {m['name_zh']}")
        print(f"Slug:        {m.get('slug', '?')}")
        print(f"Icon:        {m.get('icon', '-')}")
        print(f"Is preset:   {m.get('is_preset', False)}")
        print(f"ID:          {m.get('id', '?')}")
        if m.get("description"):
            print(f"\nDescription:\n  {m['description']}")
        if m.get("config"):
            print(f"\nConfig:\n  {json.dumps(m['config'], ensure_ascii=False, indent=2)}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_methods_create(args):
    client = DailyOSClient()
    try:
        try:
            config = json.loads(args.config) if args.config else None
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON for --config: {e}", file=sys.stderr)
            sys.exit(1)
        data = {"slug": args.slug, "name": args.name}
        if args.name_zh:
            data["name_zh"] = args.name_zh
        description = resolve_text_arg(args.description)
        if description:
            data["description"] = description
        if args.icon:
            data["icon"] = args.icon
        if config is not None:
            data["config"] = config
        result = client.create_method(data)
        if args.json:
            json_out(result, True)
            return
        print(f"✅ Method created: {result.get('id', '?')}")
        print(f"   name={result.get('name', '?')}  slug={result.get('slug', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_methods_clone(args):
    client = DailyOSClient()
    try:
        result = client.clone_method(args.id)
        if args.json:
            json_out(result, True)
            return
        print(f"✅ Method cloned: {result.get('id', '?')}")
        print(f"   name={result.get('name', '?')}  slug={result.get('slug', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_methods_delete(args):
    client = DailyOSClient()
    try:
        client.delete_method(args.id)
        print(f"🗑  Method deleted: {args.id}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Config ========================


def cmd_config_active(args):
    client = DailyOSClient()
    try:
        result = client.get_active_methods(context=args.context)
        if args.json:
            json_out(result, True)
            return
        items = result if isinstance(result, list) else result.get("items", [])
        print(f"⚡ Active methods for context '{args.context}' ({len(items)}):\n")
        for sel in items:
            m = sel.get("method") or sel
            print(f"  • {m.get('name', '?'):30s}  selection_id={str(sel.get('id', '?'))[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_config_activate(args):
    client = DailyOSClient()
    try:
        try:
            overrides = json.loads(args.overrides) if args.overrides else None
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON for --overrides: {e}", file=sys.stderr)
            sys.exit(1)
        result = client.activate_method(
            method_id=args.method_id,
            context=args.context,
            overrides=overrides,
        )
        if args.json:
            json_out(result, True)
            return
        print(f"✅ Method activated: selection_id={result.get('id', '?')}")
        m = result.get("method") or {}
        print(f"   method={m.get('name', args.method_id)}  context={args.context}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_config_deactivate(args):
    client = DailyOSClient()
    try:
        client.deactivate_method(args.selection_id)
        print(f"🗑  Selection deactivated: {args.selection_id}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_config_guide(args):
    client = DailyOSClient()
    try:
        result = client.get_guide(context=args.context)
        method_names = result.get("method_names", [])
        count = result.get("method_count", len(method_names))
        print(f"📖 Composite Guide — {count} method(s): {', '.join(method_names)}\n")
        print(result.get("guide", "(no guide)"))
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_config_history(args):
    client = DailyOSClient()
    try:
        result = client.get_method_history(context=args.context, page_size=args.limit)
        if args.json:
            json_out(result, True)
            return
        items = result.get("items", []) if isinstance(result, dict) else result
        print(f"🕓 Method history for context '{args.context}' ({len(items)}):\n")
        for h in items:
            date = str(h.get("created_at", ""))[:19]
            m = h.get("method") or {}
            action = h.get("action", "activated")
            print(
                f"  [{date}] {action:12s} {m.get('name', '?'):30s}  id={str(h.get('id', '?'))[:12]}"
            )
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Plans ========================


def cmd_plans_list(args):
    client = DailyOSClient()
    try:
        result = client.list_plans(
            page_size=args.limit,
            date_from=args.date_from,
            date_to=args.date_to,
        )
        if args.json:
            json_out(result, True)
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"📅 Plans ({len(items)} of {total}):\n")
        for p in items:
            date = str(p.get("plan_date", p.get("created_at", "")))[:10]
            status = p.get("status", "?")
            score = p.get("completion_score")
            score_str = f"  score={score:.0f}%" if score is not None else ""
            item_count = len(p.get("items", []))
            print(
                f"  [{date}] {status:12s}  items={item_count:>2d}{score_str}  id={str(p.get('id', '?'))[:12]}"
            )
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_plans_today(args):
    client = DailyOSClient()
    try:
        p = client.get_today(context=args.context)
        if args.json:
            json_out(p, True)
            return
        date = str(p.get("plan_date", "today"))
        status = p.get("status", "?")
        items = p.get("items", [])
        score = p.get("completion_score")
        score_str = f"  score={score:.0f}%" if score is not None else ""
        print(f"📅 Today ({date})  status={status}{score_str}")
        if items:
            print(f"\n  Items ({len(items)}):")
            for it in items:
                done = "✅" if it.get("completed") else "⬜"
                print(f"    {done} {it.get('title', it.get('text', '?'))}")
        else:
            print("  (no items)")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_plans_get(args):
    client = DailyOSClient()
    try:
        p = client.get_plan(args.id)
        if args.json:
            json_out(p, True)
            return
        date = str(p.get("plan_date", ""))[:10]
        status = p.get("status", "?")
        score = p.get("completion_score")
        score_str = f"  score={score:.0f}%" if score is not None else ""
        print(f"📅 Plan [{date}]  status={status}{score_str}")
        print(f"   ID: {p.get('id', '?')}")
        items = p.get("items", [])
        if items:
            print(f"\n  Items ({len(items)}):")
            for it in items:
                done = "✅" if it.get("completed") else "⬜"
                print(f"    {done} {it.get('title', it.get('text', '?'))}")
        if p.get("reflection"):
            print(f"\nReflection:\n  {p['reflection']}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_plans_update(args):
    client = DailyOSClient()
    try:
        try:
            items = json.loads(args.items)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON for --items: {e}", file=sys.stderr)
            sys.exit(1)
        result = client.update_plan(args.id, {"items": items})
        if args.json:
            json_out(result, True)
            return
        print(f"✅ Plan updated: {args.id}")
        print(f"   items={len(result.get('items', []))}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_plans_transition(args):
    client = DailyOSClient()
    try:
        result = client.transition_plan(args.id, status=args.status, comment=args.comment)
        if args.json:
            json_out(result, True)
            return
        print(f"✅ Plan transitioned: {args.id}")
        print(f"   status={result.get('status', args.status)}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Status ========================


def cmd_status(args):
    client = DailyOSClient()
    try:
        active_methods = client.get_active_methods()
        today = client.get_today()
        if args.json:
            json_out({"active_methods": active_methods, "today": today}, True)
            return
        method_list = (
            active_methods if isinstance(active_methods, list) else active_methods.get("items", [])
        )
        names = [
            ((sel.get("method") or {}).get("name") or sel.get("name", "?")) for sel in method_list
        ]
        print("🧠 DailyOS Status")
        print(f"{'=' * 40}")
        print(f"  Active methods ({len(names)}): {', '.join(names) if names else '(none)'}")
        date = str(today.get("plan_date", "today"))
        status = today.get("status", "?")
        items = today.get("items", [])
        score = today.get("completion_score")
        score_str = f"  score={score:.0f}%" if score is not None else ""
        print(f"  Today [{date}]: status={status}  items={len(items)}{score_str}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Activity Spans ========================


def cmd_spans_list(args):
    client = DailyOSClient()
    try:
        result = client.list_spans(date_from=args.date_from, date_to=args.date_to)
        if args.json:
            json_out(result, True)
            return
        items = result if isinstance(result, list) else result.get("items", [])
        print(f"📅 Activity Spans ({len(items)}):\n")
        for s in items:
            active = "✅" if s.get("is_active") else "⏸"
            cat = f"  [{s['category']}]" if s.get("category") else ""
            print(
                f"  {active} {s.get('title', '?'):30s}  {s.get('start_date', '?')} ~ {s.get('end_date', '?')}{cat}"
            )
            print(f"      id={str(s.get('id', '?'))[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_spans_create(args):
    client = DailyOSClient()
    try:
        data = {
            "title": args.title,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
        if args.category:
            data["category"] = args.category
        if args.color:
            data["color"] = args.color
        notes = resolve_text_arg(args.notes)
        if notes:
            data["notes"] = notes
        result = client.create_span(data)
        if args.json:
            json_out(result, True)
            return
        print(f"✅ Span created: {result.get('id', '?')}")
        print(f"   {result.get('title')}  {result.get('start_date')} ~ {result.get('end_date')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_spans_get_for_date(args):
    client = DailyOSClient()
    try:
        result = client.get_spans_for_date(args.date)
        if args.json:
            json_out(result, True)
            return
        items = result if isinstance(result, list) else []
        print(f"📅 Spans for {args.date} ({len(items)}):\n")
        for s in items:
            print(f"  • {s.get('title', '?'):30s}  {s.get('start_date', '?')} ~ {s.get('end_date', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_spans_update(args):
    client = DailyOSClient()
    try:
        data = {}
        if args.title:
            data["title"] = args.title
        if args.start_date:
            data["start_date"] = args.start_date
        if args.end_date:
            data["end_date"] = args.end_date
        if args.category:
            data["category"] = args.category
        if args.color:
            data["color"] = args.color
        if args.active is not None:
            data["is_active"] = args.active
        result = client.update_span(args.id, data)
        if args.json:
            json_out(result, True)
            return
        print(f"✅ Span updated: {args.id}")
        print(f"   {result.get('title')}  {result.get('start_date')} ~ {result.get('end_date')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_spans_delete(args):
    client = DailyOSClient()
    try:
        client.delete_span(args.id)
        print(f"🗑  Span deleted: {args.id}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="dailyos",
        description="DailyOS — daily method & plan CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # methods
    p_methods = sub.add_parser("methods", help="Method management")
    msub = p_methods.add_subparsers(dest="methods_cmd", required=True)

    p_mlist = msub.add_parser("list", help="List methods")
    p_mlist.add_argument("--include-presets", action="store_true", default=True)
    p_mlist.add_argument("--limit", type=int, default=20)
    p_mlist.set_defaults(func=cmd_methods_list)

    p_mget = msub.add_parser("get", help="Get method by ID")
    p_mget.add_argument("id", help="Method ID")
    p_mget.set_defaults(func=cmd_methods_get)

    p_mcreate = msub.add_parser("create", help="Create a new method")
    p_mcreate.add_argument("--slug", required=True, help="URL-friendly identifier")
    p_mcreate.add_argument("--name", required=True, help="Display name")
    p_mcreate.add_argument("--name-zh", dest="name_zh", help="Chinese display name")
    p_mcreate.add_argument("--description", help="Method description")
    p_mcreate.add_argument("--icon", help="Icon identifier")
    p_mcreate.add_argument("--config", help="Config JSON object")
    p_mcreate.set_defaults(func=cmd_methods_create)

    p_mclone = msub.add_parser("clone", help="Clone a method into current space")
    p_mclone.add_argument("id", help="Method ID to clone")
    p_mclone.set_defaults(func=cmd_methods_clone)

    p_mdel = msub.add_parser("delete", help="Delete a method")
    p_mdel.add_argument("id", help="Method ID")
    p_mdel.set_defaults(func=cmd_methods_delete)

    # config
    p_config = sub.add_parser("config", help="Method selection config")
    csub = p_config.add_subparsers(dest="config_cmd", required=True)

    p_cactive = csub.add_parser("active", help="List active methods")
    p_cactive.add_argument("--context", default="default", help="Context key")
    p_cactive.set_defaults(func=cmd_config_active)

    p_cactivate = csub.add_parser("activate", help="Activate a method")
    p_cactivate.add_argument("method_id", help="Method ID to activate")
    p_cactivate.add_argument("--context", default="default", help="Context key")
    p_cactivate.add_argument("--overrides", help="Config overrides JSON object")
    p_cactivate.set_defaults(func=cmd_config_activate)

    p_cdeactivate = csub.add_parser("deactivate", help="Deactivate a method selection")
    p_cdeactivate.add_argument("selection_id", help="Selection ID to remove")
    p_cdeactivate.set_defaults(func=cmd_config_deactivate)

    p_cguide = csub.add_parser("guide", help="Show composite guide for active methods")
    p_cguide.add_argument("--context", default="default", help="Context key")
    p_cguide.set_defaults(func=cmd_config_guide)

    p_chistory = csub.add_parser("history", help="Method activation history")
    p_chistory.add_argument("--context", default="default", help="Context key")
    p_chistory.add_argument("--limit", type=int, default=20)
    p_chistory.set_defaults(func=cmd_config_history)

    # plans
    p_plans = sub.add_parser("plans", help="Daily plan management")
    psub = p_plans.add_subparsers(dest="plans_cmd", required=True)

    p_plist = psub.add_parser("list", help="List daily plans")
    p_plist.add_argument("--limit", type=int, default=20)
    p_plist.add_argument("--date-from", dest="date_from", help="Start date (YYYY-MM-DD)")
    p_plist.add_argument("--date-to", dest="date_to", help="End date (YYYY-MM-DD)")
    p_plist.set_defaults(func=cmd_plans_list)

    p_ptoday = psub.add_parser("today", help="Get or create today's plan")
    p_ptoday.add_argument("--context", default="default", help="Context key")
    p_ptoday.set_defaults(func=cmd_plans_today)

    p_pget = psub.add_parser("get", help="Get plan by ID")
    p_pget.add_argument("id", help="Plan ID")
    p_pget.set_defaults(func=cmd_plans_get)

    p_pupdate = psub.add_parser("update", help="Update plan items")
    p_pupdate.add_argument("id", help="Plan ID")
    p_pupdate.add_argument("--items", required=True, help="Items JSON array")
    p_pupdate.set_defaults(func=cmd_plans_update)

    p_ptrans = psub.add_parser("transition", help="Transition plan status")
    p_ptrans.add_argument("id", help="Plan ID")
    p_ptrans.add_argument("--status", required=True, help="Target status")
    p_ptrans.add_argument("--comment", help="Transition comment")
    p_ptrans.set_defaults(func=cmd_plans_transition)

    # spans
    p_spans = sub.add_parser("spans", help="Activity span management")
    ssub = p_spans.add_subparsers(dest="spans_cmd", required=True)

    p_slist = ssub.add_parser("list", help="List activity spans")
    p_slist.add_argument("--date-from", dest="date_from", help="Start date (YYYY-MM-DD)")
    p_slist.add_argument("--date-to", dest="date_to", help="End date (YYYY-MM-DD)")
    p_slist.set_defaults(func=cmd_spans_list)

    p_screate = ssub.add_parser("create", help="Create an activity span")
    p_screate.add_argument("--title", required=True, help="Span title")
    p_screate.add_argument("--start-date", dest="start_date", required=True, help="Start date (YYYY-MM-DD)")
    p_screate.add_argument("--end-date", dest="end_date", required=True, help="End date (YYYY-MM-DD)")
    p_screate.add_argument("--category", help="Category label")
    p_screate.add_argument("--color", help="Hex color code")
    p_screate.add_argument("--notes", help="Notes")
    p_screate.set_defaults(func=cmd_spans_create)

    p_sdate = ssub.add_parser("get-for-date", help="Get spans for a date")
    p_sdate.add_argument("date", help="Target date (YYYY-MM-DD)")
    p_sdate.set_defaults(func=cmd_spans_get_for_date)

    p_supdate = ssub.add_parser("update", help="Update an activity span")
    p_supdate.add_argument("id", help="Span ID")
    p_supdate.add_argument("--title", help="New title")
    p_supdate.add_argument("--start-date", dest="start_date", help="New start date")
    p_supdate.add_argument("--end-date", dest="end_date", help="New end date")
    p_supdate.add_argument("--category", help="New category")
    p_supdate.add_argument("--color", help="New color")
    p_supdate.add_argument("--active", type=lambda x: x.lower() in ("true", "1", "yes"), default=None, help="Active state")
    p_supdate.set_defaults(func=cmd_spans_update)

    p_sdelete = ssub.add_parser("delete", help="Delete an activity span")
    p_sdelete.add_argument("id", help="Span ID")
    p_sdelete.set_defaults(func=cmd_spans_delete)

    # status
    p_status = sub.add_parser("status", help="DailyOS summary status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    # propagate top-level --json to subparser namespace
    if not hasattr(args, "json"):
        args.json = False
    args.func(args)


if __name__ == "__main__":
    main()
