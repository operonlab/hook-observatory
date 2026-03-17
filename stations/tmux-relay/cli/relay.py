#!/Users/joneshong/.local/bin/python3
"""relay — tmux-relay CLI.

Usage:
    relay run <command> [--timeout N] [--lines N]
    relay dispatch <command> [--timeout N] [--count N]
    relay check <signal_file>
    relay result <signal_file> [--lines N]
    relay list
    relay status <pane>
    relay acquire [N]
    relay spawn [--session S]
    relay context <pane> [--lines N]
    relay recycle <pane>
    relay standby [<pane>]
    relay reaper
    relay cleanup [--threshold N]
    relay cache show|refresh|clear|ping

Symlink: ln -sf ~/workshop/stations/tmux-relay/cli/relay.py ~/.local/bin/relay
"""

import argparse
import json
import sys

from workshop.clients.tmux_relay import TmuxRelayClient, TmuxRelayError


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def cmd_run(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        result = client.run(
            command=args.command,
            timeout=args.timeout,
            max_lines=args.lines,
        )
        if args.json:
            _json_out(result.to_dict(), True)
        else:
            print(f"Pane: {result.pane}")
            print(f"Status: {result.status}")
            print(f"Elapsed: {result.elapsed}")
            print(f"Result file: {result.result_file}")
            if result.output:
                print(f"\n--- Output ---\n{result.output}")
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dispatch(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        dispatched = client.dispatch(
            command=args.command,
            timeout=args.timeout,
            count=args.count,
        )
        if args.json:
            _json_out(dispatched, True)
        else:
            print(f"Dispatched {len(dispatched)} task(s):\n")
            for d in dispatched:
                print(f"  Pane: {d['pane']}")
                print(f"  Signal: {d['signal_file']}")
                print(f"  PID: {d['pid']}")
                print()
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_check(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    result = client.check(args.signal_file)
    if args.json:
        _json_out(result, True)
    else:
        print(f"Status: {result['status'].upper()}")
        print(f"Signal: {result['signal_file']}")
        if result.get("meta"):
            print(f"\n{result['meta']}")


def cmd_result(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    result = client.result(args.signal_file, max_lines=args.lines)
    if args.json:
        _json_out(result.to_dict(), True)
    else:
        if result.status == "running":
            print("Task not yet completed.")
            sys.exit(1)
        print(f"Status: {result.status}")
        print(f"Elapsed: {result.elapsed}")
        if result.output:
            print(f"\n--- Output ---\n{result.output}")
        elif result.result_file:
            print(f"Result file: {result.result_file}")


def cmd_list(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        panes = client.list_panes()
        if args.json:
            _json_out([p.to_dict() for p in panes], True)
        else:
            if not panes:
                print("No relay panes found.")
                return
            print(f"Relay panes ({len(panes)}):\n")
            for p in panes:
                indicator = "●" if p.status == "idle" else "◌"
                print(f"  {indicator} {p.pane_ref:30s} {p.status:15s} {p.pane_id}")
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        st = client.status(args.pane)
        if args.json:
            _json_out({"pane": args.pane, "status": st}, True)
        else:
            print(f"{args.pane}: {st}")
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_acquire(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        panes = client.acquire(count=args.count)
        if args.json:
            _json_out(panes, True)
        else:
            for p in panes:
                print(p)
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_spawn(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        pane = client.spawn(session=args.session)
        if args.json:
            _json_out({"pane": pane}, True)
        else:
            print(pane)
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_context(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        ctx = client.context(args.pane, lines=args.lines)
        if args.json:
            _json_out({"pane": args.pane, "context": ctx}, True)
        else:
            print(ctx)
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_recycle(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        result = client.recycle(args.pane)
        if args.json:
            _json_out({"pane": args.pane, "result": result}, True)
        else:
            print(f"Recycled: {result}")
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_standby(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        if args.pane:
            result = client.standby(args.pane)
            if args.json:
                _json_out({"pane": args.pane, "result": result}, True)
            else:
                print(f"{args.pane}: {result}")
        else:
            result = client.auto_standby()
            if args.json:
                _json_out({"result": result}, True)
            else:
                print(result)
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reaper(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        result = client.reaper()
        if args.json:
            _json_out({"result": result}, True)
        else:
            print(result)
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_cleanup(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    try:
        result = client.cleanup(threshold=args.threshold)
        if args.json:
            _json_out({"result": result}, True)
        else:
            print(result)
    except TmuxRelayError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_cache(args):
    client = TmuxRelayClient(
        model=getattr(args, "model", None), silent=getattr(args, "silent", False)
    )
    sub = args.cache_action

    if sub == "ping":
        ok = client._cache.ping()
        if args.json:
            _json_out({"redis": "ok" if ok else "unreachable"}, True)
        else:
            print(f"Redis: {'OK' if ok else 'UNREACHABLE'}")
        if not ok:
            sys.exit(1)

    elif sub == "show":
        try:
            panes = client._cache.get_all_panes()
            stats = client._cache.stats()
            if args.json:
                _json_out({"panes": panes, "stats": stats}, True)
            else:
                print(
                    f"Cache fresh: {stats['fresh']}  |  Panes: {stats['panes']}  |  Results: {stats['results']}\n"
                )
                if not panes:
                    print("No cached panes.")
                else:
                    for k, v in panes.items():
                        indicator = "●" if v.get("status") == "idle" else "◌"
                        print(
                            f"  {indicator} [{k}] {v.get('ref', '?'):30s} {v.get('status', '?'):15s}"
                        )
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif sub == "refresh":
        try:
            result = client.refresh_cache()
            if args.json:
                _json_out(result, True)
            else:
                print(f"Cache refreshed: {result['panes']} pane(s)")
        except TmuxRelayError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif sub == "clear":
        try:
            client._cache.clear()
            if args.json:
                _json_out({"cleared": True}, True)
            else:
                print("Cache cleared.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="relay",
        description="tmux-relay — async inter-pane delegation CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--model", help="Claude Code model (e.g. haiku, sonnet)")
    parser.add_argument("--silent", action="store_true", help="Suppress TTS in relay sessions")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # run
    p_run = sub.add_parser("run", help="Blocking relay: send command and wait for result")
    p_run.add_argument("command", help="Command/prompt to send")
    p_run.add_argument("--timeout", type=int, default=600)
    p_run.add_argument("--lines", type=int, default=200, help="Max output lines")
    p_run.set_defaults(func=cmd_run)

    # dispatch
    p_dispatch = sub.add_parser("dispatch", help="Fire-and-forget dispatch")
    p_dispatch.add_argument("command", help="Command/prompt to send")
    p_dispatch.add_argument("--timeout", type=int, default=600)
    p_dispatch.add_argument("--count", type=int, default=1, help="Number of panes")
    p_dispatch.set_defaults(func=cmd_dispatch)

    # check
    p_check = sub.add_parser("check", help="Check if dispatched command completed")
    p_check.add_argument("signal_file", help="Path to .done signal file")
    p_check.set_defaults(func=cmd_check)

    # result
    p_result = sub.add_parser("result", help="Read completed relay output")
    p_result.add_argument("signal_file", help="Path to .done signal file")
    p_result.add_argument("--lines", type=int, default=200, help="Max output lines")
    p_result.set_defaults(func=cmd_result)

    # list
    p_list = sub.add_parser("list", help="List relay panes with status")
    p_list.set_defaults(func=cmd_list)

    # status
    p_status = sub.add_parser("status", help="Check single pane status")
    p_status.add_argument("pane", help="Pane reference")
    p_status.set_defaults(func=cmd_status)

    # acquire
    p_acquire = sub.add_parser("acquire", help="Acquire N panes (auto-spawn)")
    p_acquire.add_argument("count", type=int, nargs="?", default=1, help="Number of panes")
    p_acquire.set_defaults(func=cmd_acquire)

    # spawn
    p_spawn = sub.add_parser("spawn", help="Spawn a new relay pane")
    p_spawn.add_argument("--session", help="tmux session name")
    p_spawn.set_defaults(func=cmd_spawn)

    # context
    p_context = sub.add_parser("context", help="Capture pane conversation context")
    p_context.add_argument("pane", help="Pane reference")
    p_context.add_argument("--lines", type=int, default=30, help="Lines to capture")
    p_context.set_defaults(func=cmd_context)

    # recycle
    p_recycle = sub.add_parser("recycle", help="Recycle a pane (/exit + restart)")
    p_recycle.add_argument("pane", help="Pane reference")
    p_recycle.set_defaults(func=cmd_recycle)

    # standby
    p_standby = sub.add_parser("standby", help="Standby: exit Claude Code, keep pane")
    p_standby.add_argument(
        "pane", nargs="?", default=None, help="Pane reference (omit for auto-sweep)"
    )
    p_standby.set_defaults(func=cmd_standby)

    # reaper
    p_reaper = sub.add_parser("reaper", help="Recycle excess idle panes")
    p_reaper.set_defaults(func=cmd_reaper)

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="Remove stale pending files")
    p_cleanup.add_argument(
        "--threshold", type=int, default=None, help="Staleness threshold (seconds)"
    )
    p_cleanup.set_defaults(func=cmd_cleanup)

    # cache
    p_cache = sub.add_parser("cache", help="Redis cache operations")
    p_cache.add_argument(
        "cache_action",
        choices=["show", "refresh", "clear", "ping"],
        help="Cache action: show|refresh|clear|ping",
    )
    p_cache.set_defaults(func=cmd_cache)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
