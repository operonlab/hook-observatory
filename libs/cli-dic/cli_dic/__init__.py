"""cli-dic — CLI tool dictionary for the Workshop ecosystem.

Declarative descriptors for coding CLI tools (Claude Code, Codex CLI, Gemini CLI).
Used by tmux-relay, maestro, headless wrappers, and session-channel board.

    from cli_dic import get, CLAUDE_CODE
    entry = get("claude")
    cmd = entry.headless_cmd("fix the bug", auto_approve=True)
"""

from cli_dic.base import (
    AgentSpec,
    AutoApprove,
    CLIEntry,
    ExitBehavior,
    HeadlessSpec,
    HookSpec,
    InstructionSpec,
    MCPSpec,
    SkillSpec,
    ToolNameMap,
)
from cli_dic.claude_code import CLAUDE_CODE
from cli_dic.codex_cli import CODEX_CLI
from cli_dic.gemini_cli import GEMINI_CLI
from cli_dic.registry import detect_from_command, get, list_entries, list_names, register

__all__ = [
    "CLAUDE_CODE",
    "CODEX_CLI",
    "GEMINI_CLI",
    "AgentSpec",
    "AutoApprove",
    "CLIEntry",
    "ExitBehavior",
    "HeadlessSpec",
    "HookSpec",
    "InstructionSpec",
    "MCPSpec",
    "SkillSpec",
    "ToolNameMap",
    "detect_from_command",
    "get",
    "list_entries",
    "list_names",
    "register",
]
