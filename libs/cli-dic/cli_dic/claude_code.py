"""Claude Code CLI entry."""

from __future__ import annotations

import re

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
)

CLAUDE_CODE = CLIEntry(
    name="claude-code",
    binary="claude",
    display_name="Claude Code",
    vendor="anthropic",
    config_dir="~/.claude/",
    install_command="npm install -g @anthropic-ai/claude-code",
    exit_behavior=ExitBehavior(command="/exit", needs_enter=True),
    idle_prompt="❯",
    processing_indicators=("⏺", "✢", "✻", "Thinking", "Processing"),
    headless=HeadlessSpec(
        prompt_flag="-p",
        output_format_flag="--output-format",
        cwd_flag="--cwd",
        env_unset=("CLAUDECODE",),
    ),
    auto_approve=AutoApprove(
        flag="--dangerously-skip-permissions",
        aliases=("--permission-mode bypassPermissions",),
    ),
    model_flag="--model",
    default_model="sonnet",
    resume_flag="--resume",
    continue_flag="--continue",
    known_version="2.1.92",
    prompt_pattern=re.compile(r"❯"),
    process_names=frozenset({"claude"}),
    # ── Configuration ecosystem ──
    mcp=MCPSpec(
        config_format="json",
        config_path=".mcp.json",  # project-level; also --mcp-config flag
        config_key="mcpServers",
        supports_http=True,
        supports_stdio=True,
        http_url_key="url",  # {"type": "http", "url": "..."}
        env_in_config=True,
    ),
    skills=SkillSpec(dir_name="skills", file_name="SKILL.md", format="markdown"),
    hooks=HookSpec(
        config_path="settings.json",
        config_format="json",
        events=(
            "Notification",
            "PostToolUse",
            "PreCompact",
            "PreToolUse",
            "SessionEnd",
            "SessionStart",
            "Stop",
            "SubagentStart",
            "SubagentStop",
            "UserPromptSubmit",
        ),
    ),
    instructions=InstructionSpec(
        global_file="CLAUDE.md",
        project_file="CLAUDE.md",
        rules_dir="rules/",
    ),
    agents=AgentSpec(dir_name="agents", file_format="md"),
)
