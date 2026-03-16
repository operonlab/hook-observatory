#!/Users/joneshong/.local/bin/python3
"""Capture CLI — quick capture with smart defaults.

Uses the shared workshop SDK client (CaptureClient).

Usage:
    capture add <module> <entity_type> [--payload JSON] [--raw "text"] [--json]
    capture list [--module M] [--status S] [--json]
    capture show <id> [--json]
    capture fill <id> --payload JSON [--json]
    capture promote <id> [--json]
    capture delete <id>
    capture stats [--json]
    capture batch-promote <id1> <id2> ...
    capture batch-fill <id1> <id2> ... -p '{"wallet_id":"xxx"}'
    capture history <id> [--json]

Symlink: ln -sf ~/workshop/core/cli/capture.py ~/.local/bin/capture
"""

import argparse
import json
import sys

from cli.cli_utils import resolve_text_arg
from cli.exit_codes import EXIT_VALIDATION, exit_code_for
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.capture import CaptureClient


def _json_out(data, args):
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return True
    return False


def _err(exc):
    print(f"Error: {exc}", file=sys.stderr)
    sys.exit(exit_code_for(exc))


def _client():
    return CaptureClient()


def _bar(completeness: float) -> str:
    pct = int(completeness * 100)
    filled = pct // 10
    return f"[{'█' * filled}{'░' * (10 - filled)}] {pct}%"


# ── Commands ──────────────────────────────────────────────────────


def cmd_add(args):
    c = _client()
    try:
        payload_raw = resolve_text_arg(args.payload)
        payload = json.loads(payload_raw) if payload_raw else {}
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON payload: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        result = c.create(
            module=args.module,
            entity_type=args.entity_type,
            payload=payload,
            raw_input=args.raw,
        )
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(result, args):
        return

    print(f"Captured: {result['id']}")
    print(f"  Completeness: {_bar(result.get('completeness', 0))}")
    missing = result.get("missing_fields", [])
    if missing:
        print(f"  Missing: {', '.join(missing)}")
    if result.get("expires_at"):
        print(f"  Expires: {result['expires_at'][:10]}")


def cmd_list(args):
    c = _client()
    try:
        items = c.list(
            module=args.module,
            status=args.status,
            limit=args.limit,
        )
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(items, args):
        return

    if not items:
        print("No captures.")
        return

    for cap in items:
        pct = int(cap.get("completeness", 0) * 100)
        desc = cap.get("payload", {}).get("description", cap.get("raw_input", ""))
        if desc and len(desc) > 50:
            desc = desc[:47] + "..."
        status = cap["status"]
        mod = f"{cap['module']}/{cap['entity_type']}"
        print(f"  {cap['id'][:12]}  {mod:25s}  {pct:3d}%  {status:8s}  {desc or '-'}")


def cmd_show(args):
    c = _client()
    try:
        result = c.get(args.id)
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(result, args):
        return

    print(f"ID: {result['id']}")
    print(f"Module: {result['module']}/{result['entity_type']}")
    print(f"Status: {result['status']}")
    print(f"Completeness: {_bar(result.get('completeness', 0))}")
    missing = result.get("missing_fields", [])
    if missing:
        print(f"Missing: {', '.join(missing)}")
    print("Payload:")
    for k, v in result.get("payload", {}).items():
        print(f"  {k}: {v}")
    if result.get("raw_input"):
        print(f"Raw: {result['raw_input']}")


def cmd_fill(args):
    c = _client()
    payload = json.loads(resolve_text_arg(args.payload))
    try:
        result = c.update(args.id, payload=payload)
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(result, args):
        return

    print(f"Updated: {_bar(result.get('completeness', 0))}")
    missing = result.get("missing_fields", [])
    if missing:
        print(f"Still missing: {', '.join(missing)}")
    else:
        print("All fields complete — ready to promote!")


def cmd_promote(args):
    c = _client()
    try:
        result = c.promote(args.id)
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(result, args):
        return

    if result.get("success"):
        print(f"Promoted! Record ID: {result['promoted_id']}")
    else:
        print("Promote failed.")
        missing = result.get("missing_fields", [])
        if missing:
            print(f"Missing: {', '.join(missing)}")
        if result.get("error"):
            print(f"Error: {result['error']}")


def cmd_delete(args):
    c = _client()
    try:
        c.delete(args.id)
    except (APIConnectionError, APIError) as e:
        _err(str(e))
    print("Deleted.")


def cmd_stats(args):
    c = _client()
    try:
        result = c.stats()
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(result, args):
        return

    print(f"Total: {result['total']}")
    if result.get("by_module"):
        print("By module:")
        for k, v in result["by_module"].items():
            print(f"  {k}: {v}")
    if result.get("by_status"):
        print("By status:")
        for k, v in result["by_status"].items():
            print(f"  {k}: {v}")


