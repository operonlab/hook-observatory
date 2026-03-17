#!/Users/joneshong/.local/bin/python3
"""Taskflow CLI — command-line interface for Taskflow Core API.

Uses the shared workshop SDK client (TaskflowClient).

Usage:
    taskflow tasks list [--status S] [--source S] [--project P] [--priority P]
                        [--tag T] [--search Q] [--top-level] [--json]
    taskflow tasks get <id> [--json]
    taskflow tasks create --title T --source S [--description D] [--project P]
                          [--priority P] [--due-date D] [--start-date D]
                          [--estimated-hours H] [--tags t1,t2] [--parent P] [--json]
    taskflow tasks update <id> [--title T] [--description D] [--source S]
                          [--project P] [--priority P] [--due-date D]
                          [--start-date D] [--estimated-hours H]
                          [--actual-hours H] [--tags t1,t2] [--json]
    taskflow tasks delete <id>
    taskflow tasks subtasks <id> [--json]
    taskflow tasks transition <id> --status S [--comment C] [--json]
    taskflow updates list <task_id> [--json]
    taskflow updates add <task_id> --type T --content C [--hours H] [--json]
    taskflow today [--json]
    taskflow upcoming [--days D] [--json]
    taskflow progress [--json]
    taskflow trash list [--json]
    taskflow trash restore <id> [--json]

Symlink: ln -sf ~/workshop/core/cli/taskflow.py ~/.local/bin/taskflow
"""

import argparse

from cli.cli_helpers import err, fmt_date, json_out
from cli.cli_utils import resolve_text_arg
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.taskflow import TaskflowClient
from workshop.fmt_constants import TASKFLOW_PRIORITY_EMOJI, TASKFLOW_STATUS_EMOJI

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _client():
    return TaskflowClient()


def fmt_priority(p):
    """Format priority with icon."""
    icon = TASKFLOW_PRIORITY_EMOJI.get(p, "")
    return f"{icon} {p}" if icon else (p or "-")


def fmt_status(s):
    """Format status with icon."""
    icon = TASKFLOW_STATUS_EMOJI.get(s, "")
    return f"{icon} {s}" if icon else (s or "-")


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


