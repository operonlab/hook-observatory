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

import asyncio
import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.agent_metrics import AgentMetricsClient, AgentMetricsError

server = Server("agent-metrics")
client = AgentMetricsClient(dispatch_timeout=600)


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # Maestro Dispatch
        Tool(
            name="maestro_plan",
            description=(
                "Analyze a task and return recommended orchestration pattern, "
                "complexity, categories, and phases. No execution."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task description to analyze"},
                    "budget": {
                        "type": "string",
                        "enum": ["minimize", "balanced", "maximize_quality"],
                        "default": "balanced",
                    },
                    "pattern": {
                        "type": "string",
                        "enum": ["solo", "pipeline", "race", "swarm", "escalation"],
                        "description": "Force a specific pattern (optional)",
                    },
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="maestro_run",
            description=(
                "Execute a dispatch: analyze task → route to CLI(s) → run agents → return report. "
                "Long-running — may take minutes. Use from background agent for true async."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task description"},
                    "budget": {
                        "type": "string",
                        "enum": ["minimize", "balanced", "maximize_quality"],
                        "default": "balanced",
                    },
                    "pattern": {
                        "type": "string",
                        "enum": ["solo", "pipeline", "race", "swarm", "escalation"],
                    },
                    "cwd": {"type": "string", "default": "", "description": "Working directory"},
                    "timeout": {
                        "type": "integer",
                        "default": 300,
                        "description": "Per-agent timeout",
                    },
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="maestro_runs",
            description="List recent dispatch run history with name, pattern, status, duration.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        # Project Management
        Tool(
            name="project_list",
            description="List team-task projects with name, mode, status, goal.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Max number of projects to return",
                    },
                },
            },
        ),
        Tool(
            name="project_create",
            description=(
                "Create a new team-task project. Modes: linear (sequential pipeline), "
                "dag (dependency graph), debate (multi-perspective review)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "mode": {
                        "type": "string",
                        "enum": ["linear", "dag", "debate"],
                        "default": "dag",
                    },
                    "goal": {"type": "string", "default": ""},
                    "pipeline": {
                        "type": "string",
                        "default": "",
                        "description": "Comma-separated stages (linear mode only)",
                    },
                    "workspace": {"type": "string", "default": ""},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="project_status",
            description="Get full project state including all tasks/stages and their statuses.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="project_add_task",
            description="Add a task to a DAG project with optional dependencies and agent assignment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project name"},
                    "task_id": {"type": "string", "description": "Task identifier"},
                    "agent": {"type": "string", "default": ""},
                    "description": {"type": "string", "default": ""},
                    "deps": {
                        "type": "string",
                        "default": "",
                        "description": "Comma-separated dependency task IDs",
                    },
                },
                "required": ["project", "task_id"],
            },
        ),
        Tool(
            name="project_ready",
            description=(
                "Get ready-to-dispatch tasks: all dependencies resolved, status pending. "
                "DAG mode only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project name"},
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="project_update_task",
            description="Update task status (pending → in-progress → done/failed/skipped).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project name"},
                    "task_id": {"type": "string", "description": "Task ID"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in-progress", "done", "failed", "skipped"],
                    },
                },
                "required": ["project", "task_id", "status"],
            },
        ),
        Tool(
            name="project_round",
            description=(
                "Manage debate rounds: start, submit response, cross-review, synthesize, "
                "or check status. Debate mode only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project name"},
                    "action": {
                        "type": "string",
                        "enum": ["start", "submit", "cross-review", "synthesize", "status"],
                    },
                    "debater_id": {"type": "string", "default": ""},
                    "text": {"type": "string", "default": ""},
                },
                "required": ["project", "action"],
            },
        ),
    ]


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


# ======================== Tool Handler ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "maestro_plan":
            result = await to_thread(
                client.plan,
                task=arguments["task"],
                budget=arguments.get("budget", "balanced"),
                pattern=arguments.get("pattern"),
            )
            return text_result(_format_plan(result))

        elif name == "maestro_run":
            result = await to_thread(
                client.run,
                task=arguments["task"],
                budget=arguments.get("budget", "balanced"),
                pattern=arguments.get("pattern"),
                cwd=arguments.get("cwd", ""),
                timeout=arguments.get("timeout", 300),
            )
            return text_result(_format_report(result))

        elif name == "maestro_runs":
            runs = await to_thread(client.list_runs, limit=arguments.get("limit", 20))
            return text_result(_format_runs(runs))

        elif name == "project_list":
            limit = arguments.get("limit", 20)
            projects = await to_thread(client.list_projects)
            total_count = len(projects)
            projects = projects[:limit]
            header = f"Showing {len(projects)} of {total_count} projects\n\n"
            return text_result(header + _format_projects(projects))

        elif name == "project_create":
            result = await to_thread(
                client.create_project,
                name=arguments["name"],
                mode=arguments.get("mode", "dag"),
                goal=arguments.get("goal", ""),
                pipeline=arguments.get("pipeline", ""),
                workspace=arguments.get("workspace", ""),
            )
            return text_result(
                f"✅ Created project **{arguments['name']}** ({arguments.get('mode', 'dag')})"
            )

        elif name == "project_status":
            proj = await to_thread(client.get_project, name=arguments["name"])
            return text_result(_format_project(proj))

        elif name == "project_add_task":
            result = await to_thread(
                client.add_task,
                project=arguments["project"],
                task_id=arguments["task_id"],
                agent=arguments.get("agent", ""),
                description=arguments.get("description", ""),
                deps=arguments.get("deps", ""),
            )
            return text_result(
                f"✅ Added task **{arguments['task_id']}** to {arguments['project']}"
            )

        elif name == "project_ready":
            tasks = await to_thread(client.ready_tasks, project=arguments["project"])
            return text_result(_format_ready(tasks))

        elif name == "project_update_task":
            result = await to_thread(
                client.update_task,
                project=arguments["project"],
                task_id=arguments["task_id"],
                status=arguments["status"],
            )
            msg = f"✅ Updated **{arguments['task_id']}** → {arguments['status']}"
            if result.get("newly_ready"):
                msg += f"\n\nNewly ready: {', '.join(result['newly_ready'])}"
            return text_result(msg)

        elif name == "project_round":
            result = await to_thread(
                client.manage_round,
                project=arguments["project"],
                action=arguments["action"],
                debater_id=arguments.get("debater_id", ""),
                text=arguments.get("text", ""),
            )
            return text_result(json.dumps(result, indent=2, ensure_ascii=False))

        return text_result(f"Unknown tool: {name}")

    except AgentMetricsError as e:
        return text_result(f"agent-metrics error: {e}")
    except Exception as e:
        return text_result(f"Unexpected error: {type(e).__name__}: {e}")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
