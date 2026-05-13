"""Agent naming enforcement handler.

PreToolUse hook for the Agent tool:
- Block: missing or empty `name` parameter
- Suggest: general-purpose type when a specialized agent would fit
- Allow: MCP-dependent tasks or genuinely general work
"""

from __future__ import annotations

import os
import re

from .base import ALLOW, HookResult, block, message


def _is_litellm_proxy() -> bool:
    """Detect cc-llm/LiteLLM scenario where the underlying model is not Claude.

    Third-party models (minimax, glm, kimi, ...) routed through LiteLLM cannot
    be expected to follow the kebab-case `name` convention — enforcing it
    breaks the tool_use/tool_result pairing and crashes the session.
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    return "127.0.0.1:4000" in base_url or "localhost:4000" in base_url


def _derive_name(prompt: str, subagent_type: str) -> str:
    """Build a safe kebab-case fallback name from prompt + subagent_type."""
    words = re.findall(r"[a-z]+", (prompt or "").lower())[:3]
    if not words:
        words = ["run", "task"]
    base = "-".join(words)
    suffix = subagent_type or "agent"
    return f"{base}-{suffix}"[:60]


# Ordered by specificity: dispatchers first, then specific, then general.
# First match wins — keep specific keywords above broad ones.
KEYWORD_MAP: list[tuple[str, list[str]]] = [
    # Dispatchers
    ("codex-dispatcher", ["codex", "gpt-"]),
    ("gemini-dispatcher", ["gemini"]),
    ("copilot-dispatcher", ["copilot"]),
    # Specific agents
    ("chaos-engineer", ["chaos", "fault inject", "resilience test"]),
    (
        "media",
        ["video", "audio", "image process", "screen record", "ocr", "transcri", "tts", "stt"],
    ),
    ("browser", ["browser", "playwright", "scrape", "web page", "notebookllm"]),
    ("designer", ["diagram", "mermaid", "theme", "visual design", "ui design", "frontend design"]),
    # General agents
    ("researcher", ["research", "search web", "look up", "competitive", "company intel"]),
    ("reviewer", ["review", "audit", "quality check", "verify code", "security scan"]),
    ("writer", ["write doc", "draft doc", "content gen", "readme", "changelog", "spec"]),
    (
        "worker",
        ["implement", "edit file", "fix bug", "build", "scaffold", "refactor", "create file"],
    ),
    ("explorer", ["explore", "scan code", "find file", "codebase", "catalog", "topology"]),
]

MCP_KEYWORDS = ["mcpproxy", "retrieve_tools", "call_tool", "mcp server", "mcp tool"]


def _suggest_type(prompt: str) -> str | None:
    """Return the best-matching agent type for a prompt, or None."""
    lower = prompt.lower()
    for agent_type, keywords in KEYWORD_MAP:
        if any(kw in lower for kw in keywords):
            return agent_type
    return None


def _needs_mcp(prompt: str) -> bool:
    """Check if the prompt likely requires MCP tool access."""
    lower = prompt.lower()
    return any(kw in lower for kw in MCP_KEYWORDS)


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if tool_name != "Agent":
        return ALLOW

    name = tool_input.get("name", "").strip()
    subagent_type = tool_input.get("subagent_type", "").strip()
    prompt = tool_input.get("prompt", "")

    # Rule 1: name is mandatory
    if not name:
        # cc-llm / LiteLLM scenario: third-party model can't follow our
        # kebab-case convention. Auto-fill a derived name instead of blocking,
        # because blocking produces an empty tool_use_id that crashes strict
        # models like minimax-m2.7 with "tool result's tool id() not found".
        if _is_litellm_proxy():
            patched = dict(tool_input)
            patched["name"] = _derive_name(prompt, subagent_type)
            return HookResult(updated_input=patched)
        return block(
            "Agent must have a `name` parameter (kebab-case verb-noun, "
            'e.g. name: "scan-auth-routes"). Add a descriptive name and retry.'
        )

    # Rule 2: if using a specialized type, allow silently
    if subagent_type and subagent_type not in ("general-purpose", ""):
        return ALLOW

    # Rule 3: general-purpose with MCP need → allow silently
    if _needs_mcp(prompt):
        return ALLOW

    # Rule 4: suggest a better type if keyword matches
    suggested = _suggest_type(prompt)
    if suggested:
        return message(
            f'💡 Consider using `subagent_type: "{suggested}"` for this task '
            f"(matched keywords in prompt). general-purpose also works but "
            f"specialized agents have focused tools and cost less."
        )

    return ALLOW