def cmd_task_list(args):
    client = _client()
    try:
        result = client.list_tasks(
            status=args.status,
            source=args.source,
            project=args.project,
            priority=args.priority,
            tag=args.tag,
            search=args.search,
            top_level=args.top_level,
            page=1,
            page_size=50,
        )
        if json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Tasks ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for t in items:
            status = TASKFLOW_STATUS_EMOJI.get(t.get("status", ""), "?")
            priority = TASKFLOW_PRIORITY_EMOJI.get(t.get("priority", ""), "")
            due = fmt_date(t.get("due_date"))
            title = t.get("title", "")
            print(f"  {status} {priority} {title[:50]:<52s}  due: {due}  id={t['id'][:8]}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_task_get(args):
    client = _client()
    try:
        t = client.get_task(args.id)
        if json_out(t, args):
            return
        print(f"Task: {t['id']}")
        print(f"  Title:       {t.get('title')}")
        print(f"  Status:      {fmt_status(t.get('status'))}")
        print(f"  Priority:    {fmt_priority(t.get('priority'))}")
        print(f"  Source:      {t.get('source', '-')}")
        print(f"  Project:     {t.get('project', '-')}")
        print(f"  Due:         {fmt_date(t.get('due_date'))}")
        print(f"  Start:       {fmt_date(t.get('start_date'))}")
        print(f"  Est. hours:  {t.get('estimated_hours', '-')}")
        print(f"  Act. hours:  {t.get('actual_hours', '-')}")
        tags = ", ".join(t.get("tags", [])) or "-"
        print(f"  Tags:        {tags}")
        parent = t.get("parent_id")
        print(f"  Parent:      {parent[:8] if parent else '-'}")
        desc = t.get("description", "")
        if desc:
            print(f"  Description: {desc[:120]}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_task_create(args):
    client = _client()
    try:
        data: dict = {"title": args.title, "source": args.source}
        description = resolve_text_arg(args.description)
        if description:
            data["description"] = description
        if args.project:
            data["project"] = args.project
        if args.priority:
            data["priority"] = args.priority
        if args.due_date:
            data["due_date"] = args.due_date
        if args.start_date:
            data["start_date"] = args.start_date
        if args.estimated_hours is not None:
            data["estimated_hours"] = args.estimated_hours
        if args.tags:
            data["tags"] = [t.strip() for t in args.tags.split(",")]
        if args.parent:
            data["parent_id"] = args.parent
        result = client.create_task(data)
        if json_out(result, args):
            return
        print(f"Task created: {result['id']}")
        print(
            f"  {fmt_status(result.get('status'))}  {fmt_priority(result.get('priority'))}"
            f"  {result.get('title')}"
        )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_task_update(args):
    client = _client()
    try:
        data: dict = {}
        if args.title:
            data["title"] = args.title
        description = resolve_text_arg(args.description)
        if description:
            data["description"] = description
        if args.source:
            data["source"] = args.source
        if args.project:
            data["project"] = args.project
        if args.priority:
            data["priority"] = args.priority
        if args.due_date:
            data["due_date"] = args.due_date
        if args.start_date:
            data["start_date"] = args.start_date
        if args.estimated_hours is not None:
            data["estimated_hours"] = args.estimated_hours
        if args.actual_hours is not None:
            data["actual_hours"] = args.actual_hours
        if args.tags:
            data["tags"] = [t.strip() for t in args.tags.split(",")]
        result = client.update_task(args.id, data)
        if json_out(result, args):
            return
        print(f"Task updated: {result['id']}")
        print(
            f"  {fmt_status(result.get('status'))}  {fmt_priority(result.get('priority'))}"
            f"  {result.get('title')}"
        )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_task_delete(args):
    client = _client()
    try:
        client.delete_task(args.id)
        print(f"Task deleted: {args.id}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_task_subtasks(args):
    client = _client()
    try:
        result = client.list_subtasks(args.id, page=1, page_size=50)
        if json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Subtasks of {args.id[:8]} ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for t in items:
            status = TASKFLOW_STATUS_EMOJI.get(t.get("status", ""), "?")
            priority = TASKFLOW_PRIORITY_EMOJI.get(t.get("priority", ""), "")
            due = fmt_date(t.get("due_date"))
            print(
                f"  {status} {priority} {t.get('title', '')[:50]:<52s}"
                f"  due: {due}  id={t['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_task_transition(args):
    client = _client()
    try:
        result = client.transition_status(args.id, status=args.status, comment=args.comment)
        if json_out(result, args):
            return
        print(f"Task {args.id[:8]} transitioned to: {fmt_status(result.get('status'))}")
        print(f"  {result.get('title')}")
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# updates
# ---------------------------------------------------------------------------


def cmd_update_list(args):
    client = _client()
    try:
        result = client.list_updates(args.task_id, page=1, page_size=50)
        if json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Updates for task {args.task_id[:8]} ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for u in items:
            created = fmt_date(u.get("created_at"))
            hours = u.get("hours_logged")
            hours_str = f"  +{hours}h" if hours else ""
            print(
                f"  [{created}] [{u.get('type', '?'):<10s}]{hours_str}"
                f"  {u.get('content', '')[:80]}"
                f"  id={u['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_update_add(args):
    client = _client()
    try:
        data: dict = {"type": args.type, "content": resolve_text_arg(args.content)}
        if args.hours is not None:
            data["hours_logged"] = args.hours
        result = client.add_update(args.task_id, data)
        if json_out(result, args):
            return
        print(f"Update added: {result['id']}")
        print(f"  [{result.get('type')}]  {result.get('content', '')[:80]}")
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# today / upcoming / progress
# ---------------------------------------------------------------------------


def cmd_today(args):
    client = _client()
    try:
        items = client.get_today(space_id=None)
        if json_out(items, args):
            return
        print(f"Today's Tasks ({len(items)} tasks)\n")
        if not items:
            print("  (none)")
            return
        for t in items:
            status = TASKFLOW_STATUS_EMOJI.get(t.get("status", ""), "?")
            priority = TASKFLOW_PRIORITY_EMOJI.get(t.get("priority", ""), "")
            print(f"  {status} {priority} {t.get('title', '')[:55]:<57s}  id={t['id'][:8]}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_upcoming(args):
    client = _client()
    try:
        items = client.get_upcoming(space_id=None, days=args.days)
        if json_out(items, args):
            return
        print(f"Upcoming Tasks — next {args.days} days ({len(items)} tasks)\n")
        if not items:
            print("  (none)")
            return
        for t in items:
            status = TASKFLOW_STATUS_EMOJI.get(t.get("status", ""), "?")
            priority = TASKFLOW_PRIORITY_EMOJI.get(t.get("priority", ""), "")
            due = fmt_date(t.get("due_date"))
            print(
                f"  {status} {priority} {t.get('title', '')[:50]:<52s}"
                f"  due: {due}  id={t['id'][:8]}"
            )
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_progress(args):
    client = _client()
    try:
        p = client.get_progress(space_id=None)
        if json_out(p, args):
            return
        print("Task Progress Summary\n")
        total = p.get("total", 0)
        done = p.get("done", 0)
        in_progress = p.get("in_progress", 0)
        todo = p.get("todo", 0)
        blocked = p.get("blocked", 0)
        cancelled = p.get("cancelled", 0)
        review = p.get("review", 0)
        pct = p.get("completion_pct", 0)
        print(f"  Total:       {total}")
        print(f"  ✅ Done:      {done}  ({pct:.1f}%)")
        print(f"  🔵 In progress: {in_progress}")
        print(f"  🟣 Review:    {review}")
        print(f"  ⬜ Todo:      {todo}")
        print(f"  🚫 Blocked:   {blocked}")
        print(f"  ⬛ Cancelled: {cancelled}")
        overdue = p.get("overdue", 0)
        if overdue:
            print(f"\n  ⚠️  Overdue:   {overdue}")
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# trash
# ---------------------------------------------------------------------------


def cmd_trash_list(args):
    client = _client()
    try:
        result = client.list_trash(page=1, page_size=50)
        if json_out(result, args):
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Trash ({total} total)\n")
        if not items:
            print("  (none)")
            return
        for t in items:
            deleted = fmt_date(t.get("deleted_at"))
            print(f"  {t.get('title', '')[:55]:<57s}  deleted: {deleted}  id={t['id'][:8]}")
    except (APIError, APIConnectionError) as e:
        err(e)


def cmd_trash_restore(args):
    client = _client()
    try:
        result = client.restore_task(args.id)
        if json_out(result, args):
            return
        print(f"Task restored: {result['id']}")
        print(f"  {fmt_status(result.get('status'))}  {result.get('title')}")
    except (APIError, APIConnectionError) as e:
        err(e)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        prog="taskflow", description="Taskflow CLI for Workshop Core API"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # -- tasks --
    task_parser = sub.add_parser("tasks", aliases=["t"], help="Task management")
    task_sub = task_parser.add_subparsers(dest="action", required=True)

    task_list = task_sub.add_parser("list", help="List tasks")
    task_list.add_argument("--status", help="Filter by status")
    task_list.add_argument("--source", help="Filter by source")
    task_list.add_argument("--project", help="Filter by project")
    task_list.add_argument("--priority", help="Filter by priority")
    task_list.add_argument("--tag", help="Filter by tag")
    task_list.add_argument("--search", help="Full-text search query")
    task_list.add_argument(
        "--top-level",
        dest="top_level",
        action="store_true",
        help="Only top-level tasks (no parent)",
    )
    task_list.set_defaults(func=cmd_task_list)

    task_get = task_sub.add_parser("get", help="Get task by ID")
    task_get.add_argument("id", help="Task ID")
    task_get.set_defaults(func=cmd_task_get)

    task_create = task_sub.add_parser("create", help="Create a task")
    task_create.add_argument("--title", required=True, help="Task title")
    task_create.add_argument("--source", required=True, help="Source system/context")
    task_create.add_argument("--description", help="Task description")
    task_create.add_argument("--project", help="Project name or ID")
    task_create.add_argument(
        "--priority",
        choices=["urgent", "high", "medium", "low"],
        help="Task priority",
    )
    task_create.add_argument("--due-date", dest="due_date", help="Due date (YYYY-MM-DD)")
    task_create.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    task_create.add_argument(
        "--estimated-hours", dest="estimated_hours", type=float, help="Estimated hours"
    )
    task_create.add_argument("--tags", help="Comma-separated tags")
    task_create.add_argument("--parent", help="Parent task ID")
    task_create.set_defaults(func=cmd_task_create)

    task_update = task_sub.add_parser("update", help="Update a task")
    task_update.add_argument("id", help="Task ID")
    task_update.add_argument("--title", help="New title")
    task_update.add_argument("--description", help="New description")
    task_update.add_argument("--source", help="New source")
    task_update.add_argument("--project", help="New project")
    task_update.add_argument(
        "--priority",
        choices=["urgent", "high", "medium", "low"],
        help="New priority",
    )
    task_update.add_argument("--due-date", dest="due_date", help="New due date (YYYY-MM-DD)")
    task_update.add_argument("--start-date", dest="start_date", help="New start date (YYYY-MM-DD)")
    task_update.add_argument(
        "--estimated-hours", dest="estimated_hours", type=float, help="New estimated hours"
    )
    task_update.add_argument(
        "--actual-hours", dest="actual_hours", type=float, help="Actual hours logged"
    )
    task_update.add_argument("--tags", help="Comma-separated tags (replaces existing)")
    task_update.set_defaults(func=cmd_task_update)

    task_delete = task_sub.add_parser("delete", help="Delete a task")
    task_delete.add_argument("id", help="Task ID")
    task_delete.set_defaults(func=cmd_task_delete)

    task_subtasks = task_sub.add_parser("subtasks", help="List subtasks of a task")
    task_subtasks.add_argument("id", help="Parent task ID")
    task_subtasks.set_defaults(func=cmd_task_subtasks)

    task_transition = task_sub.add_parser("transition", help="Transition task status")
    task_transition.add_argument("id", help="Task ID")
    task_transition.add_argument(
        "--status",
        required=True,
        choices=["todo", "in_progress", "review", "done", "blocked", "cancelled"],
        help="New status",
    )
    task_transition.add_argument("--comment", help="Optional transition comment")
    task_transition.set_defaults(func=cmd_task_transition)

    # -- updates --
    upd_parser = sub.add_parser("updates", aliases=["upd"], help="Task update management")
    upd_sub = upd_parser.add_subparsers(dest="action", required=True)

    upd_list = upd_sub.add_parser("list", help="List updates for a task")
    upd_list.add_argument("task_id", help="Task ID")
    upd_list.set_defaults(func=cmd_update_list)

    upd_add = upd_sub.add_parser("add", help="Add an update to a task")
    upd_add.add_argument("task_id", help="Task ID")
    upd_add.add_argument("--type", "-t", required=True, help="Update type (e.g. comment, progress)")
    upd_add.add_argument("--content", "-c", required=True, help="Update content")
    upd_add.add_argument("--hours", type=float, help="Hours logged with this update")
    upd_add.set_defaults(func=cmd_update_add)

    # -- today --
    today_parser = sub.add_parser("today", help="Show tasks due today")
    today_parser.set_defaults(func=cmd_today)

    # -- upcoming --
    upcoming_parser = sub.add_parser("upcoming", help="Show upcoming tasks")
    upcoming_parser.add_argument(
        "--days", "-d", type=int, default=7, help="Days ahead to look (default: 7)"
    )
    upcoming_parser.set_defaults(func=cmd_upcoming)

    # -- progress --
    progress_parser = sub.add_parser("progress", help="Show task completion progress")
    progress_parser.set_defaults(func=cmd_progress)

    # -- trash --
    trash_parser = sub.add_parser("trash", help="Manage deleted tasks")
    trash_sub = trash_parser.add_subparsers(dest="action", required=True)

    trash_list = trash_sub.add_parser("list", help="List trashed tasks")
    trash_list.set_defaults(func=cmd_trash_list)

    trash_restore = trash_sub.add_parser("restore", help="Restore a trashed task")
    trash_restore.add_argument("id", help="Task ID")
    trash_restore.set_defaults(func=cmd_trash_restore)

    args = parser.parse_args()

    # Propagate top-level --json flag to sub-parsers that don't have it explicitly
    if not hasattr(args, "json"):
        args.json = False

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
