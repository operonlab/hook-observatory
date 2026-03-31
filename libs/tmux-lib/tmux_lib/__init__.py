"""tmux_lib — reusable tmux control abstraction.

Tier 1 (primitives): raw tmux subprocess calls (sync + async)
Tier 2 (cli_session): interactive CLI lifecycle management
Tier 3 (patterns): CLI tool detection profiles
Tier 4 (cc_reader): Claude Code JSONL + stability response reader
"""

from tmux_lib.cc_reader import (
    CCDelta,
    TOOL_NAME_LABEL,
    aiter_cc_response,
    extract_text_from_jsonl_entry,
    iter_cc_response,
    resolve_session_jsonl,
    strip_cc_noise,
    wait_stable,
    wait_stable_sync,
)
from tmux_lib.cli_session import (
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
from tmux_lib.patterns import (
    CLAUDE_CODE,
    CODEX_CLI,
    GEMINI_CLI,
    CLIProfile,
    get_profile,
    list_profiles,
    register_profile,
)
from tmux_lib.primitives import (
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
    # cc_reader (Tier 4)
    "CCDelta",
    "TOOL_NAME_LABEL",
    "resolve_session_jsonl",
    "extract_text_from_jsonl_entry",
    "strip_cc_noise",
    "wait_stable_sync",
    "wait_stable",
    "iter_cc_response",
    "aiter_cc_response",
    # primitives (Tier 1)
    "TmuxResult",
    "tmux_run", "tmux_run_async",
    "tmux_check", "tmux_check_async",
    "tmux_ok", "tmux_ok_async",
    "capture", "capture_async",
    "display", "display_async",
    "send_text", "send_text_async",
    "send_enter", "send_enter_async",
    # cli_session (Tier 2)
    "get_pane_command", "get_pane_command_async",
    "is_shell", "is_shell_async",
    "is_process_running", "is_process_running_async",
    "is_busy", "is_busy_async",
    "has_prompt", "has_prompt_async",
    "wait_for_prompt", "wait_for_prompt_async",
    "wait_for_text",
    "start_cli", "start_cli_async",
    "shutdown_cli", "shutdown_cli_async",
    # patterns (Tier 3)
    "CLIProfile", "CLAUDE_CODE", "GEMINI_CLI", "CODEX_CLI",
    "get_profile", "register_profile", "list_profiles",
]
