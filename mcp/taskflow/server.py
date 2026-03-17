#!/usr/bin/env python3
"""Taskflow MCP Server — tasks, transitions, progress thin adapter over Core API.

12 tools: list_tasks, get_task, create_task, update_task, delete_task,
          transition, add_update, today, upcoming, progress,
          list_subtasks, restore.
Uses workshop.clients.taskflow SDK.

Usage:
    python3 mcp/taskflow/server.py
"""

from asyncio import to_thread
from typing import Optional

from mcp.server.fastmcp import FastMCP
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.taskflow import TaskflowClient

mcp = FastMCP("workshop-taskflow")
client = TaskflowClient()


# ======================== Helpers ========================


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


# ======================== Tools ========================


@mcp.tool()
async def taskflow_list_tasks(
    status: Optional[str] = None,
    source: Optional[str] = None,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    top_level: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """列出任務（可依狀態/來源/專案/優先級/標籤/關鍵字篩選）"""
    try:
        result = await to_thread(
            client.list_tasks,
            status=status,
            source=source,
            project=project,
            priority=priority,
            tag=tag,
            search=search,
            top_level=top_level,
            page=page,
            page_size=page_size,
        )
        items = result.get("items", [])
        if not items:
            return "目前沒有符合條件的任務。"
        total = result.get("total", 0)
        lines = [f"# 任務列表（共 {total} 筆）\n"]
        for t in items:
            lines.append(fmt_task_line(t))
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_get_task(task_id: str) -> str:
    """查看任務詳情（含子任務與進度更新）"""
    try:
        result = await to_thread(client.get_task, task_id)
        return fmt_task_detail(result)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_create_task(
    title: str,
    source: str,
    description: Optional[str] = None,
    project: Optional[str] = None,
    priority: str = "medium",
    due_date: Optional[str] = None,
    start_date: Optional[str] = None,
    estimated_hours: Optional[float] = None,
    tags: Optional[list[str]] = None,
    parent_id: Optional[str] = None,
) -> str:
    """新增任務"""
    try:
        body: dict = {"title": title, "source": source}
        if description is not None:
            body["description"] = description
        if project is not None:
            body["project"] = project
        if priority is not None:
            body["priority"] = priority
        if due_date is not None:
            body["due_date"] = due_date
        if start_date is not None:
            body["start_date"] = start_date
        if estimated_hours is not None:
            body["estimated_hours"] = estimated_hours
        if tags is not None:
            body["tags"] = tags
        if parent_id is not None:
            body["parent_id"] = parent_id
        result = await to_thread(client.create_task, body)
        p = result.get("priority", "medium")
        return (
            f"任務已建立\n"
            f"- 標題: {result['title']}\n"
            f"- 優先級: {PRIORITY_EMOJI.get(p, '')} {p}\n"
            f"- ID: `{result['id'][:8]}`"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    source: Optional[str] = None,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
    start_date: Optional[str] = None,
    estimated_hours: Optional[float] = None,
    actual_hours: Optional[float] = None,
    tags: Optional[list[str]] = None,
    parent_id: Optional[str] = None,
) -> str:
    """更新任務欄位"""
    try:
        body: dict = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if source is not None:
            body["source"] = source
        if project is not None:
            body["project"] = project
        if priority is not None:
            body["priority"] = priority
        if due_date is not None:
            body["due_date"] = due_date
        if start_date is not None:
            body["start_date"] = start_date
        if estimated_hours is not None:
            body["estimated_hours"] = estimated_hours
        if actual_hours is not None:
            body["actual_hours"] = actual_hours
        if tags is not None:
            body["tags"] = tags
        if parent_id is not None:
            body["parent_id"] = parent_id
        result = await to_thread(client.update_task, task_id, body)
        return (
            f"任務已更新\n- 標題: {result.get('title', '')}\n- ID: `{result.get('id', '')[:8]}`"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_delete_task(task_id: str) -> str:
    """刪除任務（軟刪除，移至垃圾桶）"""
    try:
        await to_thread(client.delete_task, task_id)
        return f"任務 `{task_id[:8]}` 已移至垃圾桶。"
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_transition(
    task_id: str,
    status: str,
    comment: Optional[str] = None,
) -> str:
    """變更任務狀態（todo/in_progress/review/done/blocked/cancelled）"""
    try:
        result = await to_thread(client.transition_status, task_id, status, comment)
        s_emoji = STATUS_EMOJI.get(status, "")
        return (
            f"狀態已更新\n"
            f"- 任務: {result.get('title', '')}\n"
            f"- 新狀態: {s_emoji} {status}\n"
            f"- ID: `{result.get('id', '')[:8]}`"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_add_update(
    task_id: str,
    type: str,
    content: str,
    hours_spent: Optional[float] = None,
) -> str:
    """新增進度更新（progress / blocker / note / status_change）"""
    try:
        body: dict = {"type": type, "content": content}
        if hours_spent is not None:
            body["hours_spent"] = hours_spent
        result = await to_thread(client.add_update, task_id, body)
        return (
            f"進度更新已記錄\n"
            f"- 類型: {result.get('type', '')}\n"
            f"- 內容: {result.get('content', '')[:80]}\n"
            f"- ID: `{result.get('id', '')[:8]}`"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_today() -> str:
    """列出今日任務（今日到期 + 進行中）"""
    try:
        items = await to_thread(client.get_today)
        if not items:
            return "今日沒有待辦任務，幹得漂亮！"
        lines = [f"# 今日任務（共 {len(items)} 筆）\n"]
        for t in items:
            lines.append(fmt_task_line(t))
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_upcoming(days: int = 7) -> str:
    """列出即將到期的任務"""
    try:
        items = await to_thread(client.get_upcoming, days)
        if not items:
            return f"未來 {days} 天內沒有到期任務。"
        lines = [f"# 即將到期任務（{days} 天內，共 {len(items)} 筆）\n"]
        for t in items:
            lines.append(fmt_task_line(t))
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_progress() -> str:
    """查看任務進度統計（狀態/來源/優先級分布、逾期數、工時）"""
    try:
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

        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_list_subtasks(
    task_id: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """列出指定任務的子任務"""
    try:
        result = await to_thread(
            client.list_subtasks,
            task_id,
            page=page,
            page_size=page_size,
        )
        items = result.get("items", [])
        if not items:
            return "此任務目前沒有子任務。"
        total = result.get("total", 0)
        lines = [f"# 子任務（共 {total} 筆）\n"]
        for t in items:
            lines.append(fmt_task_line(t))
        return "\n".join(lines)
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def taskflow_restore(task_id: str) -> str:
    """從垃圾桶還原已刪除的任務"""
    try:
        result = await to_thread(client.restore_task, task_id)
        return (
            f"任務已還原\n- 標題: {result.get('title', '')}\n- ID: `{result.get('id', '')[:8]}`"
        )
    except APIError as e:
        return f"API 錯誤: {e}"
    except APIConnectionError as e:
        return f"連線失敗: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
