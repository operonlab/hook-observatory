#!/usr/bin/env python3
"""
LLM Usage Station — CLI entry point.

Usage:
    python3 -m stations.llm-usage <command>
    python3 stations/llm-usage/__main__.py <command>

Commands:
    collect      — Run full dual-track collection
    summary      — Display dual-track summary
    trends       — Display cost trends
    by-model     — Per-model breakdown
    serve        — Start API server
    schedule     — Manage launchd schedule (install/uninstall/status)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


def cmd_collect(args: list[str]) -> None:
    """Run unified collection."""
    import argparse

    parser = argparse.ArgumentParser(description="Collect LLM usage data")
    parser.add_argument("--sub-only", action="store_true")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--compact", action="store_true")
    opts = parser.parse_args(args)

    from collector import UnifiedCollector, load_config

    config = load_config()
    collector = UnifiedCollector(config)

    if opts.sub_only:
        result = collector.collect_subscription()
    elif opts.api_only:
        result = collector.collect_api()
    else:
        result = collector.collect_all()

    indent = None if opts.compact else 2
    print(json.dumps(result, indent=indent, ensure_ascii=False))


def cmd_summary(args: list[str]) -> None:
    """Display dual-track summary."""
    import argparse

    parser = argparse.ArgumentParser(description="Show summary")
    parser.add_argument("--compact", action="store_true")
    opts = parser.parse_args(args)

    from analyzer import generate_summary
    from api_collector import load_config

    config = load_config()
    result = generate_summary(config)
    indent = None if opts.compact else 2
    print(json.dumps(result, indent=indent, ensure_ascii=False))


def cmd_trends(args: list[str]) -> None:
    """Display cost trends."""
    import argparse

    parser = argparse.ArgumentParser(description="Show trends")
    parser.add_argument("--days", "-d", type=int, default=30)
    parser.add_argument("--compact", action="store_true")
    opts = parser.parse_args(args)

    from analyzer import generate_trends
    from api_collector import load_config

    config = load_config()
    result = generate_trends(config, days=opts.days)
    indent = None if opts.compact else 2
    print(json.dumps(result, indent=indent, ensure_ascii=False))


def cmd_by_model(args: list[str]) -> None:
    """Per-model breakdown."""
    import argparse

    parser = argparse.ArgumentParser(description="Show by-model")
    parser.add_argument("--days", "-d", type=int, default=30)
    parser.add_argument("--compact", action="store_true")
    opts = parser.parse_args(args)

    from analyzer import generate_by_model
    from api_collector import load_config

    config = load_config()
    result = generate_by_model(config, days=opts.days)
    indent = None if opts.compact else 2
    print(json.dumps(result, indent=indent, ensure_ascii=False))


def cmd_serve(args: list[str]) -> None:
    """Start API server."""
    import argparse

    parser = argparse.ArgumentParser(description="Start API server")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", type=str)
    opts = parser.parse_args(args)

    from api import main as api_main

    # Re-inject args for api.py's own argparse
    sys.argv = ["api.py"]
    if opts.port:
        sys.argv += ["--port", str(opts.port)]
    if opts.host:
        sys.argv += ["--host", opts.host]
    api_main()


def cmd_schedule(args: list[str]) -> None:
    """Manage launchd schedule."""
    if not args:
        print("Usage: schedule <install|uninstall|status>", file=sys.stderr)
        sys.exit(1)

    subcmd = args[0]
    from scheduler import Scheduler

    scheduler = Scheduler()

    if subcmd == "install":
        scheduler.install()
    elif subcmd == "uninstall":
        scheduler.uninstall()
    elif subcmd == "status":
        info = scheduler.status()
        print(json.dumps(info, indent=2))
    else:
        print(f"Unknown schedule command: {subcmd}", file=sys.stderr)
        sys.exit(1)


COMMANDS = {
    "collect": cmd_collect,
    "summary": cmd_summary,
    "trends": cmd_trends,
    "by-model": cmd_by_model,
    "serve": cmd_serve,
    "schedule": cmd_schedule,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("LLM Usage Station v2.0")
        print()
        print("Commands:")
        print("  collect      Run full dual-track collection")
        print("  summary      Display dual-track summary")
        print("  trends       Display cost trends")
        print("  by-model     Per-model breakdown")
        print("  serve        Start API server")
        print("  schedule     Manage launchd (install/uninstall/status)")
        print()
        print("Usage: python3 __main__.py <command> [options]")
        sys.exit(0)

    cmd_name = sys.argv[1]
    if cmd_name not in COMMANDS:
        print(f"Unknown command: {cmd_name}", file=sys.stderr)
        print(f"Available: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    COMMANDS[cmd_name](sys.argv[2:])


if __name__ == "__main__":
    main()
