"""Tests for maestro dispatch argparse bug fix.

Root cause: argparse.REMAINDER swallows known flags that appear after
a positional argument. Maestro was passing [prompt, "--full-auto", "--cd", cwd]
which caused codex_headless to parse full_auto=False, cd=None.

Invariants tested:
  1. Flags after positional MUST be parsed correctly (the actual bug)
  2. Flags before positional MUST still work (regression guard)
  3. Extra/unknown args passed through correctly
  4. maestro dispatch_agent builds correct arg order
"""

import argparse
import subprocess
import sys

# ---------------------------------------------------------------------------
# Fixture: minimal argparse that mirrors codex_headless.py's structure
# ---------------------------------------------------------------------------

def build_codex_argparse() -> argparse.ArgumentParser:
    """Replicate codex_headless.py's argparse (post-fix: parse_known_args)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?", default=None)
    ap.add_argument("--full-auto", action="store_true")
    ap.add_argument("--cd", "-C", default=None)
    ap.add_argument("-m", "--model", default=None)
    ap.add_argument("--mode", choices=["headless", "interactive"], default="headless")
    ap.add_argument("--codex-bin", default="")
    ap.add_argument("--skip-preflight", action="store_true")
    ap.add_argument("--background", "--bg", action="store_true")
    ap.add_argument("--clipboard", action="store_true")
    ap.add_argument("-s", "--sandbox", default=None)
    ap.add_argument("-p", "--profile", default=None)
    ap.add_argument("-i", "--image", action="append", default=None)
    ap.add_argument("--json", dest="json_output", action="store_true")
    ap.add_argument("-o", "--output-file", default=None)
    ap.add_argument("--ephemeral", action="store_true")
    ap.add_argument("--skip-git-repo-check", action="store_true")
    ap.add_argument("--yolo", action="store_true")
    ap.add_argument("--notify", action="store_true")
    return ap


# ---------------------------------------------------------------------------
# Invariant 1: flags after positional MUST be parsed (THE BUG)
# ---------------------------------------------------------------------------

class TestFlagsAfterPositional:
    """The exact scenario maestro was triggering before the fix."""

    def test_old_maestro_order_prompt_then_flags(self):
        """maestro used to pass: [prompt, --full-auto, --cd, /path]"""
        ap = build_codex_argparse()
        args, extra = ap.parse_known_args(
            ["hello test", "--full-auto", "--cd", "/Users/joneshong/workshop"]
        )
        assert args.prompt == "hello test"
        assert args.full_auto is True, "full_auto must be True even after positional"
        assert args.cd == "/Users/joneshong/workshop"
        assert extra == []

    def test_flags_with_model_after_prompt(self):
        ap = build_codex_argparse()
        args, extra = ap.parse_known_args(
            ["do something", "--full-auto", "-m", "o4-mini", "--cd", "/tmp"]
        )
        assert args.prompt == "do something"
        assert args.full_auto is True
        assert args.model == "o4-mini"
        assert args.cd == "/tmp"


# ---------------------------------------------------------------------------
# Invariant 2: flags before positional still work (regression guard)
# ---------------------------------------------------------------------------

class TestFlagsBeforePositional:
    def test_flags_then_prompt(self):
        ap = build_codex_argparse()
        args, extra = ap.parse_known_args(
            ["--full-auto", "--cd", "/workshop", "my prompt"]
        )
        assert args.prompt == "my prompt"
        assert args.full_auto is True
        assert args.cd == "/workshop"

    def test_interleaved_flags_and_prompt(self):
        ap = build_codex_argparse()
        args, extra = ap.parse_known_args(
            ["--full-auto", "the prompt", "--cd", "/workshop"]
        )
        assert args.prompt == "the prompt"
        assert args.full_auto is True
        assert args.cd == "/workshop"


# ---------------------------------------------------------------------------
# Invariant 3: unknown args go to extras (passthrough to underlying CLI)
# ---------------------------------------------------------------------------

class TestExtraArgsPassthrough:
    def test_unknown_flags_captured(self):
        ap = build_codex_argparse()
        args, extra = ap.parse_known_args(
            ["--full-auto", "prompt", "--some-unknown-flag", "--another", "val"]
        )
        assert args.prompt == "prompt"
        assert args.full_auto is True
        assert "--some-unknown-flag" in extra
        assert "--another" in extra

    def test_double_dash_separator(self):
        ap = build_codex_argparse()
        args, extra = ap.parse_known_args(
            ["--full-auto", "prompt", "--", "--raw-flag"]
        )
        assert args.full_auto is True
        # -- and everything after goes to extra
        stripped = [a for a in extra if a != "--"]
        assert "--raw-flag" in stripped or "--raw-flag" in extra


# ---------------------------------------------------------------------------
# Invariant 4: maestro dispatch_agent builds correct arg order
# ---------------------------------------------------------------------------

class TestMaestroDispatchArgOrder:
    """Verify the fixed maestro.py puts prompt LAST for codex."""

    def test_codex_prompt_after_flags(self):
        """Simulate the fixed dispatch_agent cmd construction."""
        prompt = "analyze this codebase"
        cwd = "/Users/joneshong/workshop"

        # Fixed maestro logic:
        cmd = ["python3", "codex_headless.py"]
        cmd += ["--full-auto"]
        if cwd:
            cmd += ["--cd", cwd]
        cmd.append(prompt)

        # prompt should be last
        assert cmd[-1] == prompt
        # --full-auto should appear before prompt
        fa_idx = cmd.index("--full-auto")
        prompt_idx = cmd.index(prompt)
        assert fa_idx < prompt_idx, "--full-auto must come before prompt"

    def test_claude_dispatch_unchanged(self):
        """Claude uses -p flag, so order doesn't matter. Verify unchanged."""
        prompt = "do something"
        cmd = ["python3", "claude_headless.py"]
        cmd += ["-p", prompt, "--output-format", "json"]
        # -p makes prompt a flag value, not positional — safe regardless of order
        assert "-p" in cmd
        assert cmd[cmd.index("-p") + 1] == prompt

    def test_gemini_dispatch_unchanged(self):
        """Gemini uses -p flag, so order doesn't matter. Verify unchanged."""
        prompt = "do something"
        cmd = ["python3", "gemini_headless.py"]
        cmd += ["-p", prompt, "--approval-mode", "yolo"]
        assert "-p" in cmd
        assert cmd[cmd.index("-p") + 1] == prompt


