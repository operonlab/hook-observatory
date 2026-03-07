#!/usr/bin/env python3
"""Taskflow MCP Server — tasks, transitions, progress thin adapter over Core API.

12 tools: list_tasks, get_task, create_task, update_task, delete_task,
          transition, add_update, today, upcoming, progress,
          list_subtasks, restore.
Uses workshop.clients.taskflow SDK.

Usage:
    python3 mcp/taskflow/server.py
"""

import asyncio
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.taskflow import TaskflowClient

server = Server("workshop-taskflow")
client = TaskflowClient()


# ======================== Helpers ========================


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


STATUS_EMOJI: dict[str, str] = {
    "todo": "⬜",
    "in_progress": "🔵",
    "review": "🟣",
    "done": "✅",
    "blocked": "🚫",
    "cancelled": "⬛",
}

PRIORITY_EMOJI: dict[str, str] = {
    "urgent": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}


def fmt_task_line(t: dict) -> str:
    """Format a single task as a compact list item."""
    status = t.get("status", "todo")
    priority = t.get("priority", "medium")
    s_emoji = STATUS_EMOJI.get(status, "❓")
    p_emoji = PRIORITY_EMOJI.get(priority, "")
    due = t.get("due_date", "")
    due_str = f"| due {due} " if due else ""
    tid = t.get("id", "")[:8]
    return f"- **{t.get('title', '(無標題)')}** [{s_emoji}] {p_emoji} {due_str}| `{tid}`"


def fmt_task_detail(t: dict) -> str:
    """Format task detail block."""
    status = t.get("status", "todo")
    priority = t.get("priority", "medium")
    lines = [
        f"# {t.get('title', '(無標題)')}",
        "",
        f"- **狀態**: {STATUS_EMOJI.get(status, '')} {status}",
        f"- **優先級**: {PRIORITY_EMOJI.get(priority, '')} {priority}",
        f"- **來源**: {t.get('source', '')}",
        f"- **專案**: {t.get('project') or '—'}",
        f"- **ID**: `{t.get('id', '')}`",
    ]
    if t.get("due_date"):
        lines.append(f"- **到期日**: {t['due_date']}")
    if t.get("start_date"):
        lines.append(f"- **開始日**: {t['start_date']}")
    if t.get("estimated_hours") is not None:
        lines.append(f"- **預估工時**: {t['estimated_hours']}h")
    if t.get("actual_hours") is not None:
        lines.append(f"- **實際工時**: {t['actual_hours']}h")
    if t.get("tags"):
        lines.append(f"- **標籤**: {', '.join(t['tags'])}")
    if t.get("description"):
        lines.append(f"\n## 說明\n\n{t['description']}")
    updates = t.get("updates", [])
    if updates:
        lines.append("\n## 最新進度\n")
        for u in updates[:3]:
            lines.append(f"- [{u.get('type', '')}] {u.get('content', '')}")
    return "\n".join(lines)


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="taskflow_list_tasks",
            description="列出任務（可依狀態/來源/專案/優先級/標籤/關鍵字篩選）",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "todo",
                            "in_progress",
                            "review",
                            "done",
                            "blocked",
                            "cancelled",
                        ],
                        "description": "任務狀態篩選",
                    },
                    "source": {"type": "string", "description": "來源篩選"},
                    "project": {"type": "string", "description": "專案篩選"},
                    "priority": {
                        "type": "string",
                        "enum": ["urgent", "high", "medium", "low"],
                        "description": "優先級篩選",
                    },
                    "tag": {"type": "string", "description": "標籤篩選"},
                    "search": {"type": "string", "description": "關鍵字搜尋"},
                    "top_level": {
                        "type": "boolean",
                        "description": "只顯示頂層任務（無父任務）",
                        "default": False,
                    },
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="taskflow_get_task",
            description="查看任務詳情（含子任務與進度更新）",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任務 ID"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="taskflow_create_task",
            description="新增任務",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "任務標題"},
                    "source": {
                        "type": "string",
                        "description": "任務來源（如 manual / mcp / auto）",
                    },
                    "description": {"type": "string", "description": "任務說明"},
                    "project": {"type": "string", "description": "所屬專案"},
                    "priority": {
                        "type": "string",
                        "enum": ["urgent", "high", "medium", "low"],
                        "default": "medium",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "到期日（YYYY-MM-DD）",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "開始日（YYYY-MM-DD）",
                    },
                    "estimated_hours": {
                        "type": "number",
                        "description": "預估工時（小時）",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "標籤列表",
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "父任務 ID（建立子任務時使用）",
                    },
                },
                "required": ["title", "source"],
            },
        ),
        Tool(
            name="taskflow_update_task",
            description="更新任務欄位",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任務 ID"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "source": {"type": "string"},
                    "project": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["urgent", "high", "medium", "low"],
                    },
                    "due_date": {"type": "string"},
                    "start_date": {"type": "string"},
                    "estimated_hours": {"type": "number"},
                    "actual_hours": {"type": "number"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "parent_id": {"type": "string"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="taskflow_delete_task",
            description="刪除任務（軟刪除，移至垃圾桶）",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任務 ID"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="taskflow_transition",
            description="變更任務狀態（todo/in_progress/review/done/blocked/cancelled）",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任務 ID"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "todo",
                            "in_progress",
                            "review",
                            "done",
                            "blocked",
                            "cancelled",
                        ],
                        "description": "目標狀態",
                    },
                    "comment": {
                        "type": "string",
                        "description": "狀態變更原因或備註",
                    },
                },
                "required": ["task_id", "status"],
            },
        ),
        Tool(
            name="taskflow_add_update",
            description="新增進度更新（progress / blocker / note / status_change）",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任務 ID"},
                    "type": {
                        "type": "string",
                        "enum": ["progress", "blocker", "note", "status_change"],
                        "description": "更新類型",
                    },
                    "content": {"type": "string", "description": "更新內容"},
                    "hours_spent": {
                        "type": "number",
                        "description": "本次花費工時（小時）",
                    },
                },
                "required": ["task_id", "type", "content"],
            },
        ),
        Tool(
            name="taskflow_today",
            description="列出今日任務（今日到期 + 進行中）",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="taskflow_upcoming",
            description="列出即將到期的任務",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 7,
                        "description": "往後幾天（預設 7 天）",
                    },
                },
            },
        ),
        Tool(
            name="taskflow_progress",
            description="查看任務進度統計（狀態/來源/優先級分布、逾期數、工時）",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="taskflow_list_subtasks",
            description="列出指定任務的子任務",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "父任務 ID"},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="taskflow_restore",
            description="從垃圾桶還原已刪除的任務",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任務 ID"},
                },
                "required": ["task_id"],
            },
        ),
    ]


