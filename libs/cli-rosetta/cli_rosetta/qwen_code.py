"""Qwen Code CLI entry (Gemini CLI fork by Alibaba)."""

from __future__ import annotations

import re

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

QWEN_CODE = CLIEntry(
    name="qwen-code",
    binary="qwen",
    display_name="Qwen Code",
    vendor="alibaba",
    config_dir="~/.qwen/",
    install_command="brew install qwen-code",
    exit_behavior=ExitBehavior(key_sequence="C-c", repeat=2),
    idle_prompt="❯",
    processing_indicators=(),
    headless=HeadlessSpec(
        prompt_flag="-p",  # deprecated; positional preferred
        output_format_flag="--output-format",
        cwd_flag="",
    ),
    auto_approve=AutoApprove(
        flag="--approval-mode yolo",
        aliases=("-y", "--yolo"),
    ),
    model_flag="--model",
    default_model="coder-model",
    resume_flag="--resume",
    continue_flag="--continue",
    known_version="0.14.0",
    brew_package="qwen-code",
    prompt_pattern=re.compile(r"❯"),
    process_names=frozenset({"qwen"}),
    # ── Configuration ecosystem ──
    mcp=MCPSpec(
        config_format="json",
        config_path="settings.json",  # mcpServers key inside settings.json
        config_key="mcpServers",
        supports_http=True,
        supports_stdio=True,
        http_url_key="url",  # {"type": "http", "url": "..."}
        env_in_config=True,
    ),
    skills=SkillSpec(
        dir_name="skills",
        file_name="SKILL.md",
        format="markdown",
        search_paths=("~/.qwen/skills/",),
    ),
    hooks=HookSpec(
        config_path="settings.json",
        config_format="json",
        # Qwen Code hooks are CC-style (verified from source HookEventName enum)
        events=(
            "Notification",
            "PermissionRequest",
            "PostToolUse",
            "PostToolUseFailure",
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
        global_file="QWEN.md",  # ~/.qwen/QWEN.md
        project_file="QWEN.md",  # project root or .qwen/QWEN.md
        rules_dir="rules/",
    ),
    agents=AgentSpec(dir_name="agents", file_format="md"),
    # Qwen Code tool names (verified from source line 73433-73448)
    tool_names=ToolNameMap(
        read="read_file",
        write="write_file",
        edit="edit",  # NOT "edit_file" — Qwen uses plain "edit"
        bash="run_shell_command",
        glob="glob",  # NOT "glob_search" — Qwen uses plain "glob"
        grep="grep_search",
        web_fetch="web_fetch",
        web_search="web_search",
        agent="agent",  # Qwen HAS an agent tool
        notebook_edit="",
    ),
)
