"""Gemini CLI entry."""

from __future__ import annotations

import re

from cli_dic.base import AutoApprove, CLIEntry, ExitBehavior, HeadlessSpec

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
)