# ======================== Handlers ========================


async def handle_list_tasks(args: dict) -> list[TextContent]:
    result = await to_thread(
        client.list_tasks,
        status=args.get("status"),
        source=args.get("source"),
        project=args.get("project"),
        priority=args.get("priority"),
        tag=args.get("tag"),
        search=args.get("search"),
        top_level=args.get("top_level", False),
        page=args.get("page", 1),
        page_size=args.get("page_size", 20),
    )
    items = result.get("items", [])
    if not items:
        return text_result("目前沒有符合條件的任務。")
    total = result.get("total", 0)
    lines = [f"# 任務列表（共 {total} 筆）\n"]
    for t in items:
        lines.append(fmt_task_line(t))
    return text_result("\n".join(lines))


async def handle_get_task(args: dict) -> list[TextContent]:
    result = await to_thread(client.get_task, args["task_id"])
    return text_result(fmt_task_detail(result))


async def handle_create_task(args: dict) -> list[TextContent]:
    body: dict = {"title": args["title"], "source": args["source"]}
    for f in (
        "description",
        "project",
        "priority",
        "due_date",
        "start_date",
        "estimated_hours",
        "tags",
        "parent_id",
    ):
        if f in args:
            body[f] = args[f]
    result = await to_thread(client.create_task, body)
    priority = result.get("priority", "medium")
    return text_result(
        f"任務已建立\n"
        f"- 標題: {result['title']}\n"
        f"- 優先級: {PRIORITY_EMOJI.get(priority, '')} {priority}\n"
        f"- ID: `{result['id'][:8]}`"
    )


async def handle_update_task(args: dict) -> list[TextContent]:
    task_id = args["task_id"]
    body: dict = {}
    for f in (
        "title",
        "description",
        "source",
        "project",
        "priority",
        "due_date",
        "start_date",
        "estimated_hours",
        "actual_hours",
        "tags",
        "parent_id",
    ):
        if f in args:
            body[f] = args[f]
    result = await to_thread(client.update_task, task_id, body)
    return text_result(
        f"任務已更新\n- 標題: {result.get('title', '')}\n- ID: `{result.get('id', '')[:8]}`"
    )


async def handle_delete_task(args: dict) -> list[TextContent]:
    await to_thread(client.delete_task, args["task_id"])
    return text_result(f"任務 `{args['task_id'][:8]}` 已移至垃圾桶。")


