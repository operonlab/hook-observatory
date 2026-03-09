#!/usr/bin/env python3
"""DailyOS MCP Server — thin wrapper over DailyOSClient SDK.

8 tools: dailyos_methods, dailyos_active, dailyos_activate, dailyos_guide,
         dailyos_plans, dailyos_today, dailyos_update_plan, dailyos_transition.

Usage:
    python3 mcp/dailyos/server.py

Configure in ~/.claude.json:
    "dailyos": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/dailyos/server.py"],
        "env": {}
    }
"""

import asyncio
import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.dailyos import DailyOSClient

server = Server("dailyos")
client = DailyOSClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="dailyos_methods",
            description="List DailyOS methods (productivity frameworks). Optionally include preset methods.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_presets": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include built-in preset methods",
                    },
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="dailyos_active",
            description="Get active method selections for a context (which productivity methods are currently active).",
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "default": "default",
                        "description": "Context key (e.g. 'default', 'work', 'personal')",
                    },
                },
            },
        ),
        Tool(
            name="dailyos_activate",
            description="Activate a method for a context. Adds it to the active method selections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "method_id": {"type": "string", "description": "Method UUID to activate"},
                    "context": {
                        "type": "string",
                        "default": "default",
                        "description": "Context key",
                    },
                    "overrides": {
                        "type": "object",
                        "description": "Optional config overrides for this selection",
                    },
                },
                "required": ["method_id"],
            },
        ),
        Tool(
            name="dailyos_guide",
            description="Get composite guide text for all active methods in a context. Returns combined daily practice instructions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "default": "default",
                        "description": "Context key",
                    },
                },
            },
        ),
        Tool(
            name="dailyos_plans",
            description="List daily plans with optional date range filter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                    "date_from": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM-DD"},
                },
            },
        ),
        Tool(
            name="dailyos_today",
            description="Get or create today's daily plan. Returns current plan items, status, and completion score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "default": "default",
                        "description": "Context key for method selection",
                    },
                },
            },
        ),
        Tool(
            name="dailyos_update_plan",
            description="Update a daily plan's items, reflection, or completion score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "Plan UUID"},
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Updated plan item list",
                    },
                    "reflection": {
                        "type": "string",
                        "description": "End-of-day reflection text",
                    },
                    "completion_score": {
                        "type": "number",
                        "description": "Completion score 0-100",
                    },
                },
                "required": ["plan_id"],
            },
        ),
        Tool(
            name="dailyos_transition",
            description="Transition a daily plan to a new status (active, completed, skipped).",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "Plan UUID"},
                    "status": {
                        "type": "string",
                        "description": "Target status: active | completed | skipped",
                    },
                    "comment": {
                        "type": "string",
                        "description": "Optional transition comment",
                    },
                },
                "required": ["plan_id", "status"],
            },
        ),
    ]


def _format_methods(result: dict) -> str:
    items = result.get("items", [])
    total = result.get("total", 0)
    if not items:
        return "No methods found."
    lines = [f"**Methods** ({len(items)} of {total})\n"]
    for m in items:
        icon = m.get("icon", "")
        name = m.get("name", "?")
        name_zh = m.get("name_zh", "")
        is_preset = m.get("is_preset", False)
        preset_tag = " [preset]" if is_preset else ""
        label = f"{icon} {name}" if icon else name
        zh_part = f" / {name_zh}" if name_zh else ""
        lines.append(f"- **{label}**{zh_part}{preset_tag} (id: {m.get('id', '?')[:12]})")
    return "\n".join(lines)


