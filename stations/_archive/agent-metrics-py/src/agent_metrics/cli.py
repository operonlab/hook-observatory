"""Agent Metrics CLI entry point.

Usage:
    python -m agent_metrics serve                             # Start API server
    python -m agent_metrics maestro plan "Build auth module"  # Plan a dispatch
    python -m agent_metrics maestro run "Fix login bug"       # Run a dispatch
    python -m agent_metrics maestro runs                      # List dispatch history
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from agent_metrics.engines import maestro as me


def _json_out(data: dict | list) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


async def _cmd_plan(args: argparse.Namespace) -> None:
    analysis = me.analyze_task(args.task, args.budget)
    result = asdict(analysis)
    explicit = me.detect_explicit_clis(args.task)
    if explicit:
        result["explicit_clis"] = explicit
    _json_out(result)


async def _cmd_run(args: argparse.Namespace) -> None:
    from agent_metrics.config import settings
    from agent_metrics.db import close_pool, get_pool
    from datetime import UTC, datetime

    pool = await get_pool()
    try:
        analysis = me.analyze_task(args.task, args.budget)
        run = me.MaestroRun(
            id=me.generate_run_id(),
            name=me.generate_run_name(),
            pattern=analysis.recommended_pattern,
            task=args.task,
            budget=args.budget,
            cwd=args.cwd or ".",
            phases=analysis.phases,
            started_at=datetime.now(UTC).isoformat(),
        )
        await me.save_run(pool, run)

        timeout = args.timeout
        cwd = args.cwd or None

        if analysis.recommended_pattern == "solo":
            cli = me.route_to_cli(analysis.categories[0], args.budget)
            result = me.dispatch_agent(cli, args.task, cwd, settings.SKILLS_DIR, timeout=timeout)
            run.results = [asdict(result)]
        else:
            # For CLI, default to solo for simplicity
            cli = me.route_to_cli(analysis.categories[0], args.budget)
            result = me.dispatch_agent(cli, args.task, cwd, settings.SKILLS_DIR, timeout=timeout)
            run.results = [asdict(result)]

        run.completed_at = datetime.now(UTC).isoformat()
        started = datetime.fromisoformat(run.started_at)
        run.duration_s = round(
            (datetime.fromisoformat(run.completed_at) - started).total_seconds(), 1
        )
        run.status = "completed"
        await me.save_run(pool, run)
        _json_out(me.generate_report(run))
    finally:
        await close_pool()


async def _cmd_runs(args: argparse.Namespace) -> None:
    from agent_metrics.db import close_pool, get_pool

    pool = await get_pool()
    try:
        runs = await me.list_runs(pool, args.limit)
        _json_out(runs)
    finally:
        await close_pool()


async def _cmd_routing(_args: argparse.Namespace) -> None:
    _json_out({
        "routing": me.get_cli_routing(),
        "templates": me.get_pipeline_templates(),
    })


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from agent_metrics.config import settings

    host = args.host or settings.HOST
    port = args.port or settings.PORT
    uvicorn.run("agent_metrics.main:app", host=host, port=port, reload=args.reload)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-metrics", description="Agent Metrics CLI")
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Start API server")
    p_serve.add_argument("--host", default="")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--reload", action="store_true")

    # maestro
    p_maestro = sub.add_parser("maestro", help="Maestro orchestration")
    msub = p_maestro.add_subparsers(dest="maestro_cmd")

    p_plan = msub.add_parser("plan", help="Analyze task (no execution)")
    p_plan.add_argument("task", help="Task description")
    p_plan.add_argument("--budget", default="balanced", choices=["minimize", "balanced", "maximize_quality"])

    p_run = msub.add_parser("run", help="Execute a dispatch")
    p_run.add_argument("task", help="Task description")
    p_run.add_argument("--budget", default="balanced", choices=["minimize", "balanced", "maximize_quality"])
    p_run.add_argument("--cwd", default="")
    p_run.add_argument("--timeout", type=int, default=300)

    p_runs = msub.add_parser("runs", help="List dispatch history")
    p_runs.add_argument("--limit", type=int, default=50)

    msub.add_parser("routing", help="Show CLI routing table")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "serve":
        _cmd_serve(args)
    elif args.command == "maestro":
        if not args.maestro_cmd:
            p_maestro.print_help()
            sys.exit(1)
        cmd_map = {
            "plan": _cmd_plan,
            "run": _cmd_run,
            "runs": _cmd_runs,
            "routing": _cmd_routing,
        }
        asyncio.run(cmd_map[args.maestro_cmd](args))


if __name__ == "__main__":
    main()
