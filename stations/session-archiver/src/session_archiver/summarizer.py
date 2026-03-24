"""LLM summary generation — claude --model haiku integration.

Generates one-line session summaries by extracting the first and last user messages
from the JSONL and sending them to Claude Haiku.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import structlog

sys.path.insert(0, "/Users/joneshong/workshop/core")

logger = structlog.get_logger(__name__)


def _extract_user_messages(jsonl_path: Path, max_chars: int = 2000) -> tuple[str, str]:
    """Extract first and last user messages from a JSONL file.

    Returns (first_user_msg, last_user_msg). Truncates to max_chars each.
    """
    first_user = ""
    last_user = ""

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
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


def generate_summary(jsonl_path: Path, timeout: int | None = None) -> str | None:
    """Generate a one-line session summary using Claude Haiku.

    Returns the summary string, or None on failure (graceful degradation).
    Timeout scales with file size: base 30s + 2s/MB, capped at 180s.
    """
    file_size_mb = jsonl_path.stat().st_size / (1024 * 1024) if jsonl_path.exists() else 0
    if timeout is None:
        timeout = min(180, max(30, 30 + int(file_size_mb * 2)))

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

    # Clean env: remove CLAUDECODE to avoid interfering with nested claude CLI calls
    import os
    import time

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["claude", "--model", "haiku", "-p", prompt_text],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if result.returncode != 0:
                logger.warning(
                    "claude_haiku_failed",
                    returncode=result.returncode,
                    stderr=result.stderr[:200],
                    attempt=attempt + 1,
                )
                if attempt < max_retries - 1:
                    backoff = 2**attempt  # 1s, 2s, 4s
                    time.sleep(backoff)
                    continue
                return None

            summary = result.stdout.strip()
            if not summary:
                return None

            # Truncate to reasonable length
            return summary[:500]

        except subprocess.TimeoutExpired:
            logger.warning(
                "claude_haiku_timeout",
                timeout=timeout,
                file_size_mb=round(file_size_mb, 1),
                attempt=attempt + 1,
            )
            if attempt < max_retries - 1:
                backoff = 2**attempt
                time.sleep(backoff)
                continue
            return None
        except FileNotFoundError:
            logger.warning("claude_cli_not_found")
            return None
        except OSError as e:
            logger.warning("summary_generation_failed", error=str(e))
            return None
    return None


def generate_summary_rlm(jsonl_path: Path, timeout: int = 45) -> dict | None:
    """Generate a structured session summary using RLM engine.

    Returns a dict with {goal, key_decisions, outcomes, follow_ups},
    or None on failure (caller should fallback to generate_summary).
    """
    # Read JSONL content for context
    try:
        content = jsonl_path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            logger.warning("empty_jsonl", path=str(jsonl_path))
            return None
    except OSError as e:
        logger.warning("read_jsonl_failed", path=str(jsonl_path), error=str(e))
        return None

    # Truncate to ~50K chars to keep RLM context manageable
    if len(content) > 50_000:
        content = content[:25_000] + "\n...[truncated]...\n" + content[-25_000:]

    prompt = (
        "Analyze this Claude Code session transcript and produce a structured summary.\n\n"
        "Output ONLY valid JSON with these exact keys:\n"
        "{\n"
        '  "goal": "The primary goal of this session (1 sentence, Traditional Chinese preferred)",\n'
        '  "key_decisions": ["Decision 1", "Decision 2", ...],\n'
        '  "outcomes": ["What was accomplished 1", "What was accomplished 2", ...],\n'
        '  "follow_ups": ["Remaining task 1", "Remaining task 2", ...]\n'
        "}\n\n"
        "Rules:\n"
        "- Each array should have 1-5 items\n"
        "- Use Traditional Chinese when the session content is in Chinese\n"
        "- Focus on WHAT was done and decided, not HOW\n"
        "- If no clear follow-ups exist, use an empty array\n"
        "- Output ONLY the JSON object, no markdown fencing"
    )

    try:
        from src.shared.rlm_engine import RLMConfig, RLMEngine

        engine = RLMEngine(
            RLMConfig(
                model="grok-4-fast",
                max_iterations=5,
                max_timeout_secs=timeout,
                api_base="http://localhost:4000/v1",
                api_key="sk-litellm-local-dev",
            )
        )
        result = engine.completion(prompt=prompt, context=content)

        if result.status != "ok" or not result.response:
            logger.warning("rlm_empty_response", status=result.status)
            return None

        # Parse JSON from response
        import re

        raw = result.response.strip()
        # Try to extract JSON object
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            logger.warning("rlm_no_json", response=raw[:200])
            return None

        data = json.loads(json_match.group())

        # Validate required keys
        required = {"goal", "key_decisions", "outcomes", "follow_ups"}
        if not required.issubset(data.keys()):
            logger.warning("rlm_missing_keys", keys=list(data.keys()))
            return None

        # Ensure arrays
        for key in ("key_decisions", "outcomes", "follow_ups"):
            if not isinstance(data[key], list):
                data[key] = [str(data[key])]

        return {
            "goal": str(data["goal"])[:500],
            "key_decisions": [str(d)[:200] for d in data["key_decisions"][:5]],
            "outcomes": [str(o)[:200] for o in data["outcomes"][:5]],
            "follow_ups": [str(f)[:200] for f in data["follow_ups"][:5]],
        }

    except json.JSONDecodeError as e:
        logger.warning("rlm_json_parse_failed", error=str(e))
        return None
    except Exception as e:
        logger.warning("rlm_summary_failed", error=str(e))
        return None
