#!/usr/bin/env python3
"""agent-metrics MCP Server — Thin wrapper over AgentMetricsClient SDK.

10 tools: maestro_plan, maestro_run, maestro_runs,
          project_list, project_create, project_status,
          project_add_task, project_ready, project_update_task, project_round.

All logic lives in workshop.clients.agent_metrics (SDK layer).

Usage:
    python3 mcp/agent-metrics/server.py

Configure in ~/.claude.json:
    "agent-metrics": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/agent-metrics/server.py"],
        "env": {}
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.agent_metrics import AgentMetricsClient
from workshop.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("agent-metrics")
client = AgentMetricsClient(dispatch_timeout=600)


# ======================== Result Formatting ========================


def _format_plan(data: dict) -> str:
    parts = [
        f"**Pattern**: {data.get('recommended_pattern', '?')}",
        f"**Complexity**: {data.get('complexity', '?')}",
        f"**Categories**: {', '.join(data.get('categories', []))}",
    ]
    if data.get("explicit_clis"):
        parts.append(f"**Explicit CLIs**: {', '.join(data['explicit_clis'])}")
    if data.get("phases"):
        phases_text = "\n".join(
            f"  {i}. [{p.get('cli', '?')}] {p.get('role', '?')}"
            for i, p in enumerate(data["phases"], 1)
        )
        parts.append(f"\n**Phases**:\n{phases_text}")
    return "\n".join(parts)


def _format_report(data: dict) -> str:
    parts = [
        f"**Name**: {data.get('name', '?')}",
        f"**Pattern**: {data.get('pattern', '?')}",
        f"**Duration**: {data.get('duration_s', '?')}s",
        f"**Agents**: {data.get('agents_completed', 0)}/{data.get('agents_total', 0)}",
    ]
    for r in data.get("results", []):
        output = r.get("output", "")[:3000]
        parts.append(
            f"\n### [{r.get('cli', '?')}] {r.get('status', '?')} ({r.get('duration_s', '?')}s)\n{output}"
        )
    return "\n".join(parts)


def _format_runs(runs: list[dict]) -> str:
    if not runs:
        return "No dispatch runs found."
    lines = ["| Name | Pattern | Status | Duration |", "|------|---------|--------|----------|"]
    for r in runs:
        duration = f"{r.get('duration_s', 0):.1f}s" if r.get("duration_s") else "-"
        lines.append(
            f"| {r.get('name', '?')} | {r.get('pattern', '?')} | {r.get('status', '?')} | {duration} |"
        )
    return "\n".join(lines)


def _format_projects(projects: list[dict]) -> str:
    if not projects:
        return "No projects found."
    lines = ["| Name | Mode | Status | Goal |", "|------|------|--------|------|"]
    for p in projects:
        lines.append(
            f"| {p.get('name', '?')} | {p.get('mode', '?')} | {p.get('status', '?')} | {p.get('goal', '')[:40]} |"
        )
    return "\n".join(lines)


def _format_project(proj: dict) -> str:
    parts = [
        f"**Project**: {proj.get('name', '?')}",
        f"**Mode**: {proj.get('mode', '?')}",
        f"**Goal**: {proj.get('goal', '-')}",
        f"**Status**: {proj.get('status', '?')}",
    ]
    items = proj.get("stages") or proj.get("tasks") or []
    if items:
        parts.append(f"\n**Tasks** ({len(items)}):")
        for t in items:
            icon = (
                "✅"
                if t.get("status") == "done"
                else "🔄"
                if t.get("status") == "in-progress"
                else "⏳"
            )
            deps = (
                f" (deps: {','.join(t.get('dependencies', []))})" if t.get("dependencies") else ""
            )
            parts.append(
                f"- {icon} **{t.get('id', '?')}** — {t.get('status', '?')} ({t.get('agent', '')}){deps}"
            )
    return "\n".join(parts)


def _format_ready(tasks: list[dict]) -> str:
    if not tasks:
        return "No ready tasks."
    lines = [f"**Ready tasks** ({len(tasks)}):"]
    for t in tasks:
        lines.append(
            f"- **{t.get('id', '?')}** — {t.get('agent', '')} — {t.get('description', '')[:60]}"
        )
    return "\n".join(lines)


# ======================== Tool Handlers ========================


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def maestro_plan(
    task: str,
    budget: str = "balanced",
    pattern: str = "",
) -> str:
    """Analyze a task and return recommended orchestration pattern, complexity, categories, and phases. No execution."""
    result = await to_thread(
        client.plan,
        task=task,
        budget=budget,
        pattern=pattern or None,
    )
    return _format_plan(result)


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def maestro_run(
    task: str,
    budget: str = "balanced",
    pattern: str = "",
    cwd: str = "",
    timeout: int = 300,
) -> str:
    """Execute a dispatch: analyze task → route to CLI(s) → run agents → return report. Long-running — may take minutes. Use from background agent for true async."""
    result = await to_thread(
        client.run,
        task=task,
        budget=budget,
        pattern=pattern or None,
        cwd=cwd,
        timeout=timeout,
    )
    return _format_report(result)


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def maestro_runs(limit: int = 20) -> str:
    """List recent dispatch run history with name, pattern, status, duration."""
    runs = await to_thread(client.list_runs, limit=limit)
    return _format_runs(runs)


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def project_list(limit: int = 20) -> str:
    """List team-task projects with name, mode, status, goal."""
    projects = await to_thread(client.list_projects)
    total_count = len(projects)
    projects = projects[:limit]
    header = f"Showing {len(projects)} of {total_count} projects\n\n"
    return header + _format_projects(projects)


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def project_create(
    name: str,
    mode: str = "dag",
    goal: str = "",
    pipeline: str = "",
    workspace: str = "",
) -> str:
    """Create a new team-task project. Modes: linear (sequential pipeline), dag (dependency graph), debate (multi-perspective review)."""
    await to_thread(
        client.create_project,
        name=name,
        mode=mode,
        goal=goal,
        pipeline=pipeline,
        workspace=workspace,
    )
    return f"✅ Created project **{name}** ({mode})"


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def project_status(name: str) -> str:
    """Get full project state including all tasks/stages and their statuses."""
    proj = await to_thread(client.get_project, name=name)
    return _format_project(proj)


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def project_add_task(
    project: str,
    task_id: str,
    agent: str = "",
    description: str = "",
    deps: str = "",
) -> str:
    """Add a task to a DAG project with optional dependencies and agent assignment."""
    await to_thread(
        client.add_task,
        project=project,
        task_id=task_id,
        agent=agent,
        description=description,
        deps=deps,
    )
    return f"✅ Added task **{task_id}** to {project}"


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def project_ready(project: str) -> str:
    """Get ready-to-dispatch tasks: all dependencies resolved, status pending. DAG mode only."""
    tasks = await to_thread(client.ready_tasks, project=project)
    return _format_ready(tasks)


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def project_update_task(
    project: str,
    task_id: str,
    status: str,
) -> str:
    """Update task status (pending → in-progress → done/failed/skipped)."""
    result = await to_thread(
        client.update_task,
        project=project,
        task_id=task_id,
        status=status,
    )
    msg = f"✅ Updated **{task_id}** → {status}"
    if result.get("newly_ready"):
        msg += f"\n\nNewly ready: {', '.join(result['newly_ready'])}"
    return msg


@mcp.tool()
@mcp_error_handler("AgentMetrics")
async def project_round(
    project: str,
    action: str,
    debater_id: str = "",
    text: str = "",
) -> str:
    """Manage debate rounds: start, submit response, cross-review, synthesize, or check status. Debate mode only."""
    result = await to_thread(
        client.manage_round,
        project=project,
        action=action,
        debater_id=debater_id,
        text=text,
    )
    return json_text(result)


if __name__ == "__main__":
    mcp.run()
