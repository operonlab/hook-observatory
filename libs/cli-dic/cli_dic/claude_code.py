"""Claude Code CLI entry."""

from __future__ import annotations

import re

from cli_dic.base import AutoApprove, CLIEntry, ExitBehavior, HeadlessSpec

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
)
