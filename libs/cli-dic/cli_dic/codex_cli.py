"""Codex CLI entry."""

from __future__ import annotations

import re

from cli_dic.base import AutoApprove, CLIEntry, ExitBehavior, HeadlessSpec

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
)
