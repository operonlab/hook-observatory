"""LLM summary generation — claude --model haiku integration.

Generates one-line session summaries by extracting the first and last user messages
from the JSONL and sending them to Claude Haiku.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def _extract_user_messages(jsonl_path: Path, max_chars: int = 2000) -> tuple[str, str]:
    """Extract first and last user messages from a JSONL file.

    Returns (first_user_msg, last_user_msg). Truncates to max_chars each.
    """
    first_user = ""
    last_user = ""

    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") != "user":
                    continue

                # Extract text content from user message
                msg = _extract_text(event)
                if not msg:
                    continue

                if not first_user:
                    first_user = msg[:max_chars]
                last_user = msg[:max_chars]
    except OSError as e:
        logger.warning("read_jsonl_failed", path=str(jsonl_path), error=str(e))

    return first_user, last_user


def _extract_text(event: dict) -> str:
    """Extract plain text from a user event, handling various content formats."""
    # Direct message field
    if "message" in event and isinstance(event["message"], str):
        return event["message"]

    # Content array format
    message = event.get("message", {})
    if isinstance(message, dict):
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    parts.append(item)
            return " ".join(parts)

    return ""


def generate_summary(jsonl_path: Path, timeout: int = 30) -> str | None:
    """Generate a one-line session summary using Claude Haiku.

    Returns the summary string, or None on failure (graceful degradation).
    """
    first_msg, last_msg = _extract_user_messages(jsonl_path)

    if not first_msg and not last_msg:
        logger.warning("no_user_messages", path=str(jsonl_path))
        return None

    prompt_text = (
        "Summarize this Claude Code session in exactly 1 sentence (Traditional Chinese preferred). "
        "Focus on WHAT was accomplished, not the process.\n\n"
        f"First user message:\n{first_msg}\n\n"
        f"Last user message:\n{last_msg}"
    )

    try:
        result = subprocess.run(
            ["claude", "--model", "haiku", "-p", prompt_text],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning("claude_haiku_failed", returncode=result.returncode,
                           stderr=result.stderr[:200])
            return None

        summary = result.stdout.strip()
        if not summary:
            return None

        # Truncate to reasonable length
        return summary[:500]

    except subprocess.TimeoutExpired:
        logger.warning("claude_haiku_timeout", timeout=timeout)
        return None
    except FileNotFoundError:
        logger.warning("claude_cli_not_found")
        return None
    except OSError as e:
        logger.warning("summary_generation_failed", error=str(e))
        return None
