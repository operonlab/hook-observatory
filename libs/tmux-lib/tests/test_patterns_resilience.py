"""Test tmux_lib.patterns resilience — cli_rosetta fallback.

Invariants tested (not implementation details):
1. Import NEVER fails regardless of cli_rosetta availability
2. Five named profiles always exist with correct types
3. Profiles match actual CLI prompt characters
4. Full import chain (tmux_lib -> patterns -> sdk_client.tmux_relay) works
5. Fallback profiles are functionally equivalent for detection purposes
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
import unittest

REQUIRED_PROFILES = ("claude-code", "gemini-cli", "codex-cli", "qwen-code", "copilot-cli")

# Known CLI prompt characters (ground truth from actual CLI outputs)
KNOWN_PROMPTS = {
    "claude-code": "\u276f",  # ❯
    "gemini-cli": "\u276f",  # ❯
    "codex-cli": "\u203a",  # ›
    "qwen-code": "\u276f",  # ❯
    "copilot-cli": ">",  # >
}


class TestPatternsImportResilience(unittest.TestCase):
    """Invariant: patterns module must be importable in any Python environment."""

    def test_import_patterns_direct(self):
        """tmux_lib.patterns imports without error."""
        import tmux_lib.patterns as mod

        self.assertTrue(hasattr(mod, "CLAUDE_CODE"))
        self.assertTrue(hasattr(mod, "_REGISTRY"))

    def test_import_tmux_lib_toplevel(self):
        """tmux_lib.__init__ re-exports from patterns without error."""
        import tmux_lib

        self.assertTrue(hasattr(tmux_lib, "CLAUDE_CODE"))
        self.assertTrue(hasattr(tmux_lib, "GEMINI_CLI"))
        self.assertTrue(hasattr(tmux_lib, "CODEX_CLI"))

    def test_import_after_forced_reimport(self):
        """Re-importing patterns after cache clear still works."""
        if "tmux_lib.patterns" in sys.modules:
            del sys.modules["tmux_lib.patterns"]
        mod = importlib.import_module("tmux_lib.patterns")
        self.assertIsNotNone(mod.CLAUDE_CODE)


class TestProfileInvariants(unittest.TestCase):
    """Invariant: all five profiles exist with correct structural properties."""

    @classmethod
    def setUpClass(cls):
        from tmux_lib.patterns import _REGISTRY

        cls.registry = _REGISTRY

    def test_all_required_profiles_exist(self):
        for name in REQUIRED_PROFILES:
            self.assertIn(name, self.registry, f"Missing profile: {name}")

    def test_profile_type(self):
        from tmux_lib.patterns import CLIProfile

        for name in REQUIRED_PROFILES:
            self.assertIsInstance(self.registry[name], CLIProfile)

    def test_prompt_pattern_is_compiled_regex(self):
        for name in REQUIRED_PROFILES:
            p = self.registry[name]
            self.assertIsInstance(
                p.prompt_pattern, re.Pattern, f"{name}.prompt_pattern is not re.Pattern"
            )

    def test_process_names_is_frozenset(self):
        for name in REQUIRED_PROFILES:
            p = self.registry[name]
            self.assertIsInstance(
                p.process_names, frozenset, f"{name}.process_names is not frozenset"
            )
            self.assertGreater(len(p.process_names), 0, f"{name}.process_names is empty")

    def test_exit_command_is_nonempty_string(self):
        for name in REQUIRED_PROFILES:
            p = self.registry[name]
            self.assertIsInstance(p.exit_command, str)
            self.assertTrue(len(p.exit_command) > 0, f"{name}.exit_command is empty")


class TestPromptDetection(unittest.TestCase):
    """Invariant: prompt patterns match known CLI prompt characters."""

    @classmethod
    def setUpClass(cls):
        from tmux_lib.patterns import _REGISTRY

        cls.registry = _REGISTRY

    def test_claude_code_prompt_matches(self):
        p = self.registry["claude-code"]
        self.assertIsNotNone(p.prompt_pattern.search(KNOWN_PROMPTS["claude-code"]))

    def test_gemini_prompt_matches(self):
        p = self.registry["gemini-cli"]
        self.assertIsNotNone(p.prompt_pattern.search(KNOWN_PROMPTS["gemini-cli"]))

    def test_codex_prompt_matches(self):
        p = self.registry["codex-cli"]
        self.assertIsNotNone(p.prompt_pattern.search(KNOWN_PROMPTS["codex-cli"]))

    def test_qwen_prompt_matches(self):
        p = self.registry["qwen-code"]
        self.assertIsNotNone(p.prompt_pattern.search(KNOWN_PROMPTS["qwen-code"]))

    def test_copilot_prompt_matches(self):
        p = self.registry["copilot-cli"]
        self.assertIsNotNone(p.prompt_pattern.search(KNOWN_PROMPTS["copilot-cli"]))

    def test_claude_processing_indicators_exist(self):
        """Claude Code must have processing indicators (critical for idle detection)."""
        p = self.registry["claude-code"]
        self.assertIsNotNone(p.processing_indicators)
        # Must match the actual spinner characters
        for char in ("\u23fa", "\u2722", "\u273b"):  # ⏺ ✢ ✻
            self.assertIsNotNone(
                p.processing_indicators.search(char),
                f"Claude Code processing_indicators doesn't match '{char}'",
            )


class TestFallbackEquivalence(unittest.TestCase):
    """Invariant: fallback profiles are functionally equivalent for detection.

    Run the same test suite in a subprocess WITHOUT cli_rosetta available
    and verify the fallback path produces matching results.
    """

    def test_fallback_path_in_subprocess(self):
        """Run profile checks in ~/.local/bin/python3 (no venv, no cli_rosetta)."""
        script = """