def _format_plan(plan: dict) -> str:
    if not plan:
        return "No plan found."
    plan_date = str(plan.get("plan_date", plan.get("created_at", "")))[:10]
    status = plan.get("status", "?")
    score = plan.get("completion_score")
    score_str = f" | score: {score:.0f}%" if score is not None else ""
    lines = [f"**Plan** [{plan_date}] status: {status}{score_str}\n"]
    items = plan.get("items", [])
    if items:
        for item in items:
            title = item.get("title", item.get("name", "?"))
            priority = item.get("priority", "")
            item_status = item.get("status", "")
            meta = " | ".join(filter(None, [priority, item_status]))
            meta_str = f" ({meta})" if meta else ""
            lines.append(f"  - {title}{meta_str}")
    else:
        lines.append("  (no items)")
    reflection = plan.get("reflection")
    if reflection:
        lines.append(f"\nReflection: {reflection[:200]}")
    return "\n".join(lines)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "dailyos_methods":
                result = await to_thread(
                    client.list_methods,
                    include_presets=arguments.get("include_presets", True),
                    page=arguments.get("page", 1),
                    page_size=arguments.get("page_size", 20),
                )
                return text_result(_format_methods(result))

            case "dailyos_active":
                result = await to_thread(
                    client.get_active_methods,
                    context=arguments.get("context", "default"),
                )
                items = result if isinstance(result, list) else result.get("items", [])
                if not items:
                    return text_result("No active methods for this context.")
                lines = [f"**Active Methods** ({len(items)})\n"]
                for sel in items:
                    m = sel.get("method", sel)
                    icon = m.get("icon", "")
                    name_val = m.get("name", "?")
                    label = f"{icon} {name_val}" if icon else name_val
                    lines.append(f"- **{label}** (selection_id: {sel.get('id', '?')[:12]})")
                return text_result("\n".join(lines))

            case "dailyos_activate":
                result = await to_thread(
                    client.activate_method,
                    method_id=arguments["method_id"],
                    context=arguments.get("context", "default"),
                    overrides=arguments.get("overrides"),
                )
                method = result.get("method", {})
                method_name = method.get("name", result.get("method_id", "?"))
                return text_result(
                    f"Method activated: **{method_name}** (selection_id: {result.get('id', '?')[:12]})"
                )

            case "dailyos_guide":
                result = await to_thread(
                    client.get_guide,
                    context=arguments.get("context", "default"),
                )
                guide_text = result.get("guide", "")
                method_count = result.get("method_count", 0)
                method_names = result.get("method_names", [])
                header = (
                    f"**Composite Guide** ({method_count} methods: {', '.join(method_names)})\n\n"
                )
                return text_result(header + (guide_text or "(no guide content)"))

            case "dailyos_plans":
                result = await to_thread(
                    client.list_plans,
                    page=arguments.get("page", 1),
                    page_size=arguments.get("page_size", 20),
                    date_from=arguments.get("date_from"),
                    date_to=arguments.get("date_to"),
                )
                items = result.get("items", [])
                total = result.get("total", 0)
                if not items:
                    return text_result("No plans found.")
                lines = [f"**Plans** ({len(items)} of {total})\n"]
                for p in items:
                    plan_date = str(p.get("plan_date", p.get("created_at", "")))[:10]
                    status = p.get("status", "?")
                    score = p.get("completion_score")
                    score_str = f" {score:.0f}%" if score is not None else ""
                    item_count = len(p.get("items", []))
                    lines.append(
                        f"- [{plan_date}] **{status}**{score_str} — {item_count} items (id: {p.get('id', '?')[:12]})"
                    )
                return text_result("\n".join(lines))

            case "dailyos_today":
                result = await to_thread(
                    client.get_today,
                    context=arguments.get("context", "default"),
                )
                return text_result(_format_plan(result))

            case "dailyos_update_plan":
                data: dict = {}
                if "items" in arguments:
                    data["items"] = arguments["items"]
                if "reflection" in arguments:
                    data["reflection"] = arguments["reflection"]
                if "completion_score" in arguments:
                    data["completion_score"] = arguments["completion_score"]
                result = await to_thread(
                    client.update_plan,
                    plan_id=arguments["plan_id"],
                    data=data,
                )
                return text_result(_format_plan(result))

            case "dailyos_transition":
                result = await to_thread(
                    client.transition_plan,
                    plan_id=arguments["plan_id"],
                    status=arguments["status"],
                    comment=arguments.get("comment"),
                )
                plan_date = str(result.get("plan_date", result.get("created_at", "")))[:10]
                new_status = result.get("status", arguments["status"])
                return text_result(
                    f"Plan [{plan_date}] transitioned to **{new_status}** (id: {result.get('id', '?')[:12]})"
                )

            case _:
                return text_result(f"Unknown tool: {name}")

    except (APIError, APIConnectionError) as e:
        return text_result(f"DailyOS error: {e}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
