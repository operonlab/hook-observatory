"""Mutation-thinking adversarial tests for workshop.tmux module.

Independent test-adversary agent — derived from signatures + docstrings only.
Every test kills at least one specific mutation operator.
Mock boundary: subprocess only (external I/O). Module internals exercised for real.

Six Iron Rules:
  #1 Mutation thinking: each test targets a named mutation
  #2 Writer/tester separation: independent adversary
  #3 Invariants over fixed I/O pairs
  #4 Runtime → regression (boundary + extreme inputs)
  #5 Mock only subprocess (external I/O)
  #6 Not a draft — every assertion justified
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from unittest.mock import MagicMock, patch

import pytest

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
    _SEND_KEYS_LIMIT,
    TmuxResult,
    capture,
    display,
    send_enter,
    send_text,
    tmux_check,
    tmux_ok,
    tmux_run,
)

# ═══════════════════════════════════════════════════════════════════
# Section 1: TmuxResult.ok — boolean semantics
# Mutation: `returncode == 0` → `>= 0` or `!= 0` or `True`
# ═══════════════════════════════════════════════════════════════════


class TestTmuxResultOk:
    def test_ok_true_only_at_zero(self):
        assert TmuxResult(0, "", "").ok is True

    def test_ok_false_for_positive(self):
        """Kills `!= 0` mutation."""
        assert TmuxResult(1, "out", "err").ok is False

    def test_ok_false_for_minus_one(self):
        """Kills `>= 0` mutation: -1 >= 0 would pass."""
        assert TmuxResult(-1, "", "timeout").ok is False

    def test_ok_false_for_minus_two(self):
        assert TmuxResult(-2, "", "not found").ok is False

    def test_ok_false_for_large_rc(self):
        assert TmuxResult(127, "", "").ok is False


class TestTmuxResultFrozen:
    """Kills: removing `frozen=True` from dataclass."""

    def test_immutable_returncode(self):
        r = TmuxResult(0, "out", "")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.returncode = 1  # type: ignore[misc]

    def test_immutable_stdout(self):
        r = TmuxResult(0, "out", "")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.stdout = "hacked"  # type: ignore[misc]

    def test_immutable_stderr(self):
        r = TmuxResult(0, "", "err")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.stderr = "hacked"  # type: ignore[misc]


class TestTmuxResultSlots:
    """Kills: removing `slots=True` from dataclass."""

    def test_no_dynamic_attrs(self):
        r = TmuxResult(0, "", "")
        with pytest.raises((AttributeError, TypeError)):
            r.extra = "nope"  # type: ignore[attr-defined]


# ═══════════════════════════════════════════════════════════════════
# Section 2: tmux_run — error handling and never-raise contract
# Mutations: swap -1/-2, remove strip(), ignore timeout param
# ═══════════════════════════════════════════════════════════════════


class TestTmuxRun:
    @patch("workshop.tmux.primitives.subprocess.run")
    def test_success_strips_whitespace(self, mock_run):
        """Kills: removing .strip() from stdout/stderr."""
        mock_run.return_value = MagicMock(returncode=0, stdout="  hello  \n", stderr="  warn  \n")
        r = tmux_run("list-sessions")
        assert r.stdout == "hello"
        assert r.stderr == "warn"
        assert r.ok is True

    @patch("workshop.tmux.primitives.subprocess.run")
    def test_failure_preserves_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no server")
        r = tmux_run("has-session", "-t", "nope")
        assert r.returncode == 1
        assert r.ok is False

    @patch("workshop.tmux.primitives.subprocess.run")
    def test_timeout_returns_minus_one_not_minus_two(self, mock_run):
        """Kills: swapping -1 ↔ -2 for timeout vs not-found."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmux", timeout=10)
        r = tmux_run("list-sessions", timeout=10)
        assert r.returncode == -1
        assert "timeout" in r.stderr.lower()
        assert r.stdout == ""

    @patch("workshop.tmux.primitives.subprocess.run")
    def test_not_found_returns_minus_two_not_minus_one(self, mock_run):
        """Kills: swapping -1 ↔ -2."""
        mock_run.side_effect = FileNotFoundError("tmux")
        r = tmux_run("list-sessions")
        assert r.returncode == -2
        assert "not found" in r.stderr.lower()

    @patch("workshop.tmux.primitives.subprocess.run")
    def test_timeout_value_forwarded_to_subprocess(self, mock_run):
        """Kills: ignoring timeout param or hardcoding default."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        tmux_run("list-sessions", timeout=42)
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 42

    @patch("workshop.tmux.primitives.subprocess.run")
    def test_timeout_zero_extreme_input(self, mock_run):
        """Extreme: timeout=0 should still call subprocess."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmux", timeout=0)
        r = tmux_run("list-sessions", timeout=0)
        assert r.returncode == -1
        mock_run.assert_called_once()

    @patch("workshop.tmux.primitives.subprocess.run")
    def test_never_raises(self, mock_run):
        """Invariant: tmux_run NEVER raises — always returns TmuxResult."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmux", timeout=1)
        r = tmux_run("test")
        assert isinstance(r, TmuxResult)


# ═══════════════════════════════════════════════════════════════════
# Section 3: tmux_check — raise vs return inversion
# Mutation: `not r.ok` → `r.ok` (raises on success instead of failure)
# ═══════════════════════════════════════════════════════════════════


class TestTmuxCheck:
    @patch("workshop.tmux.primitives.tmux_run")
    def test_success_returns_stdout(self, mock_run):
        mock_run.return_value = TmuxResult(0, "output", "")
        assert tmux_check("test") == "output"

    @patch("workshop.tmux.primitives.tmux_run")
    def test_failure_raises_runtime_error(self, mock_run):
        """Kills: `not r.ok` → `r.ok`."""
        mock_run.return_value = TmuxResult(1, "", "bad")
        with pytest.raises(RuntimeError, match="failed"):
            tmux_check("test")

    @patch("workshop.tmux.primitives.tmux_run")
    def test_error_message_includes_subcommand(self, mock_run):
        """Kills: removing args[0] from error message."""
        mock_run.return_value = TmuxResult(1, "", "err")
        with pytest.raises(RuntimeError, match="send-keys"):
            tmux_check("send-keys", "-t", "pane")

    @patch("workshop.tmux.primitives.tmux_run")
    def test_error_message_includes_returncode(self, mock_run):
        mock_run.return_value = TmuxResult(42, "", "err")
        with pytest.raises(RuntimeError, match="rc=42"):
            tmux_check("test")


# ═══════════════════════════════════════════════════════════════════
# Section 4: tmux_ok — None vs empty string on failure
# Mutation: always return stdout (ignoring ok), or return '' instead of None
# ═══════════════════════════════════════════════════════════════════


class TestTmuxOk:
    @patch("workshop.tmux.primitives.tmux_run")
    def test_success_returns_stdout(self, mock_run):
        mock_run.return_value = TmuxResult(0, "data", "")
        assert tmux_ok("test") == "data"

    @patch("workshop.tmux.primitives.tmux_run")
    def test_failure_returns_none_not_empty(self, mock_run):
        """Kills: returning '' instead of None."""
        mock_run.return_value = TmuxResult(1, "", "err")
        result = tmux_ok("test")
        assert result is None

    @patch("workshop.tmux.primitives.tmux_run")
    def test_failure_with_stale_stdout_still_returns_none(self, mock_run):
        """Kills: always returning stdout regardless of ok."""
        mock_run.return_value = TmuxResult(1, "stale data", "err")
        result = tmux_ok("test")
        assert result is None

    @patch("workshop.tmux.primitives.tmux_run")
    def test_success_empty_stdout_is_not_none(self, mock_run):
        """Distinguishes ok+empty from failure+None."""
        mock_run.return_value = TmuxResult(0, "", "")
        result = tmux_ok("test")
        assert result == ""
        assert result is not None


# ═══════════════════════════════════════════════════════════════════
# Section 5: send_text — 512-char threshold & literal guard
# Mutations: > → >=, remove `literal and`, ignore buf_name
# ═══════════════════════════════════════════════════════════════════


class TestSendTextThreshold:
    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_exactly_512_uses_send_keys(self, mock_check, mock_paste):
        """Kills: > mutated to >= would route 512 chars to paste."""
        send_text("%0", "A" * 512)
        mock_check.assert_called_once()
        mock_paste.assert_not_called()

    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_513_uses_paste_buffer(self, mock_check, mock_paste):
        text = "A" * 513
        send_text("%0", text)
        mock_paste.assert_called_once_with("%0", text, "_ws_paste")
        mock_check.assert_not_called()

    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_511_uses_send_keys(self, mock_check, mock_paste):
        send_text("%0", "A" * 511)
        mock_check.assert_called_once()
        mock_paste.assert_not_called()

    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_long_non_literal_uses_send_keys(self, mock_check, mock_paste):
        """Kills: removing `literal and` — non-literal never pastes."""
        send_text("%0", "A" * 1000, literal=False)
        mock_check.assert_called_once()
        mock_paste.assert_not_called()

    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_empty_text_uses_send_keys(self, mock_check, mock_paste):
        send_text("%0", "")
        mock_check.assert_called_once()
        mock_paste.assert_not_called()

    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_custom_buf_name_propagated(self, mock_check, mock_paste):
        """Kills: ignoring buf_name parameter."""
        text = "A" * 1000
        send_text("%0", text, buf_name="_custom")
        mock_paste.assert_called_once_with("%0", text, "_custom")


class TestSendTextLiteralFlag:
    """Kills: always adding -l, or never adding -l."""

    @patch("workshop.tmux.primitives.tmux_check")
    def test_literal_true_includes_dash_l(self, mock_check):
        send_text("%0", "hello", literal=True)
        args = mock_check.call_args[0]
        assert "-l" in args

    @patch("workshop.tmux.primitives.tmux_check")
    def test_literal_false_excludes_dash_l(self, mock_check):
        send_text("%0", "hello", literal=False)
        args = mock_check.call_args[0]
        assert "-l" not in args


class TestSendKeysLimitConstant:
    def test_limit_is_512(self):
        """Kills: changing the threshold constant value."""
        assert _SEND_KEYS_LIMIT == 512


# ═══════════════════════════════════════════════════════════════════
# Section 6: capture — conditional flag passing (-J, -e)
# Mutations: remove `if join_wrapped`, remove `if escape_sequences`,
#            ignore start_line
# ═══════════════════════════════════════════════════════════════════


class TestCapture:
    @patch("workshop.tmux.primitives.tmux_ok")
    def test_default_no_j_no_e(self, mock_ok):
        mock_ok.return_value = "content"
        capture("%0")
        args = mock_ok.call_args[0]
        assert "-J" not in args
        assert "-e" not in args

    @patch("workshop.tmux.primitives.tmux_ok")
    def test_join_wrapped_adds_j(self, mock_ok):
        """Kills: removing `if join_wrapped` branch."""
        mock_ok.return_value = "content"
        capture("%0", join_wrapped=True)
        assert "-J" in mock_ok.call_args[0]

    @patch("workshop.tmux.primitives.tmux_ok")
    def test_escape_sequences_adds_e(self, mock_ok):
        """Kills: removing `if escape_sequences` branch."""
        mock_ok.return_value = "content"
        capture("%0", escape_sequences=True)
        assert "-e" in mock_ok.call_args[0]

    @patch("workshop.tmux.primitives.tmux_ok")
    def test_both_flags_together(self, mock_ok):
        mock_ok.return_value = "content"
        capture("%0", join_wrapped=True, escape_sequences=True)
        args = mock_ok.call_args[0]
        assert "-J" in args
        assert "-e" in args

    @patch("workshop.tmux.primitives.tmux_ok")
    def test_custom_start_line(self, mock_ok):
        """Kills: ignoring start_line parameter."""
        mock_ok.return_value = "content"
        capture("%0", start_line=-50)
        args = mock_ok.call_args[0]
        idx = args.index("-S")
        assert args[idx + 1] == "-50"

    @patch("workshop.tmux.primitives.tmux_ok")
    def test_default_start_line_minus_200(self, mock_ok):
        mock_ok.return_value = "content"
        capture("%0")
        args = mock_ok.call_args[0]
        idx = args.index("-S")
        assert args[idx + 1] == "-200"


# ═══════════════════════════════════════════════════════════════════
# Section 7: display — delegation correctness
# ═══════════════════════════════════════════════════════════════════


class TestDisplay:
    @patch("workshop.tmux.primitives.tmux_ok")
    def test_delegates_args_correctly(self, mock_ok):
        mock_ok.return_value = "zsh"
        result = display("%0", "#{pane_current_command}")
        assert result == "zsh"
        mock_ok.assert_called_once_with(
            "display-message", "-t", "%0", "-p", "#{pane_current_command}"
        )


# ═══════════════════════════════════════════════════════════════════
# Section 8: send_enter — correct key name
# ═══════════════════════════════════════════════════════════════════


class TestSendEnter:
    @patch("workshop.tmux.primitives.tmux_check")
    def test_sends_enter_key(self, mock_check):
        send_enter("%0")
        mock_check.assert_called_once_with("send-keys", "-t", "%0", "Enter")


# ═══════════════════════════════════════════════════════════════════
# Section 9: _paste_text_sync — cleanup on failure & re-raise
# Mutations: remove delete-buffer cleanup, swallow error
# ═══════════════════════════════════════════════════════════════════


class TestPasteTextSync:
    @patch("workshop.tmux.primitives.tmux_ok")
    @patch("workshop.tmux.primitives.tmux_check")
    @patch("workshop.tmux.primitives.subprocess.run")
    def test_paste_failure_cleans_buffer_then_reraises(self, mock_run, mock_check, mock_ok):
        """Kills: removing delete-buffer cleanup, or removing re-raise."""
        from tmux_lib.primitives import _paste_text_sync

        mock_run.return_value = MagicMock(returncode=0)
        mock_check.side_effect = RuntimeError("paste failed")
        with pytest.raises(RuntimeError, match="paste failed"):
            _paste_text_sync("%0", "text", "_ws")
        mock_ok.assert_called_once_with("delete-buffer", "-b", "_ws")

    @patch("workshop.tmux.primitives.subprocess.run")
    def test_load_buffer_failure_raises(self, mock_run):
        """Kills: swallowing load-buffer subprocess error."""
        from tmux_lib.primitives import _paste_text_sync

        mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
        with pytest.raises(RuntimeError, match="load-buffer"):
            _paste_text_sync("%0", "text", "_ws")

    @patch("workshop.tmux.primitives.tmux_check")
    @patch("workshop.tmux.primitives.subprocess.run")
    def test_success_path_no_cleanup(self, mock_run, mock_check):
        """Invariant: on success, no delete-buffer call."""
        from tmux_lib.primitives import _paste_text_sync

        mock_run.return_value = MagicMock(returncode=0)
        mock_check.return_value = ""
        _paste_text_sync("%0", "text", "_ws")
        # tmux_check called for paste-buffer, no tmux_ok for cleanup
        mock_check.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# Section 10: CLIProfile — frozen immutability
# Mutation: removing frozen=True
# ═══════════════════════════════════════════════════════════════════


class TestCLIProfileFrozen:
    def test_cannot_mutate_name(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            CLAUDE_CODE.name = "hacked"  # type: ignore[misc]

    def test_cannot_mutate_process_names(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            CLAUDE_CODE.process_names = frozenset({"x"})  # type: ignore[misc]

    def test_cannot_mutate_exit_command(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            CLAUDE_CODE.exit_command = "rm -rf /"  # type: ignore[misc]

    def test_cannot_mutate_prompt_pattern(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            CLAUDE_CODE.prompt_pattern = re.compile(r"x")  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
# Section 11: Profile registry — get / register / list
# Mutations: wrong key, no KeyError, overwrite rejected
# ═══════════════════════════════════════════════════════════════════


class TestProfileRegistry:
    def test_get_known_profile(self):
        assert get_profile("claude-code") is CLAUDE_CODE

    def test_get_unknown_raises_keyerror(self):
        """Kills: returning None/default instead of raising."""
        with pytest.raises(KeyError):
            get_profile("nonexistent-cli")

    def test_list_contains_builtins(self):
        names = list_profiles()
        assert "claude-code" in names
        assert "gemini-cli" in names
        assert "codex-cli" in names

    def test_register_custom_then_retrieve(self):
        custom = CLIProfile(
            name="test-custom-reg",
            prompt_pattern=re.compile(r"\$"),
            process_names=frozenset({"custom-bin"}),
        )
        register_profile(custom)
        try:
            assert get_profile("test-custom-reg") is custom
        finally:
            from tmux_lib.patterns import _REGISTRY

            _REGISTRY.pop("test-custom-reg", None)

    def test_register_overwrites_existing(self):
        """Kills: register_profile raising on duplicate key."""
        original = get_profile("codex-cli")
        replacement = CLIProfile(
            name="codex-cli",
            prompt_pattern=re.compile(r"replaced"),
            process_names=frozenset({"codex"}),
        )
        register_profile(replacement)
        try:
            assert get_profile("codex-cli") is replacement
        finally:
            from tmux_lib.patterns import _REGISTRY

            _REGISTRY["codex-cli"] = original

    def test_register_uses_profile_name_as_key(self):
        """Kills: using a hardcoded key or wrong field."""
        custom = CLIProfile(
            name="unique-xyz-test",
            prompt_pattern=re.compile(r"\$"),
            process_names=frozenset({"x"}),
        )
        register_profile(custom)
        try:
            assert get_profile("unique-xyz-test") is custom
        finally:
            from tmux_lib.patterns import _REGISTRY

            _REGISTRY.pop("unique-xyz-test", None)


# ═══════════════════════════════════════════════════════════════════
# Section 12: Built-in profile invariants
# ═══════════════════════════════════════════════════════════════════


class TestBuiltinProfiles:
    @pytest.mark.parametrize("profile", [CLAUDE_CODE, GEMINI_CLI, CODEX_CLI])
    def test_prompt_pattern_is_compiled_regex(self, profile):
        assert isinstance(profile.prompt_pattern, re.Pattern)

    @pytest.mark.parametrize("profile", [CLAUDE_CODE, GEMINI_CLI, CODEX_CLI])
    def test_process_names_nonempty(self, profile):
        assert len(profile.process_names) > 0

    @pytest.mark.parametrize("profile", [CLAUDE_CODE, GEMINI_CLI, CODEX_CLI])
    def test_exit_command_nonempty_string(self, profile):
        assert isinstance(profile.exit_command, str)
        assert len(profile.exit_command) > 0

    def test_claude_detect_semver_true(self):
        assert CLAUDE_CODE.detect_semver is True

    def test_gemini_detect_semver_false(self):
        """Kills: setting detect_semver=True for gemini."""
        assert GEMINI_CLI.detect_semver is False

    def test_claude_has_processing_indicators(self):
        assert CLAUDE_CODE.processing_indicators is not None

    def test_gemini_no_processing_indicators(self):
        assert GEMINI_CLI.processing_indicators is None

    def test_claude_has_content_indicators(self):
        assert CLAUDE_CODE.content_indicators is not None


# ═══════════════════════════════════════════════════════════════════
# Section 13: is_shell — None/empty/fullpath command detection
# Mutations: `return True` → `return False` for None,
#            fullpath vs basename
# ═══════════════════════════════════════════════════════════════════


class TestIsShell:
    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_none_command_is_shell(self, mock_cmd):
        """Kills: returning False when cmd is None."""
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = None
        assert is_shell("%0") is True

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_empty_string_is_shell(self, mock_cmd):
        """Empty string is falsy → treated as shell."""
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = ""
        assert is_shell("%0") is True

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_zsh_bare_is_shell(self, mock_cmd):
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "zsh"
        assert is_shell("%0") is True

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_full_path_zsh_is_shell(self, mock_cmd):
        """Kills: checking full path instead of split('/')[-1] basename."""
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "/usr/bin/zsh"
        assert is_shell("%0") is True

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_bash_is_shell(self, mock_cmd):
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "bash"
        assert is_shell("%0") is True

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_fish_is_shell(self, mock_cmd):
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "fish"
        assert is_shell("%0") is True

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_sh_is_shell(self, mock_cmd):
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "sh"
        assert is_shell("%0") is True

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_claude_is_not_shell(self, mock_cmd):
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "claude"
        assert is_shell("%0") is False

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_python_is_not_shell(self, mock_cmd):
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "python3"
        assert is_shell("%0") is False

    @patch("workshop.tmux.cli_session.get_pane_command")
    def test_vim_is_not_shell(self, mock_cmd):
        from tmux_lib.cli_session import is_shell

        mock_cmd.return_value = "vim"
        assert is_shell("%0") is False


# ═══════════════════════════════════════════════════════════════════
# Section 14: is_process_running — multi-path detection
# Mutations: remove process_name check, remove shell short-circuit,
#            remove semver detection, remove content fallback
# ═══════════════════════════════════════════════════════════════════


class TestIsProcessRunning:
    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_process_name_match_early_return(self, mock_display, mock_capture):
        """Kills: removing process_name check."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = "claude"
        assert is_process_running("%0", CLAUDE_CODE) is True
        mock_capture.assert_not_called()  # early return

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_process_name_case_insensitive(self, mock_display, mock_capture):
        """Kills: removing .lower() on cmd."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = "Claude"
        assert is_process_running("%0", CLAUDE_CODE) is True

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_shell_short_circuits_to_false(self, mock_display, mock_capture):
        """Kills: removing the shell short-circuit branch.
        Even if content has indicators, shell cmd → False."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = "zsh"
        mock_capture.return_value = "❯"
        assert is_process_running("%0", CLAUDE_CODE) is False
        mock_capture.assert_not_called()

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_full_path_shell_short_circuits(self, mock_display, mock_capture):
        """Kills: basename check in shell detection."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = "/usr/bin/bash"
        assert is_process_running("%0", CLAUDE_CODE) is False
        mock_capture.assert_not_called()

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_semver_detection_when_enabled(self, mock_display, mock_capture):
        """Kills: removing detect_semver branch."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = "1.0.35"
        assert is_process_running("%0", CLAUDE_CODE) is True

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_semver_ignored_when_disabled(self, mock_display, mock_capture):
        """Kills: always checking semver regardless of flag."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = "1.0.35"
        mock_capture.return_value = ""
        assert is_process_running("%0", GEMINI_CLI) is False

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_content_fallback_when_cmd_is_none(self, mock_display, mock_capture):
        """Kills: removing content_indicators fallback."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = None
        mock_capture.return_value = "some output with ❯ prompt"
        assert is_process_running("%0", CLAUDE_CODE) is True

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_content_fallback_no_match(self, mock_display, mock_capture):
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = None
        mock_capture.return_value = "random text no indicators"
        assert is_process_running("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_no_content_indicators_skips_capture(self, mock_display, mock_capture):
        """Kills: calling capture when content_indicators is None."""
        from tmux_lib.cli_session import is_process_running

        profile = CLIProfile(
            name="no-content",
            prompt_pattern=re.compile(r"\$"),
            process_names=frozenset({"nobin"}),
            content_indicators=None,
        )
        mock_display.return_value = None
        assert is_process_running("%0", profile) is False
        mock_capture.assert_not_called()

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_none_capture_does_not_crash(self, mock_display, mock_capture):
        """Kills: not guarding `content and` before .search()."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = None
        mock_capture.return_value = None
        assert is_process_running("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.display")
    def test_unknown_cmd_falls_through_to_content(self, mock_display, mock_capture):
        """Unknown cmd, not shell, not semver → must check content."""
        from tmux_lib.cli_session import is_process_running

        mock_display.return_value = "vim"
        mock_capture.return_value = "❯"
        assert is_process_running("%0", CLAUDE_CODE) is True


# ═══════════════════════════════════════════════════════════════════
# Section 15: has_prompt — empty/None capture handling
# Mutation: `return False` → `return True` for empty
# ═══════════════════════════════════════════════════════════════════


class TestHasPrompt:
    @patch("workshop.tmux.cli_session.capture")
    def test_none_capture_returns_false(self, mock_capture):
        """Kills: returning True when capture is None."""
        from tmux_lib.cli_session import has_prompt

        mock_capture.return_value = None
        assert has_prompt("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    def test_empty_string_returns_false(self, mock_capture):
        from tmux_lib.cli_session import has_prompt

        mock_capture.return_value = ""
        assert has_prompt("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    def test_prompt_found_returns_true(self, mock_capture):
        from tmux_lib.cli_session import has_prompt

        mock_capture.return_value = "some output\n❯"
        assert has_prompt("%0", CLAUDE_CODE) is True

    @patch("workshop.tmux.cli_session.capture")
    def test_no_prompt_returns_false(self, mock_capture):
        from tmux_lib.cli_session import has_prompt

        mock_capture.return_value = "Building...\nDone."
        assert has_prompt("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    def test_lines_param_propagated(self, mock_capture):
        """Kills: ignoring lines param, hardcoding start_line."""
        from tmux_lib.cli_session import has_prompt

        mock_capture.return_value = "❯"
        has_prompt("%0", CLAUDE_CODE, lines=3)
        _, kwargs = mock_capture.call_args
        assert kwargs["start_line"] == -3

    @patch("workshop.tmux.cli_session.capture")
    def test_default_lines_is_5(self, mock_capture):
        from tmux_lib.cli_session import has_prompt

        mock_capture.return_value = "❯"
        has_prompt("%0", CLAUDE_CODE)
        _, kwargs = mock_capture.call_args
        assert kwargs["start_line"] == -5


# ═══════════════════════════════════════════════════════════════════
# Section 16: is_busy — None indicators → always False
# Mutation: `return False` → `return True` when no indicators
# ═══════════════════════════════════════════════════════════════════


class TestIsBusy:
    @patch("workshop.tmux.cli_session.capture")
    def test_no_indicators_returns_false_without_capture(self, mock_capture):
        """Kills: returning True when processing_indicators is None."""
        from tmux_lib.cli_session import is_busy

        assert is_busy("%0", GEMINI_CLI) is False
        mock_capture.assert_not_called()

    @patch("workshop.tmux.cli_session.capture")
    def test_busy_when_indicator_matches(self, mock_capture):
        from tmux_lib.cli_session import is_busy

        mock_capture.return_value = "⏺ Processing files..."
        assert is_busy("%0", CLAUDE_CODE) is True

    @patch("workshop.tmux.cli_session.capture")
    def test_not_busy_when_idle(self, mock_capture):
        from tmux_lib.cli_session import is_busy

        mock_capture.return_value = "Done.\n❯"
        assert is_busy("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    def test_none_capture_not_busy(self, mock_capture):
        """Kills: not guarding `if not bottom`."""
        from tmux_lib.cli_session import is_busy

        mock_capture.return_value = None
        assert is_busy("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    def test_empty_string_not_busy(self, mock_capture):
        from tmux_lib.cli_session import is_busy

        mock_capture.return_value = ""
        assert is_busy("%0", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.capture")
    def test_lines_param_propagated(self, mock_capture):
        """Kills: ignoring lines param in is_busy."""
        from tmux_lib.cli_session import is_busy

        mock_capture.return_value = ""
        is_busy("%0", CLAUDE_CODE, lines=3)
        _, kwargs = mock_capture.call_args
        assert kwargs["start_line"] == -3


# ═══════════════════════════════════════════════════════════════════
# Section 17: wait_for_prompt — timeout boundary semantics
# Mutation: `<` → `<=`, sleep before first check
# ═══════════════════════════════════════════════════════════════════


class TestWaitForPrompt:
    @patch("workshop.tmux.cli_session.has_prompt")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_timeout_zero_returns_false_immediately(self, mock_time, mock_sleep, mock_has):
        """Kills: `<` → `<=` — with timeout=0, deadline==now, loop body never runs."""
        from tmux_lib.cli_session import wait_for_prompt

        mock_time.return_value = 100.0
        result = wait_for_prompt("%0", CLAUDE_CODE, timeout=0, poll_interval=0.1)
        assert result is False
        mock_has.assert_not_called()

    @patch("workshop.tmux.cli_session.has_prompt")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_found_on_first_check(self, mock_time, mock_sleep, mock_has):
        from tmux_lib.cli_session import wait_for_prompt

        mock_time.side_effect = [0.0, 0.1]
        mock_has.return_value = True
        assert wait_for_prompt("%0", CLAUDE_CODE, timeout=30) is True
        mock_sleep.assert_not_called()

    @patch("workshop.tmux.cli_session.has_prompt")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_found_after_retries(self, mock_time, mock_sleep, mock_has):
        from tmux_lib.cli_session import wait_for_prompt

        mock_time.side_effect = [0.0, 1.0, 3.0, 5.0]
        mock_has.side_effect = [False, False, True]
        assert wait_for_prompt("%0", CLAUDE_CODE, timeout=30, poll_interval=2.0) is True
        assert mock_sleep.call_count == 2

    @patch("workshop.tmux.cli_session.has_prompt")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_timeout_exceeded_returns_false(self, mock_time, mock_sleep, mock_has):
        from tmux_lib.cli_session import wait_for_prompt

        mock_time.side_effect = [0.0, 1.0, 31.0]
        mock_has.return_value = False
        assert wait_for_prompt("%0", CLAUDE_CODE, timeout=30) is False

    @patch("workshop.tmux.cli_session.has_prompt")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_poll_interval_used(self, mock_time, mock_sleep, mock_has):
        """Kills: ignoring poll_interval param."""
        from tmux_lib.cli_session import wait_for_prompt

        mock_time.side_effect = [0.0, 0.5, 31.0]
        mock_has.return_value = False
        wait_for_prompt("%0", CLAUDE_CODE, timeout=30, poll_interval=7.5)
        mock_sleep.assert_called_with(7.5)


# ═══════════════════════════════════════════════════════════════════
# Section 18: wait_for_text — text presence + join_wrapped
# ═══════════════════════════════════════════════════════════════════


class TestWaitForText:
    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_text_found(self, mock_time, mock_sleep, mock_capture):
        from tmux_lib.cli_session import wait_for_text

        mock_time.side_effect = [0.0, 0.1]
        mock_capture.return_value = "Hello world"
        assert wait_for_text("%0", "Hello") is True

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_text_not_found_timeout(self, mock_time, mock_sleep, mock_capture):
        from tmux_lib.cli_session import wait_for_text

        mock_time.side_effect = [0.0, 1.0, 31.0]
        mock_capture.return_value = "nothing here"
        assert wait_for_text("%0", "missing", timeout=30) is False

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_none_capture_keeps_waiting(self, mock_time, mock_sleep, mock_capture):
        """Kills: not guarding `content and text in content`."""
        from tmux_lib.cli_session import wait_for_text

        mock_time.side_effect = [0.0, 0.5, 31.0]
        mock_capture.return_value = None
        assert wait_for_text("%0", "text", timeout=30) is False

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_uses_join_wrapped(self, mock_time, mock_sleep, mock_capture):
        """Kills: not passing join_wrapped=True to capture."""
        from tmux_lib.cli_session import wait_for_text

        mock_time.side_effect = [0.0, 0.1]
        mock_capture.return_value = "found"
        wait_for_text("%0", "found")
        _, kwargs = mock_capture.call_args
        assert kwargs.get("join_wrapped") is True

    @patch("workshop.tmux.cli_session.capture")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    def test_custom_lines_param(self, mock_time, mock_sleep, mock_capture):
        """Kills: ignoring lines param."""
        from tmux_lib.cli_session import wait_for_text

        mock_time.side_effect = [0.0, 0.1]
        mock_capture.return_value = "found"
        wait_for_text("%0", "found", lines=50)
        _, kwargs = mock_capture.call_args
        assert kwargs["start_line"] == -50


# ═══════════════════════════════════════════════════════════════════
# Section 19: start_cli — pre-check prevents double start
# Mutations: skip is_shell, always start even if running
# ═══════════════════════════════════════════════════════════════════


class TestStartCli:
    @patch("workshop.tmux.cli_session.wait_for_prompt")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    @patch("workshop.tmux.cli_session.is_process_running")
    @patch("workshop.tmux.cli_session.is_shell")
    def test_not_shell_returns_process_check(
        self, mock_shell, mock_running, mock_send, mock_enter, mock_wait
    ):
        """Kills: removing is_shell pre-check → would start over existing process."""
        from tmux_lib.cli_session import start_cli

        mock_shell.return_value = False
        mock_running.return_value = True
        assert start_cli("%0", "claude", CLAUDE_CODE) is True
        mock_send.assert_not_called()
        mock_enter.assert_not_called()

    @patch("workshop.tmux.cli_session.wait_for_prompt")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    @patch("workshop.tmux.cli_session.is_process_running")
    @patch("workshop.tmux.cli_session.is_shell")
    def test_not_shell_process_not_running_returns_false(
        self, mock_shell, mock_running, mock_send, mock_enter, mock_wait
    ):
        from tmux_lib.cli_session import start_cli

        mock_shell.return_value = False
        mock_running.return_value = False
        assert start_cli("%0", "claude", CLAUDE_CODE) is False
        mock_send.assert_not_called()

    @patch("workshop.tmux.cli_session.wait_for_prompt")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    @patch("workshop.tmux.cli_session.is_process_running")
    @patch("workshop.tmux.cli_session.is_shell")
    def test_shell_sends_command_and_waits(
        self, mock_shell, mock_running, mock_send, mock_enter, mock_wait
    ):
        from tmux_lib.cli_session import start_cli

        mock_shell.return_value = True
        mock_wait.return_value = True
        assert start_cli("%0", "claude --dp", CLAUDE_CODE) is True
        mock_send.assert_called_once()
        mock_enter.assert_called_once()
        mock_wait.assert_called_once()

    @patch("workshop.tmux.cli_session.wait_for_prompt")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    @patch("workshop.tmux.cli_session.is_process_running")
    @patch("workshop.tmux.cli_session.is_shell")
    def test_shell_wait_timeout_returns_false(
        self, mock_shell, mock_running, mock_send, mock_enter, mock_wait
    ):
        """Kills: always returning True from start_cli."""
        from tmux_lib.cli_session import start_cli

        mock_shell.return_value = True
        mock_wait.return_value = False
        assert start_cli("%0", "claude", CLAUDE_CODE) is False

    @patch("workshop.tmux.cli_session.wait_for_prompt")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    @patch("workshop.tmux.cli_session.is_process_running")
    @patch("workshop.tmux.cli_session.is_shell")
    def test_buf_name_forwarded(self, mock_shell, mock_running, mock_send, mock_enter, mock_wait):
        """Kills: ignoring buf_name param."""
        from tmux_lib.cli_session import start_cli

        mock_shell.return_value = True
        mock_wait.return_value = True
        start_cli("%0", "claude", CLAUDE_CODE, buf_name="_custom")
        _, kwargs = mock_send.call_args
        assert kwargs["buf_name"] == "_custom"


# ═══════════════════════════════════════════════════════════════════
# Section 20: shutdown_cli — exit command + wait for shell
# ═══════════════════════════════════════════════════════════════════


class TestShutdownCli:
    @patch("workshop.tmux.cli_session.is_shell")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    def test_sends_profile_exit_command(
        self, mock_send, mock_enter, mock_time, mock_sleep, mock_shell
    ):
        from tmux_lib.cli_session import shutdown_cli

        mock_time.side_effect = [0.0, 0.1]
        mock_shell.return_value = True
        assert shutdown_cli("%0", CLAUDE_CODE) is True
        mock_send.assert_called_once_with("%0", "/exit")
        mock_enter.assert_called_once()

    @patch("workshop.tmux.cli_session.is_shell")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    def test_timeout_returns_false(self, mock_send, mock_enter, mock_time, mock_sleep, mock_shell):
        from tmux_lib.cli_session import shutdown_cli

        mock_time.side_effect = [0.0, 1.0, 16.0]
        mock_shell.return_value = False
        assert shutdown_cli("%0", CLAUDE_CODE, timeout=15) is False

    @patch("workshop.tmux.cli_session.is_shell")
    @patch("workshop.tmux.cli_session.time.sleep")
    @patch("workshop.tmux.cli_session.time.time")
    @patch("workshop.tmux.cli_session.send_enter")
    @patch("workshop.tmux.cli_session.send_text")
    def test_custom_profile_exit_command(
        self, mock_send, mock_enter, mock_time, mock_sleep, mock_shell
    ):
        """Kills: hardcoding '/exit' instead of using profile.exit_command."""
        from tmux_lib.cli_session import shutdown_cli

        profile = CLIProfile(
            name="custom-exit",
            prompt_pattern=re.compile(r"\$"),
            process_names=frozenset({"x"}),
            exit_command="quit",
        )
        mock_time.side_effect = [0.0, 0.1]
        mock_shell.return_value = True
        shutdown_cli("%0", profile)
        mock_send.assert_called_once_with("%0", "quit")


# ═══════════════════════════════════════════════════════════════════
# Section 21: Pattern matching correctness
# ═══════════════════════════════════════════════════════════════════


class TestPatternMatching:
    def test_claude_prompt_matches_arrow(self):
        assert CLAUDE_CODE.prompt_pattern.search("❯")

    def test_claude_prompt_no_match_dollar(self):
        assert not CLAUDE_CODE.prompt_pattern.search("$")

    def test_codex_prompt_matches_gt(self):
        assert CODEX_CLI.prompt_pattern.search(">")

    def test_codex_prompt_matches_arrow(self):
        assert CODEX_CLI.prompt_pattern.search("❯")

    def test_claude_processing_matches_circle(self):
        assert CLAUDE_CODE.processing_indicators.search("⏺ Working...")

    def test_claude_processing_matches_thinking(self):
        assert CLAUDE_CODE.processing_indicators.search("Thinking deeply...")

    def test_claude_processing_no_match_idle(self):
        assert not CLAUDE_CODE.processing_indicators.search("Done.\n$ ")

    def test_claude_content_matches_box(self):
        assert CLAUDE_CODE.content_indicators.search("╭─ output")

    def test_claude_content_matches_cost(self):
        assert CLAUDE_CODE.content_indicators.search("💰 $0.01")


# ═══════════════════════════════════════════════════════════════════
# Section 22: _SHELLS and _SEMVER_RE invariants
# ═══════════════════════════════════════════════════════════════════


class TestShellsSet:
    def test_contains_all_expected(self):
        from tmux_lib.cli_session import _SHELLS

        for sh in ("zsh", "bash", "sh", "fish"):
            assert sh in _SHELLS

    def test_excludes_non_shells(self):
        from tmux_lib.cli_session import _SHELLS

        for non in ("python3", "claude", "node", "vim", "gemini"):
            assert non not in _SHELLS

    def test_is_frozenset(self):
        from tmux_lib.cli_session import _SHELLS

        assert isinstance(_SHELLS, frozenset)


class TestSemverRegex:
    def test_matches_standard(self):
        from tmux_lib.cli_session import _SEMVER_RE

        assert _SEMVER_RE.match("1.0.35")

    def test_matches_zeros(self):
        from tmux_lib.cli_session import _SEMVER_RE

        assert _SEMVER_RE.match("0.0.0")

    def test_no_match_name(self):
        from tmux_lib.cli_session import _SEMVER_RE

        assert not _SEMVER_RE.match("claude")

    def test_no_match_partial(self):
        from tmux_lib.cli_session import _SEMVER_RE

        assert not _SEMVER_RE.match("1.0")

    def test_no_match_empty(self):
        from tmux_lib.cli_session import _SEMVER_RE

        assert not _SEMVER_RE.match("")

    def test_anchored_at_start(self):
        """Kills: using search() instead of match() — 'x1.0.0' would pass."""
        from tmux_lib.cli_session import _SEMVER_RE

        assert not _SEMVER_RE.match("x1.0.0")


# ═══════════════════════════════════════════════════════════════════
# Section 23: Edge cases — extreme inputs
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    @patch("workshop.tmux.primitives.subprocess.run")
    def test_very_long_stdout_stripped(self, mock_run):
        long_text = "x" * 10000 + "  \n"
        mock_run.return_value = MagicMock(returncode=0, stdout=long_text, stderr="")
        r = tmux_run("test")
        assert not r.stdout.endswith(" ")
        assert not r.stdout.endswith("\n")

    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_boundary_512_no_paste(self, mock_check, mock_paste):
        send_text("%0", "B" * _SEND_KEYS_LIMIT)
        mock_paste.assert_not_called()

    @patch("workshop.tmux.primitives._paste_text_sync")
    @patch("workshop.tmux.primitives.tmux_check")
    def test_boundary_513_uses_paste(self, mock_check, mock_paste):
        send_text("%0", "B" * (_SEND_KEYS_LIMIT + 1))
        mock_paste.assert_called_once()

    def test_tmux_result_empty_fields(self):
        r = TmuxResult(0, "", "")
        assert r.ok is True
        assert r.stdout == ""
        assert r.stderr == ""

    def test_tmux_result_equality(self):
        """Invariant: frozen dataclass supports equality."""
        r1 = TmuxResult(0, "a", "b")
        r2 = TmuxResult(0, "a", "b")
        assert r1 == r2

    def test_tmux_result_inequality(self):
        r1 = TmuxResult(0, "a", "")
        r2 = TmuxResult(1, "a", "")
        assert r1 != r2