async def handle_transition(args: dict) -> list[TextContent]:
    task_id = args["task_id"]
    status = args["status"]
    comment = args.get("comment")
    result = await to_thread(client.transition_status, task_id, status, comment)
    s_emoji = STATUS_EMOJI.get(status, "")
    return text_result(
        f"狀態已更新\n"
        f"- 任務: {result.get('title', '')}\n"
        f"- 新狀態: {s_emoji} {status}\n"
        f"- ID: `{result.get('id', '')[:8]}`"
    )


async def handle_add_update(args: dict) -> list[TextContent]:
    task_id = args["task_id"]
    body: dict = {"type": args["type"], "content": args["content"]}
    if "hours_spent" in args:
        body["hours_spent"] = args["hours_spent"]
    result = await to_thread(client.add_update, task_id, body)
    return text_result(
        f"進度更新已記錄\n"
        f"- 類型: {result.get('type', '')}\n"
        f"- 內容: {result.get('content', '')[:80]}\n"
        f"- ID: `{result.get('id', '')[:8]}`"
    )


async def handle_today(args: dict) -> list[TextContent]:
    items = await to_thread(client.get_today)
    if not items:
        return text_result("今日沒有待辦任務，幹得漂亮！")
    lines = [f"# 今日任務（共 {len(items)} 筆）\n"]
    for t in items:
        lines.append(fmt_task_line(t))
    return text_result("\n".join(lines))


async def handle_upcoming(args: dict) -> list[TextContent]:
    days = args.get("days", 7)
    items = await to_thread(client.get_upcoming, days)
    if not items:
        return text_result(f"未來 {days} 天內沒有到期任務。")
    lines = [f"# 即將到期任務（{days} 天內，共 {len(items)} 筆）\n"]
    for t in items:
        lines.append(fmt_task_line(t))
    return text_result("\n".join(lines))


async def handle_progress(args: dict) -> list[TextContent]:
    result = await to_thread(client.get_progress)
    lines = ["# 任務進度統計\n"]

    by_status = result.get("by_status", {})
    if by_status:
        lines.append("## 依狀態\n")
        for status, count in by_status.items():
            emoji = STATUS_EMOJI.get(status, "")
            lines.append(f"- {emoji} {status}: {count}")

    by_source = result.get("by_source", {})
    if by_source:
        lines.append("\n## 依來源\n")
        for source, count in by_source.items():
            lines.append(f"- {source}: {count}")

    by_priority = result.get("by_priority", {})
    if by_priority:
        lines.append("\n## 依優先級\n")
        for priority, count in by_priority.items():
            emoji = PRIORITY_EMOJI.get(priority, "")
            lines.append(f"- {emoji} {priority}: {count}")

    overdue = result.get("overdue", 0)
    lines.append(f"\n## 其他\n\n- 逾期任務: {overdue}")

    total_est = result.get("total_estimated_hours")
    total_act = result.get("total_actual_hours")
    if total_est is not None:
        lines.append(f"- 預估總工時: {total_est}h")
    if total_act is not None:
        lines.append(f"- 實際總工時: {total_act}h")

    return text_result("\n".join(lines))


async def handle_list_subtasks(args: dict) -> list[TextContent]:
    result = await to_thread(
        client.list_subtasks,
        args["task_id"],
        page=args.get("page", 1),
        page_size=args.get("page_size", 20),
    )
    items = result.get("items", [])
    if not items:
        return text_result("此任務目前沒有子任務。")
    total = result.get("total", 0)
    lines = [f"# 子任務（共 {total} 筆）\n"]
    for t in items:
        lines.append(fmt_task_line(t))
    return text_result("\n".join(lines))


async def handle_restore(args: dict) -> list[TextContent]:
    result = await to_thread(client.restore_task, args["task_id"])
    return text_result(
        f"任務已還原\n- 標題: {result.get('title', '')}\n- ID: `{result.get('id', '')[:8]}`"
    )


# ======================== Dispatcher ========================

HANDLERS = {
    "taskflow_list_tasks": handle_list_tasks,
    "taskflow_get_task": handle_get_task,
    "taskflow_create_task": handle_create_task,
    "taskflow_update_task": handle_update_task,
    "taskflow_delete_task": handle_delete_task,
    "taskflow_transition": handle_transition,
    "taskflow_add_update": handle_add_update,
    "taskflow_today": handle_today,
    "taskflow_upcoming": handle_upcoming,
    "taskflow_progress": handle_progress,
    "taskflow_list_subtasks": handle_list_subtasks,
    "taskflow_restore": handle_restore,
}


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if not handler:
        return text_result(f"未知工具: {name}")
    try:
        return await handler(arguments)
    except APIError as e:
        return text_result(f"API 錯誤: {e}")
    except APIConnectionError as e:
        return text_result(f"連線失敗: {e}")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
