"""
Annotate Insight PostToolUse handler -- realtime knowledge annotation post-processing.

Features:
  - Listens for mcp__memvault__annotate_insight tool call completion events
  - Optional: calls LiteLLM (qwen3.5-flash) to suggest additional tags for the insight
  - Gracefully skips when LiteLLM is unavailable (does not block main flow)

Design principles:
  - Fire-and-forget: all enrichment logic runs in background, no hook response delay
  - Fail-safe: any exception silently degrades, does not affect annotate_insight main function
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from .base import ALLOW, HOME, HookResult, run_background

# LiteLLM proxy (optional enrichment), gracefully skipped when unavailable
LITELLM_API = os.environ.get("LITELLM_API", "http://127.0.0.1:4000/v1")
LITELLM_MODEL = os.environ.get("ANNOTATE_TAG_MODEL", "qwen3.5-flash")
LITELLM_TIMEOUT = 5  # seconds; fail fast, do not slow down main flow

# tool_name pattern for annotate_insight under mcpproxy
# Claude calls MCP tools with format: mcp__<server>__<tool>
_TOOL_PATTERN = "mcp__memvault__annotate_insight"


def _suggest_tags_via_litellm(insight: str, existing_tags: list[str]) -> list[str]:
    """Call LiteLLM to suggest supplemental tags for the insight (max 3).

    Returns empty list on failure.
    """
    try:
        existing_str = ", ".join(existing_tags) if existing_tags else "(none)"
        prompt = (
            "Given the following insight, suggest 2-3 short tag keywords "
            "(in Traditional Chinese or English) "
            "that would help categorize it for future retrieval. "
            "Return ONLY a JSON array of strings, no explanation.\n\n"
            f"Existing tags: {existing_str}\n"
            f"Insight: {insight[:300]}"
        )

        body = json.dumps(
            {
                "model": LITELLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 60,
                "temperature": 0.3,
            }
        ).encode()

        req = urllib.request.Request(  # noqa: S310
            f"{LITELLM_API}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=LITELLM_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())

        raw_content = data["choices"][0]["message"]["content"].strip()

        # parse JSON array from response
        if raw_content.startswith("["):
            suggested = json.loads(raw_content)
            if isinstance(suggested, list):
                # filter out existing tags, take at most 3
                new_tags = [
                    str(t).strip() for t in suggested if str(t).strip() not in existing_tags
                ]
                return new_tags[:3]

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError):
        # LiteLLM unavailable or unexpected response format -- silently skip
        return []
    except Exception:
        # unexpected error -- silently degrade, do not block main flow
        return []

    return []


def _enhance_block(block_id: str, insight: str, existing_tags: list[str]) -> None:
    """Background worker: call LiteLLM to supplement tags, then update the memvault block."""
    sys.path.insert(0, os.path.join(HOME, "workshop", "libs", "python", "src"))

    try:
        from sdk_client.clients.memvault import MemvaultClient
    except ImportError:
        return

    # get suggested tags
    new_tags = _suggest_tags_via_litellm(insight, existing_tags)
    if not new_tags:
        return  # no new tags, skip update

    # merge and deduplicate
    merged_tags = list(dict.fromkeys(existing_tags + new_tags))

    try:
        client = MemvaultClient()
        client.update_block(block_id, tags=merged_tags)
    except Exception:
        # update failure silently degrades -- do not block background process
        return


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PostToolUse handler: annotate_insight completion → background tag enrichment."""
    # only process annotate_insight tool completion events
    if tool_name != _TOOL_PATTERN:
        return ALLOW

    # parse tool output to get block_id
    try:
        data = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except (json.JSONDecodeError, TypeError):
        return ALLOW

    # PostToolUse tool_response field contains tool output
    tool_response = data.get("tool_response", "") or ""
    insight = (data.get("tool_input") or tool_input).get("insight", "")
    existing_tags = [
        *((data.get("tool_input") or tool_input).get("tags") or []),
        "realtime-annotation",
    ]

    # parse Block ID from output text (format: "Block ID: <uuid>")
    block_id = ""
    for line in str(tool_response).split("\n"):
        if line.startswith("Block ID:"):
            block_id = line.split(":", 1)[-1].strip()
            break

    # skip enrichment if no valid block_id or insight content
    if not block_id or not insight:
        return ALLOW

    # fire-and-forget: run LiteLLM tag enrichment in background
    python = os.path.join(HOME, ".local", "bin", "python3")
    script = os.path.abspath(__file__)

    run_background(
        [
            python,
            script,
            "--block-id",
            block_id,
            "--insight",
            insight[:300],
            "--tags",
            json.dumps(existing_tags),
        ],
        cwd=os.path.join(HOME, "workshop"),
    )

    return ALLOW


# ---------------------------------------------------------------------------
# Worker mode (called by background process)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Annotate insight tag enhancer")
    parser.add_argument("--block-id", required=True)
    parser.add_argument("--insight", required=True)
    parser.add_argument("--tags", default="[]")
    args = parser.parse_args()

    try:
        existing = json.loads(args.tags)
    except (json.JSONDecodeError, TypeError):
        existing = []

    _enhance_block(args.block_id, args.insight, existing)
