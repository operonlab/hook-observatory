"""cli-rosetta — CLI tool dictionary for the Workshop ecosystem.

Declarative descriptors for coding CLI tools (Claude Code, Codex CLI, Gemini CLI).
Used by tmux-relay, maestro, headless wrappers, and session-channel board.

    from cli_rosetta import get, CLAUDE_CODE
    entry = get("claude")
    cmd = entry.headless_cmd("fix the bug", auto_approve=True)
"""

from cli_rosetta.base import (
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
from cli_rosetta.claude_code import CLAUDE_CODE
from cli_rosetta.codex_cli import CODEX_CLI
from cli_rosetta.copilot_cli import COPILOT_CLI
from cli_rosetta.gemini_cli import GEMINI_CLI
from cli_rosetta.qwen_code import QWEN_CODE
from cli_rosetta.registry import detect_from_command, get, list_entries, list_names, register

__all__ = [
    "CLAUDE_CODE",
    "CODEX_CLI",
    "COPILOT_CLI",
    "GEMINI_CLI",
    "QWEN_CODE",
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
