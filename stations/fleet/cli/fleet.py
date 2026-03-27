#!/usr/bin/env python3
"""Fleet CLI — multi-machine task dispatch.

Usage:
    fleet health                          Show fleet + node health
    fleet nodes                           List nodes and capabilities
    fleet dispatch "cmd" [--node N]       Dispatch a task
    fleet status ID                       Check task status
    fleet result ID [--lines N]           Get task output
    fleet tasks [--status S] [--node N]   List tasks
    fleet cancel ID                       Cancel a task
    fleet watch [NODE] [--session S]      SSH attach to remote tmux

Symlink: ln -sf ~/workshop/stations/fleet/cli/fleet.py ~/.local/bin/fleet
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from workshop.clients.fleet import FleetClient, FleetError


def _client() -> FleetClient:
    return FleetClient()


def _ts(epoch: float | None) -> str:
    if not epoch:
        return "-"
    return datetime.fromtimestamp(epoch).strftime("%H:%M:%S")


def _status_color(status: str) -> str:
    colors = {
        "running": "\033[33m",  # yellow
        "completed": "\033[32m",  # green
        "failed": "\033[31m",  # red
        "timeout": "\033[31m",  # red
        "cancelled": "\033[90m",  # gray
        "pending": "\033[36m",  # cyan
        "preparing": "\033[36m",  # cyan
    }
    reset = "\033[0m"
    return f"{colors.get(status, '')}{status}{reset}"


# ======================== Command Handlers ========================


def cmd_health(args):
    """Show fleet + all node health."""
    data = _client().health()
    print(f"Fleet: {data.get('status', 'unknown')}")
    for name, healthy in data.get("nodes", {}).items():
        icon = "✅" if healthy else "❌"
        print(f"  {icon} {name}")


def cmd_nodes(args):
    """List nodes with capabilities and active task count."""
    nodes = _client().list_nodes()
    if not nodes:
        print("No nodes registered.")
        return
    for n in nodes:
        icon = "✅" if n.get("healthy") else "❌"
        caps = ", ".join(n.get("capabilities", []))
        gpu_info = f" | GPU: {n['gpu']['model']}" if n.get("gpu") else ""
        tasks = n.get("active_tasks", 0)
        platform = n.get("platform", "?")
        print(f"{icon} {n['name']} ({platform}) [{caps}{gpu_info}] tasks={tasks}")


def cmd_dispatch(args):
    """Dispatch a task to Fleet."""
    result = _client().dispatch(
        command=args.command,
        mode=args.mode,
        node=args.node,
        timeout=args.timeout,
    )
    print(f"Task:   {result['id'][:8]}")
    print(f"Node:   {result.get('node', '?')}")
    print(f"Mode:   {result.get('mode', '?')}")
    print(f"Status: {_status_color(result.get('status', 'pending'))}")
    if result.get("branch"):
        print(f"Branch: {result['branch']}")


def cmd_status(args):
    """Check task status and metadata."""
    result = _client().task_status(args.task_id)
    print(f"Task:    {result['id'][:8]}")
    print(f"Command: {result.get('command', '')[:60]}")
    print(f"Node:    {result.get('node', '?')}")
    print(f"Mode:    {result.get('mode', '?')}")
    print(f"Status:  {_status_color(result.get('status', '?'))}")
    print(f"Created: {_ts(result.get('created_at'))}")
    print(f"Started: {_ts(result.get('started_at'))}")
    print(f"Done:    {_ts(result.get('completed_at'))}")
    if result.get("branch"):
        print(f"Branch:  {result['branch']}")
    if result.get("error"):
        print(f"Error:   \033[31m{result['error']}\033[0m")


def cmd_result(args):
    """Get task output."""
    result = _client().task_output(args.task_id, lines=args.lines)
    print(f"[{_status_color(result.get('status', '?'))}]")
    output = result.get("output", "")
    if output:
        print(output)
    else:
        print("(no output)")


def cmd_tasks(args):
    """List tasks with optional filters."""
    tasks = _client().list_tasks(status=args.status, node=args.node)
    if not tasks:
        print("No tasks found.")
        return
    for t in tasks:
        sid = t["id"][:8]
        status = _status_color(t.get("status", "?"))
        cmd = t.get("command", "")[:40]
        node = t.get("node", "?")
        ts = _ts(t.get("created_at"))
        print(f"  {sid}  {status:<30s}  {node:<12s}  {ts}  {cmd}")


def cmd_cancel(args):
    """Cancel a task."""
    result = _client().cancel_task(args.task_id)
    print(f"Task {result['id'][:8]}: {_status_color(result.get('status', 'cancelled'))}")


def cmd_watch(args):
    """Direct SSH attach to remote tmux — bypasses Fleet API."""
    node = args.node or "win-gpu"
    session = args.session or "fleet-*"
    # Replace the current process with SSH (no subprocess overhead)
    os.execvp(
        "ssh",
        [
            "ssh",
            "-t",
            node,
            "wsl",
            "-d",
            "Ubuntu",
            "--",
            "bash",
            "-c",
            f"tmux attach -t {session} -r 2>/dev/null || tmux attach",
        ],
    )


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="fleet",
        description="Fleet — multi-machine task dispatch",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # health
    sub.add_parser("health", help="Show fleet + node health")

    # nodes
    sub.add_parser("nodes", help="List nodes and capabilities")

    # dispatch
    p_dispatch = sub.add_parser("dispatch", help="Dispatch a task")
    p_dispatch.add_argument("command", help="Task command or prompt")
    p_dispatch.add_argument("--node", "-n", help="Target node name")
    p_dispatch.add_argument(
        "--mode",
        "-m",
        default="code",
        choices=["code", "gpu"],
        help="Execution mode (default: code)",
    )
    p_dispatch.add_argument(
        "--timeout", "-t", type=int, default=600, help="Task timeout in seconds (default: 600)"
    )

    # status
    p_status = sub.add_parser("status", help="Check task status")
    p_status.add_argument("task_id", help="Task ID (short prefix or full UUID)")

    # result
    p_result = sub.add_parser("result", help="Get task output")
    p_result.add_argument("task_id", help="Task ID")
    p_result.add_argument(
        "--lines", "-l", type=int, default=200, help="Max output lines (default: 200)"
    )

    # tasks
    p_tasks = sub.add_parser("tasks", help="List tasks")
    p_tasks.add_argument("--status", "-s", help="Filter by status")
    p_tasks.add_argument("--node", "-n", help="Filter by node")

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel a task")
    p_cancel.add_argument("task_id", help="Task ID")

    # watch
    p_watch = sub.add_parser("watch", help="SSH attach to remote tmux (bypasses API)")
    p_watch.add_argument(
        "node", nargs="?", default="win-gpu", help="Target node SSH hostname (default: win-gpu)"
    )
    p_watch.add_argument("--session", "-s", help="tmux session name or pattern")

    args = parser.parse_args()
    cmd_map = {
        "health": cmd_health,
        "nodes": cmd_nodes,
        "dispatch": cmd_dispatch,
        "status": cmd_status,
        "result": cmd_result,
        "tasks": cmd_tasks,
        "cancel": cmd_cancel,
        "watch": cmd_watch,
    }
    try:
        cmd_map[args.cmd](args)
    except FleetError as e:
        print(f"\033[31mFleet error {e.status_code}:\033[0m {e.detail}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\033[31mError:\033[0m {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