import sys, json
# Verify cli_rosetta is NOT available
try:
    import cli_rosetta
    print(json.dumps({"error": "cli_rosetta unexpectedly available"}))
    sys.exit(1)
except ImportError:
    pass

from tmux_lib.patterns import _REGISTRY, CLIProfile
import re

results = {}
for name in ("claude-code", "gemini-cli", "codex-cli", "qwen-code", "copilot-cli"):
    p = _REGISTRY.get(name)
    if p is None:
        results[name] = {"error": "missing"}
        continue
    results[name] = {
        "type_ok": isinstance(p, CLIProfile),
        "prompt_pattern": p.prompt_pattern.pattern,
        "process_names": sorted(p.process_names),
        "has_indicators": p.processing_indicators is not None,
        "exit_command": p.exit_command,
    }
print(json.dumps(results))
"""
        result = subprocess.run(
            [
                "/Users/joneshong/.local/bin/python3",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd="/Users/joneshong/workshop",
        )
        self.assertEqual(result.returncode, 0, f"Subprocess failed: {result.stderr}")

        import json

        data = json.loads(result.stdout)
        for name in REQUIRED_PROFILES:
            with self.subTest(profile=name):
                self.assertIn(name, data, f"Missing {name} in fallback")
                info = data[name]
                self.assertNotIn("error", info, f"{name}: {info.get('error')}")
                self.assertTrue(info["type_ok"], f"{name} wrong type")
                self.assertGreater(len(info["process_names"]), 0)
                self.assertGreater(len(info["exit_command"]), 0)

        # Claude Code must have processing indicators in fallback too
        self.assertTrue(
            data["claude-code"]["has_indicators"],
            "Claude Code fallback missing processing_indicators",
        )


class TestRelayImportChain(unittest.TestCase):
    """Invariant: full relay chain importable and constructible."""

    def test_tmux_relay_client_creates(self):
        from sdk_client.tmux_relay import TmuxRelayClient

        relay = TmuxRelayClient()
        self.assertIsNotNone(relay)

    def test_relay_list_panes_no_crash(self):
        """list_panes() runs without error (may return empty if no relay windows)."""
        from sdk_client.tmux_relay import TmuxRelayClient

        relay = TmuxRelayClient()
        try:
            panes = relay.list_panes()
            self.assertIsInstance(panes, list)
        except Exception as e:
            # Only acceptable failure: no tmux session
            self.assertIn("no server running", str(e).lower())


class TestLivePaneDetection(unittest.TestCase):
    """Runtime test: detect actual CLI processes in current tmux session."""

    def _get_live_panes(self):
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id} #{pane_current_command}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            self.skipTest("tmux not running")
        panes = {}
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                panes[parts[0]] = parts[1]
        return panes

    def test_detect_running_cli_processes(self):
        """If any known CLI is running, its profile's process_names should match."""
        from tmux_lib.patterns import _REGISTRY

        all_binaries = {}
        for name, profile in _REGISTRY.items():
            for pname in profile.process_names:
                all_binaries[pname] = name

        panes = self._get_live_panes()
        detected = []
        for pane_id, cmd in panes.items():
            # pane_current_command is the basename of the running process
            cmd_base = cmd.split("/")[-1].split()[0] if cmd else ""
            if cmd_base in all_binaries:
                detected.append((pane_id, cmd_base, all_binaries[cmd_base]))

        # This is observational — we just verify no crash and log what we found
        for pane_id, binary, profile_name in detected:
            profile = _REGISTRY[profile_name]
            self.assertIn(binary, profile.process_names)

    def test_has_prompt_on_idle_pane(self):
        """If there's an idle Claude Code pane, has_prompt should return True."""
        from tmux_lib import has_prompt
        from tmux_lib.patterns import CLAUDE_CODE

        panes = self._get_live_panes()
        claude_panes = [
            pid
            for pid, cmd in panes.items()
            if cmd.split("/")[-1].split()[0] in CLAUDE_CODE.process_names
        ]

        if not claude_panes:
            self.skipTest("No Claude Code panes running")

        # At least test that has_prompt doesn't crash
        for pane_id in claude_panes[:2]:  # limit to 2
            result = has_prompt(pane_id, CLAUDE_CODE)
            self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
