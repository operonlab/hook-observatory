"""Shared formatting constants across CLI + MCP layers."""

TASKFLOW_STATUS_EMOJI: dict[str, str] = {
    "todo": "\u2b1c",
    "in_progress": "\U0001f535",
    "review": "\U0001f7e3",
    "done": "\u2705",
    "blocked": "\U0001f6ab",
    "cancelled": "\u2b1b",
}

TASKFLOW_PRIORITY_EMOJI: dict[str, str] = {
    "urgent": "\U0001f534",
    "high": "\U0001f7e0",
    "medium": "\U0001f7e1",
    "low": "\U0001f7e2",
}
