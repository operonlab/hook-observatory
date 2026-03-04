#!/Users/joneshong/.local/bin/python3
"""maestro — Agent Metrics orchestration CLI.

Usage:
    maestro plan <task> [--budget B] [--pattern P]
    maestro run <task> [--budget B] [--pattern P] [--cwd PATH] [--timeout N]
    maestro runs [--limit N]
    maestro run-detail <name>
    maestro routing
    maestro project list
    maestro project create <name> [--mode M] [--goal G] [--pipeline P] [--workspace W]
    maestro project status <name>
    maestro project add-task <name> <task_id> [--agent A] [--desc D] [--deps D]
    maestro project ready <name>
    maestro project next <name>
    maestro project update <name> <task_id> <status>
    maestro project result <name> <task_id> <text>
    maestro project add-debater <name> <debater_id> [--agent A] [--perspective P]
    maestro project round <name> <action> [--debater D] [--text T]
    maestro project reset <name>

Symlink: ln -sf ~/workshop/stations/agent-metrics/cli/maestro.py ~/.local/bin/maestro
"""

import argparse
import json
import sys

from workshop.clients.agent_metrics import AgentMetricsClient, AgentMetricsError


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def _err(e):
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


# ======================== Maestro Commands ========================


def cmd_plan(args):
    client = AgentMetricsClient()
    try:
        result = client.plan(args.task, budget=args.budget, pattern=args.pattern)
        if args.json:
            _json_out(result, True)
        else:
            print(f"Pattern: {result.get('recommended_pattern', '?')}")
            print(f"Complexity: {result.get('complexity', '?')}")
            print(f"Categories: {', '.join(result.get('categories', []))}")
            if result.get("explicit_clis"):
                print(f"Explicit CLIs: {', '.join(result['explicit_clis'])}")
            if result.get("phases"):
                print("\nPhases:")
                for i, p in enumerate(result["phases"], 1):
                    print(f"  {i}. [{p.get('cli', '?')}] {p.get('role', '?')}")
    except AgentMetricsError as e:
        _err(e)


def cmd_run(args):
    client = AgentMetricsClient()
    try:
        result = client.run(
            args.task,
            budget=args.budget,
            pattern=args.pattern,
            cwd=args.cwd,
            timeout=args.timeout,
        )
        if args.json:
            _json_out(result, True)
        else:
            print(f"Name: {result.get('name', '?')}")
            print(f"Pattern: {result.get('pattern', '?')}")
            print(f"Duration: {result.get('duration_s', '?')}s")
            print(f"Agents: {result.get('agents_completed', 0)}/{result.get('agents_total', 0)}")
            for r in result.get("results", []):
                print(
                    f"\n--- [{r.get('cli', '?')}] {r.get('status', '?')} ({r.get('duration_s', '?')}s) ---"
                )
                if r.get("output"):
                    print(r["output"][:2000])
    except AgentMetricsError as e:
        _err(e)


def cmd_runs(args):
    client = AgentMetricsClient()
    try:
        runs = client.list_runs(limit=args.limit)
        if args.json:
            _json_out(runs, True)
        else:
            if not runs:
                print("No dispatch runs found.")
                return
            print(f"{'Name':<35} {'Pattern':<12} {'Status':<10} {'Duration':>8}")
            print("-" * 70)
            for r in runs:
                duration = f"{r.get('duration_s', 0):.1f}s" if r.get("duration_s") else "-"
                print(
                    f"{r.get('name', '?'):<35} {r.get('pattern', '?'):<12} {r.get('status', '?'):<10} {duration:>8}"
                )
    except AgentMetricsError as e:
        _err(e)


def cmd_run_detail(args):
    client = AgentMetricsClient()
    try:
        run = client.get_run(args.name)
        if args.json:
            _json_out(run, True)
        else:
            print(json.dumps(run, indent=2, ensure_ascii=False, default=str))
    except AgentMetricsError as e:
        _err(e)


def cmd_routing(args):
    client = AgentMetricsClient()
    try:
        table = client.routing_table()
        if args.json:
            _json_out(table, True)
        else:
            print(json.dumps(table, indent=2, ensure_ascii=False))
    except AgentMetricsError as e:
        _err(e)


# ======================== Project Commands ========================


def cmd_project_list(args):
    client = AgentMetricsClient()
    try:
        projects = client.list_projects()
        if args.json:
            _json_out(projects, True)
        else:
            if not projects:
                print("No projects found.")
                return
            print(f"{'Name':<25} {'Mode':<10} {'Status':<10} Goal")
            print("-" * 70)
            for p in projects:
                print(
                    f"{p.get('name', '?'):<25} {p.get('mode', '?'):<10} {p.get('status', '?'):<10} {p.get('goal', '')[:30]}"
                )
    except AgentMetricsError as e:
        _err(e)