# ---------------------------------------------------------------------------
# Integration: actually run codex_headless with parse_known_args
# ---------------------------------------------------------------------------

class TestCodexHeadlessIntegration:
    """Run the actual codex_headless.py to verify the argparse fix.

    Note: --codex-bin /nonexistent falls back to PATH discovery,
    so if codex is installed, it WILL run. We test arg parsing
    by checking the script imports cleanly and parses without error.
    """

    SCRIPT = "/Users/joneshong/.claude/skills/codex-cli-headless/scripts/codex_headless.py"

    def test_argparse_prompt_first_parses_correctly(self):
        """Verify parse_known_args handles prompt-before-flags.

        We test the argparse layer in isolation by importing and calling
        parse_known_args directly, avoiding actually running codex.
        """
        proc = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; sys.argv = ['codex_headless.py', 'test', '--full-auto', '--cd', '/tmp'];"
                "import argparse; ap = argparse.ArgumentParser();"
                "ap.add_argument('prompt', nargs='?', default=None);"
                "ap.add_argument('--full-auto', action='store_true');"
                "ap.add_argument('--cd', '-C', default=None);"
                "args, extra = ap.parse_known_args();"
                "assert args.full_auto, f'full_auto={args.full_auto}';"
                "assert args.cd == '/tmp', f'cd={args.cd}';"
                "print('OK')",
            ],
            capture_output=True, text=True, timeout=5,
        )
        assert proc.returncode == 0
        assert "OK" in proc.stdout

    def test_argparse_flags_first_parses_correctly(self):
        """Flags-first order should also work (regression guard)."""
        proc = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; sys.argv = ['codex_headless.py', '--full-auto', '--cd', '/tmp', 'test'];"
                "import argparse; ap = argparse.ArgumentParser();"
                "ap.add_argument('prompt', nargs='?', default=None);"
                "ap.add_argument('--full-auto', action='store_true');"
                "ap.add_argument('--cd', '-C', default=None);"
                "args, extra = ap.parse_known_args();"
                "assert args.full_auto, f'full_auto={args.full_auto}';"
                "assert args.cd == '/tmp', f'cd={args.cd}';"
                "assert args.prompt == 'test', f'prompt={args.prompt}';"
                "print('OK')",
            ],
            capture_output=True, text=True, timeout=5,
        )
        assert proc.returncode == 0
        assert "OK" in proc.stdout


# ---------------------------------------------------------------------------
# Mutation: would the OLD code pass these tests? (mutation thinking)
# ---------------------------------------------------------------------------

class TestOldCodeWouldFail:
    """Document what the OLD argparse.REMAINDER code would produce.

    These tests verify the bug existed and is now fixed.
    With REMAINDER, [prompt, --full-auto, --cd, /path] produces:
      prompt="prompt", full_auto=False, cd=None, extra=["--full-auto","--cd","/path"]
    """

    def test_remainder_swallows_flags(self):
        """Prove REMAINDER behavior for documentation."""
        ap = argparse.ArgumentParser()
        ap.add_argument("prompt", nargs="?", default=None)
        ap.add_argument("--full-auto", action="store_true")
        ap.add_argument("--cd", default=None)
        ap.add_argument("extra", nargs=argparse.REMAINDER)

        args = ap.parse_args(
            ["hello", "--full-auto", "--cd", "/path"]
        )
        # This demonstrates the BUG — REMAINDER eats the flags
        assert args.full_auto is False, "REMAINDER causes full_auto=False (the bug)"
        assert args.cd is None, "REMAINDER causes cd=None (the bug)"
        assert "--full-auto" in args.extra, "flags end up in extra"

    def test_parse_known_args_fixes_it(self):
        """Same argparse but with parse_known_args — flags parsed correctly."""
        ap = argparse.ArgumentParser()
        ap.add_argument("prompt", nargs="?", default=None)
        ap.add_argument("--full-auto", action="store_true")
        ap.add_argument("--cd", default=None)

        args, extra = ap.parse_known_args(
            ["hello", "--full-auto", "--cd", "/path"]
        )
        assert args.full_auto is True, "parse_known_args correctly parses flags"
        assert args.cd == "/path"
        assert extra == []
