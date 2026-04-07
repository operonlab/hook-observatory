"""CLI dictionary entry — declarative descriptor for a coding CLI tool.

Each CLIEntry is a frozen dataclass describing one CLI tool's commands,
flags, paths, and patterns. Minimal logic, mostly data.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExitBehavior:
    """How to exit the CLI's interactive mode."""

    command: str | None = None
    key_sequence: str | None = None
    repeat: int = 1
    needs_enter: bool = True


@dataclass(frozen=True)
class HeadlessSpec:
    """How to run this CLI in headless (non-interactive) mode."""

    subcommand: str = ""
    prompt_flag: str = "-p"
    output_format_flag: str = ""
    cwd_flag: str = ""
    env_unset: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoApprove:
    """How to skip all permission prompts."""

    flag: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CLIEntry:
    """Complete descriptor for a coding CLI tool."""

    # ── Identity ──
    name: str
    binary: str
    display_name: str
    vendor: str

    # ── Paths ──
    config_dir: str = ""
    install_command: str = ""

    # ── Interactive mode ──
    exit_behavior: ExitBehavior = field(default_factory=ExitBehavior)
    idle_prompt: str = "❯"
    processing_indicators: tuple[str, ...] = ()

    # ── Headless mode ──
    headless: HeadlessSpec = field(default_factory=HeadlessSpec)

    # ── Permissions ──
    auto_approve: AutoApprove = field(default_factory=AutoApprove)

    # ── Model selection ──
    model_flag: str = "--model"
    default_model: str = ""

    # ── Session resume ──
    resume_flag: str = ""
    resume_subcommand: str = ""
    continue_flag: str = ""

    # ── Version / health ──
    version_flag: str = "--version"
    version_pattern: str = r"\d+\.\d+\.\d+"
    known_version: str = ""

    # ── tmux detection bridge ──
    prompt_pattern: re.Pattern | None = None
    process_names: frozenset[str] = frozenset()

    # ── Convenience ──

    def headless_cmd(
        self,
        prompt: str,
        *,
        model: str | None = None,
        cwd: str | None = None,
        auto_approve: bool = False,
        output_format: str | None = None,
        extra_flags: list[str] | None = None,
    ) -> list[str]:
        """Build a headless command list."""
        cmd = [self.binary]

        if self.headless.subcommand:
            cmd.append(self.headless.subcommand)

        if auto_approve and self.auto_approve.flag:
            cmd.extend(shlex.split(self.auto_approve.flag))

        if model:
            cmd.extend([self.model_flag, model])

        if cwd and self.headless.cwd_flag:
            cmd.extend([self.headless.cwd_flag, cwd])

        if output_format and self.headless.output_format_flag:
            cmd.extend([self.headless.output_format_flag, output_format])

        if extra_flags:
            cmd.extend(extra_flags)

        if self.headless.prompt_flag:
            cmd.extend([self.headless.prompt_flag, prompt])
        else:
            cmd.append(prompt)

        return cmd

    def exit_description(self) -> str:
        """Human-readable exit instruction."""
        eb = self.exit_behavior
        if eb.command:
            return f"{eb.command} + Enter" if eb.needs_enter else eb.command
        if eb.key_sequence:
            suffix = f" × {eb.repeat}" if eb.repeat > 1 else ""
            return f"{eb.key_sequence}{suffix}"
        return "unknown"