def cmd_project_create(args):
    client = AgentMetricsClient()
    try:
        result = client.create_project(
            args.name,
            mode=args.mode,
            goal=args.goal,
            pipeline=args.pipeline,
            workspace=args.workspace,
        )
        if args.json:
            _json_out(result, True)
        else:
            print(f"Created project: {args.name} (mode={args.mode})")
    except AgentMetricsError as e:
        _err(e)


def cmd_project_status(args):
    client = AgentMetricsClient()
    try:
        proj = client.get_project(args.name)
        if args.json:
            _json_out(proj, True)
        else:
            print(f"Project: {proj.get('name', '?')}")
            print(f"Mode: {proj.get('mode', '?')}")
            print(f"Goal: {proj.get('goal', '-')}")
            print(f"Status: {proj.get('status', '?')}")
            items = proj.get("stages") or proj.get("tasks") or []
            if items:
                print(f"\nTasks ({len(items)}):")
                for t in items:
                    indicator = (
                        "+"
                        if t.get("status") == "done"
                        else "~"
                        if t.get("status") == "in-progress"
                        else "-"
                    )
                    deps = (
                        f" (deps: {','.join(t.get('dependencies', []))})"
                        if t.get("dependencies")
                        else ""
                    )
                    print(
                        f"  {indicator} {t.get('id', '?'):<15} {t.get('status', '?'):<12} {t.get('agent', '')}{deps}"
                    )
    except AgentMetricsError as e:
        _err(e)


def cmd_project_add_task(args):
    client = AgentMetricsClient()
    try:
        result = client.add_task(
            args.name,
            args.task_id,
            agent=args.agent,
            description=args.desc,
            deps=args.deps,
        )
        if args.json:
            _json_out(result, True)
        else:
            print(f"Added task: {args.task_id}")
    except AgentMetricsError as e:
        _err(e)


def cmd_project_ready(args):
    client = AgentMetricsClient()
    try:
        tasks = client.ready_tasks(args.name)
        if args.json:
            _json_out(tasks, True)
        else:
            if not tasks:
                print("No ready tasks.")
                return
            for t in tasks:
                print(
                    f"  {t.get('id', '?'):<15} {t.get('agent', ''):<15} {t.get('description', '')[:50]}"
                )
    except AgentMetricsError as e:
        _err(e)


def cmd_project_next(args):
    client = AgentMetricsClient()
    try:
        stage = client.next_stage(args.name)
        if args.json:
            _json_out(stage, True)
        else:
            if stage.get("status") == "all_complete":
                print("All stages complete.")
            else:
                print(f"Next: {stage.get('id', '?')} (agent: {stage.get('agent', '?')})")
    except AgentMetricsError as e:
        _err(e)


def cmd_project_update(args):
    client = AgentMetricsClient()
    try:
        result = client.update_task(args.name, args.task_id, args.status)
        if args.json:
            _json_out(result, True)
        else:
            print(f"Updated {args.task_id} → {args.status}")
            if result.get("newly_ready"):
                print(f"Newly ready: {', '.join(result['newly_ready'])}")
    except AgentMetricsError as e:
        _err(e)


def cmd_project_result(args):
    client = AgentMetricsClient()
    try:
        result = client.record_result(args.name, args.task_id, args.text)
        if args.json:
            _json_out(result, True)
        else:
            print(f"Recorded result for {args.task_id}")
    except AgentMetricsError as e:
        _err(e)


def cmd_project_add_debater(args):
    client = AgentMetricsClient()
    try:
        result = client.add_debater(
            args.name,
            args.debater_id,
            agent=args.agent,
            perspective=args.perspective,
        )
        if args.json:
            _json_out(result, True)
        else:
            print(f"Added debater: {args.debater_id}")
    except AgentMetricsError as e:
        _err(e)


def cmd_project_round(args):
    client = AgentMetricsClient()
    try:
        result = client.manage_round(
            args.name,
            args.action,
            debater_id=args.debater,
            text=args.text,
        )
        if args.json:
            _json_out(result, True)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except AgentMetricsError as e:
        _err(e)


