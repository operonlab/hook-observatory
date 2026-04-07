"""Gemini CLI entry."""

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
    ToolNameMap,
)

GEMINI_CLI = CLIEntry(
    name="gemini-cli",
    binary="gemini",
    display_name="Gemini CLI",
    vendor="google",
    config_dir="~/.gemini/",
    install_command="npm install -g @google/gemini-cli",
    exit_behavior=ExitBehavior(key_sequence="C-c", repeat=2),
    idle_prompt="*",
    processing_indicators=("✦",),
    headless=HeadlessSpec(
        prompt_flag="-p",
        output_format_flag="--output-format",
        cwd_flag="",
    ),
    auto_approve=AutoApprove(
        flag="--approval-mode yolo",
    ),
    model_flag="--model",
    default_model="gemini-2.5-flash",
    resume_flag="--session",
    known_version="0.36.0",
    prompt_pattern=re.compile(r"❯"),
    process_names=frozenset({"gemini"}),
    # ── Configuration ecosystem ──
    mcp=MCPSpec(
        config_format="json",
        config_path="settings.json",
        config_key="mcpServers",
        supports_http=True,
        supports_stdio=True,
        http_url_key="httpUrl",  # {"httpUrl": "..."} (different from CC's "url")
        env_in_config=True,
    ),
    skills=SkillSpec(
        dir_name="skills",
        file_name="SKILL.md",
        format="markdown",
        search_paths=("~/.agents/skills/", "~/.gemini/skills/"),  # .agents/ takes priority
    ),
    hooks=HookSpec(
        config_path="settings.json",
        config_format="json",
        events=(
            "AfterAgent",
            "AfterTool",
            "BeforeAgent",
            "BeforeTool",
            "Notification",
            "PreCompress",
            "SessionEnd",
            "SessionStart",
        ),
    ),
    instructions=InstructionSpec(
        global_file="GEMINI.md",
        project_file="GEMINI.md",
        rules_dir="",
    ),
    agents=AgentSpec(dir_name="agents", file_format="md"),
    tool_names=ToolNameMap(
        read="read_file",
        write="write_file",
        edit="edit_file",
        bash="run_shell_command",
        glob="glob_search",
        grep="grep_search",
        web_fetch="web_fetch",
        web_search="web_search",
        agent="",  # Gemini 無對應
        notebook_edit="",
    ),
)