def cmd_batch_promote(args):
    c = _client()
    try:
        results = c.batch_promote(args.ids)
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(results, args):
        return

    print(f"Batch promote: {len(results)} results")
    for r in results:
        cid = r.get("capture_id", r.get("id", "?"))[:12]
        if r.get("success"):
            print(f"  {cid}  promoted -> {r.get('promoted_id', '?')[:12]}")
        else:
            missing = ", ".join(r.get("missing_fields", []))
            error = r.get("error", "failed")
            print(f"  {cid}  FAILED  {error}" + (f" (missing: {missing})" if missing else ""))


def cmd_batch_fill(args):
    c = _client()
    try:
        payload = json.loads(resolve_text_arg(args.payload))
    except json.JSONDecodeError as e:
        _err(f"Invalid JSON payload: {e}")

    try:
        results = c.batch_fill(args.ids, payload)
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(results, args):
        return

    print(f"Batch fill: {len(results)} updated")
    for r in results:
        cid = r.get("id", "?")[:12]
        missing = r.get("missing_fields", [])
        status_str = "complete" if not missing else f"missing: {', '.join(missing)}"
        print(f"  {cid}  {_bar(r.get('completeness', 0))}  {status_str}")


def cmd_history(args):
    c = _client()
    try:
        history = c.enrichments(args.id)
    except (APIConnectionError, APIError) as e:
        _err(str(e))

    if _json_out(history, args):
        return

    if not history:
        print("No enrichment history.")
        return

    print(f"Enrichment history for {args.id[:12]}... ({len(history)} entries)")
    for entry in history:
        agent = entry.get("agent_id", "unknown")
        ts = str(entry.get("created_at", entry.get("timestamp", "")))[:19]
        delta = entry.get("delta", {})
        delta_str = ", ".join(f"{k}={v}" for k, v in delta.items()) if delta else "(no fields)"
        print(f"  {ts}  {agent:20s}  {delta_str}")


# ── Argparse ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="capture", description="Quick capture with smart defaults"
    )
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Capture data")
    p_add.add_argument("module", help="Target module (e.g. finance)")
    p_add.add_argument("entity_type", help="Entity type (e.g. transaction)")
    p_add.add_argument("--payload", "-p", help="JSON payload")
    p_add.add_argument("--raw", "-r", help="Raw natural language input")
    p_add.add_argument("--json", action="store_true")
    p_add.set_defaults(func=cmd_add)

    # list
    p_list = sub.add_parser("list", aliases=["ls"], help="List captures")
    p_list.add_argument("--module", "-m")
    p_list.add_argument("--status", "-s")
    p_list.add_argument("--limit", "-l", type=int, default=20)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="Show capture details")
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=cmd_show)

    # fill
    p_fill = sub.add_parser("fill", help="Fill in missing fields")
    p_fill.add_argument("id")
    p_fill.add_argument("--payload", "-p", required=True, help="JSON fields to add")
    p_fill.add_argument("--json", action="store_true")
    p_fill.set_defaults(func=cmd_fill)

    # promote
    p_promote = sub.add_parser("promote", help="Promote to formal record")
    p_promote.add_argument("id")
    p_promote.add_argument("--json", action="store_true")
    p_promote.set_defaults(func=cmd_promote)

    # delete
    p_del = sub.add_parser("delete", aliases=["rm"], help="Delete capture")
    p_del.add_argument("id")
    p_del.set_defaults(func=cmd_delete)

    # stats
    p_stats = sub.add_parser("stats", help="Capture statistics")
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=cmd_stats)

    # batch-promote
    p_bpromote = sub.add_parser("batch-promote", help="Batch promote multiple captures")
    p_bpromote.add_argument("ids", nargs="+", metavar="id", help="Capture IDs to promote")
    p_bpromote.add_argument("--json", action="store_true")
    p_bpromote.set_defaults(func=cmd_batch_promote)

    # batch-fill
    p_bfill = sub.add_parser("batch-fill", help="Batch fill fields into multiple captures")
    p_bfill.add_argument("ids", nargs="+", metavar="id", help="Capture IDs to update")
    p_bfill.add_argument("--payload", "-p", required=True, help="JSON fields to fill")
    p_bfill.add_argument("--json", action="store_true")
    p_bfill.set_defaults(func=cmd_batch_fill)

    # history
    p_history = sub.add_parser("history", help="Show enrichment history for a capture")
    p_history.add_argument("id", help="Capture ID")
    p_history.add_argument("--json", action="store_true")
    p_history.set_defaults(func=cmd_history)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(EXIT_VALIDATION)
    args.func(args)


if __name__ == "__main__":
    main()
