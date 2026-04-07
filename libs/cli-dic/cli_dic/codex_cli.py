"""Codex CLI entry."""

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

CODEX_CLI = CLIEntry(
    name="codex-cli",
    binary="codex",
    display_name="Codex CLI",
    vendor="openai",
    config_dir="~/.codex/",
    install_command="npm install -g @openai/codex",
    exit_behavior=ExitBehavior(key_sequence="C-c", repeat=1),
    idle_prompt="›",
    processing_indicators=(),
    headless=HeadlessSpec(
        subcommand="exec",
        prompt_flag="",
        output_format_flag="--json",
        cwd_flag="--cd",
    ),
    auto_approve=AutoApprove(
        flag="--full-auto",
        aliases=("--yolo",),
    ),
    model_flag="--model",
    default_model="o4-mini",
    resume_subcommand="resume",
    known_version="0.118.0",
    prompt_pattern=re.compile(r"❯|›|>"),
    process_names=frozenset({"codex"}),
    # ── Configuration ecosystem ──
    mcp=MCPSpec(
        config_format="toml",
        config_path="config.toml",
        config_key="mcp_servers",
        supports_http=True,
        supports_stdio=True,
        http_url_key="url",  # [mcp_servers.name] url = "..."
        env_in_config=False,  # TOML cannot define env vars; use shell env
    ),
    skills=SkillSpec(dir_name="skills", file_name="SKILL.md", format="markdown"),
    hooks=HookSpec(
        config_path="config.toml",
        config_format="toml",
        events=("notify",),
    ),
    instructions=InstructionSpec(
        global_file="instructions.md",
        project_file="CODEX.md",
        rules_dir="rules/",
    ),
    agents=AgentSpec(dir_name="agents", file_format="toml"),
    # Codex uses sandbox policy, not tool whitelist in SKILL.md frontmatter.
    # Mapping kept for sync-config translation (empty = no equivalent).
    tool_names=ToolNameMap(
        read="read_file",
        write="write_file",
        edit="apply_diff",
        bash="shell",
        glob="",  # Codex 無對應
        grep="",  # Codex 無對應
        web_fetch="",
        web_search="web_search",
        agent="",
        notebook_edit="",
    ),
)
