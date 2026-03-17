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

from asyncio import to_thread
from typing import Optional

from mcp.server.fastmcp import FastMCP
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.dailyos import DailyOSClient

mcp = FastMCP("dailyos")
client = DailyOSClient()


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


@mcp.tool()
async def dailyos_methods(
    include_presets: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List DailyOS methods (productivity frameworks). Optionally include preset methods."""
    try:
        result = await to_thread(
            client.list_methods,
            include_presets=include_presets,
            page=page,
            page_size=page_size,
        )
        return _format_methods(result)
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def dailyos_active(context: str = "default") -> str:
    """Get active method selections for a context (which productivity methods are currently active)."""
    try:
        result = await to_thread(
            client.get_active_methods,
            context=context,
        )
        items = result if isinstance(result, list) else result.get("items", [])
        if not items:
            return "No active methods for this context."
        lines = [f"**Active Methods** ({len(items)})\n"]
        for sel in items:
            m = sel.get("method", sel)
            icon = m.get("icon", "")
            name_val = m.get("name", "?")
            label = f"{icon} {name_val}" if icon else name_val
            lines.append(f"- **{label}** (selection_id: {sel.get('id', '?')[:12]})")
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def dailyos_activate(
    method_id: str,
    context: str = "default",
    overrides: Optional[dict] = None,
) -> str:
    """Activate a method for a context. Adds it to the active method selections."""
    try:
        result = await to_thread(
            client.activate_method,
            method_id=method_id,
            context=context,
            overrides=overrides,
        )
        method = result.get("method", {})
        method_name = method.get("name", result.get("method_id", "?"))
        return f"Method activated: **{method_name}** (selection_id: {result.get('id', '?')[:12]})"
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def dailyos_guide(context: str = "default") -> str:
    """Get composite guide text for all active methods in a context. Returns combined daily practice instructions."""
    try:
        result = await to_thread(
            client.get_guide,
            context=context,
        )
        guide_text = result.get("guide", "")
        method_count = result.get("method_count", 0)
        method_names = result.get("method_names", [])
        header = f"**Composite Guide** ({method_count} methods: {', '.join(method_names)})\n\n"
        return header + (guide_text or "(no guide content)")
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def dailyos_plans(
    page: int = 1,
    page_size: int = 20,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    """List daily plans with optional date range filter."""
    try:
        result = await to_thread(
            client.list_plans,
            page=page,
            page_size=page_size,
            date_from=date_from,
            date_to=date_to,
        )
        items = result.get("items", [])
        total = result.get("total", 0)
        if not items:
            return "No plans found."
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
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def dailyos_today(context: str = "default") -> str:
    """Get or create today's daily plan. Returns current plan items, status, and completion score."""
    try:
        result = await to_thread(
            client.get_today,
            context=context,
        )
        return _format_plan(result)
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def dailyos_update_plan(
    plan_id: str,
    items: Optional[list] = None,
    reflection: Optional[str] = None,
    completion_score: Optional[float] = None,
) -> str:
    """Update a daily plan's items, reflection, or completion score."""
    try:
        data: dict = {}
        if items is not None:
            data["items"] = items
        if reflection is not None:
            data["reflection"] = reflection
        if completion_score is not None:
            data["completion_score"] = completion_score
        result = await to_thread(
            client.update_plan,
            plan_id=plan_id,
            data=data,
        )
        return _format_plan(result)
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def dailyos_transition(
    plan_id: str,
    status: str,
    comment: Optional[str] = None,
) -> str:
    """Transition a daily plan to a new status (active, completed, skipped)."""
    try:
        result = await to_thread(
            client.transition_plan,
            plan_id=plan_id,
            status=status,
            comment=comment,
        )
        plan_date = str(result.get("plan_date", result.get("created_at", "")))[:10]
        new_status = result.get("status", status)
        return f"Plan [{plan_date}] transitioned to **{new_status}** (id: {result.get('id', '?')[:12]})"
    except (APIError, APIConnectionError) as e:
        return f"DailyOS error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
