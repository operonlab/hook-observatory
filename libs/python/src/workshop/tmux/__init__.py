"""workshop.tmux — reusable tmux control abstraction.

Tier 1 (primitives): raw tmux subprocess calls (sync + async)
Tier 2 (cli_session): interactive CLI lifecycle management
Tier 3 (patterns): CLI tool detection profiles
"""

from workshop.tmux.cli_session import (
    get_pane_command,
    get_pane_command_async,
    has_prompt,
    has_prompt_async,
    is_busy,
    is_busy_async,
    is_process_running,
    is_process_running_async,
    is_shell,
    is_shell_async,
    shutdown_cli,
    shutdown_cli_async,
    start_cli,
    start_cli_async,
    wait_for_prompt,
    wait_for_prompt_async,
    wait_for_text,
)
from workshop.tmux.patterns import (
    CLAUDE_CODE,
    CODEX_CLI,
    GEMINI_CLI,
    CLIProfile,
    get_profile,
    list_profiles,
    register_profile,
)
from workshop.tmux.primitives import (
    TmuxResult,
    capture,
    capture_async,
    display,
    display_async,
    send_enter,
    send_enter_async,
    send_text,
    send_text_async,
    tmux_check,
    tmux_check_async,
    tmux_ok,
    tmux_ok_async,
    tmux_run,
    tmux_run_async,
)

__all__ = [
    "TmuxResult",
    "tmux_run", "tmux_run_async",
    "tmux_check", "tmux_check_async",
    "tmux_ok", "tmux_ok_async",
    "capture", "capture_async",
    "display", "display_async",
    "send_text", "send_text_async",
    "send_enter", "send_enter_async",
    "get_pane_command", "get_pane_command_async",
    "is_shell", "is_shell_async",
    "is_process_running", "is_process_running_async",
    "is_busy", "is_busy_async",
    "has_prompt", "has_prompt_async",
    "wait_for_prompt", "wait_for_prompt_async",
    "wait_for_text",
    "start_cli", "start_cli_async",
    "shutdown_cli", "shutdown_cli_async",
    "CLIProfile", "CLAUDE_CODE", "GEMINI_CLI", "CODEX_CLI",
    "get_profile", "register_profile", "list_profiles",
]