def cmd_project_reset(args):
    client = AgentMetricsClient()
    try:
        result = client.reset_project(args.name)
        if args.json:
            _json_out(result, True)
        else:
            print(f"Reset project: {args.name}")
    except AgentMetricsError as e:
        _err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="maestro",
        description="Agent Metrics orchestration CLI — Maestro dispatch + Project management",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # plan
    p_plan = sub.add_parser("plan", help="Analyze task (no execution)")
    p_plan.add_argument("task", help="Task description")
    p_plan.add_argument(
        "--budget", default="balanced", choices=["minimize", "balanced", "maximize_quality"]
    )
    p_plan.add_argument(
        "--pattern", default=None, choices=["solo", "pipeline", "race", "swarm", "escalation"]
    )
    p_plan.set_defaults(func=cmd_plan)

    # run
    p_run = sub.add_parser("run", help="Analyze + execute a dispatch")
    p_run.add_argument("task", help="Task description")
    p_run.add_argument(
        "--budget", default="balanced", choices=["minimize", "balanced", "maximize_quality"]
    )
    p_run.add_argument(
        "--pattern", default=None, choices=["solo", "pipeline", "race", "swarm", "escalation"]
    )
    p_run.add_argument("--cwd", default="", help="Working directory for agents")
    p_run.add_argument("--timeout", type=int, default=300, help="Per-agent timeout")
    p_run.set_defaults(func=cmd_run)

    # runs
    p_runs = sub.add_parser("runs", help="List dispatch history")
    p_runs.add_argument("--limit", type=int, default=50)
    p_runs.set_defaults(func=cmd_runs)

    # run-detail
    p_detail = sub.add_parser("run-detail", help="Get dispatch run details")
    p_detail.add_argument("name", help="Run name")
    p_detail.set_defaults(func=cmd_run_detail)

    # routing
    p_routing = sub.add_parser("routing", help="Show CLI routing table")
    p_routing.set_defaults(func=cmd_routing)

    # project (subgroup)
    p_project = sub.add_parser("project", help="Project management (team-tasks)")
    psub = p_project.add_subparsers(dest="project_cmd", required=True)

    # project list
    pp_list = psub.add_parser("list", help="List all projects")
    pp_list.set_defaults(func=cmd_project_list)

    # project create
    pp_create = psub.add_parser("create", help="Create a project")
    pp_create.add_argument("name", help="Project name")
    pp_create.add_argument("--mode", default="dag", choices=["linear", "dag", "debate"])
    pp_create.add_argument("--goal", "-g", default="", help="Project goal")
    pp_create.add_argument(
        "--pipeline", "-p", default="", help="Pipeline stages (linear mode, comma-separated)"
    )
    pp_create.add_argument("--workspace", "-w", default="", help="Workspace path")
    pp_create.set_defaults(func=cmd_project_create)

    # project status
    pp_status = psub.add_parser("status", help="Get project status")
    pp_status.add_argument("name", help="Project name")
    pp_status.set_defaults(func=cmd_project_status)

    # project add-task
    pp_add = psub.add_parser("add-task", help="Add task to project (DAG mode)")
    pp_add.add_argument("name", help="Project name")
    pp_add.add_argument("task_id", help="Task ID")
    pp_add.add_argument("--agent", "-a", default="", help="Agent name")
    pp_add.add_argument("--desc", "-d", default="", help="Task description")
    pp_add.add_argument("--deps", default="", help="Dependencies (comma-separated)")
    pp_add.set_defaults(func=cmd_project_add_task)

    # project ready
    pp_ready = psub.add_parser("ready", help="List ready tasks (DAG mode)")
    pp_ready.add_argument("name", help="Project name")
    pp_ready.set_defaults(func=cmd_project_ready)

    # project next
    pp_next = psub.add_parser("next", help="Get next stage (linear mode)")
    pp_next.add_argument("name", help="Project name")
    pp_next.set_defaults(func=cmd_project_next)

    # project update
    pp_update = psub.add_parser("update", help="Update task status")
    pp_update.add_argument("name", help="Project name")
    pp_update.add_argument("task_id", help="Task ID")
    pp_update.add_argument(
        "status", choices=["pending", "in-progress", "done", "failed", "skipped"]
    )
    pp_update.set_defaults(func=cmd_project_update)

    # project result
    pp_result = psub.add_parser("result", help="Record task result")
    pp_result.add_argument("name", help="Project name")
    pp_result.add_argument("task_id", help="Task ID")
    pp_result.add_argument("text", help="Result text")
    pp_result.set_defaults(func=cmd_project_result)

    # project add-debater
    pp_debater = psub.add_parser("add-debater", help="Add debater (debate mode)")
    pp_debater.add_argument("name", help="Project name")
    pp_debater.add_argument("debater_id", help="Debater ID")
    pp_debater.add_argument("--agent", "-a", default="", help="Agent name")
    pp_debater.add_argument("--perspective", default="", help="Perspective description")
    pp_debater.set_defaults(func=cmd_project_add_debater)

    # project round
    pp_round = psub.add_parser("round", help="Manage debate round")
    pp_round.add_argument("name", help="Project name")
    pp_round.add_argument(
        "action", choices=["start", "submit", "cross-review", "synthesize", "status"]
    )
    pp_round.add_argument("--debater", "-d", default="", help="Debater ID (for submit)")
    pp_round.add_argument("--text", "-t", default="", help="Content text (for submit)")
    pp_round.set_defaults(func=cmd_project_round)

    # project reset
    pp_reset = psub.add_parser("reset", help="Reset project state")
    pp_reset.add_argument("name", help="Project name")
    pp_reset.set_defaults(func=cmd_project_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
