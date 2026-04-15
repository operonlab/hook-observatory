"""cli-rosetta adversarial test suite.

Follows the Six Iron Laws of AI Testing:
1. Mutation thinking — every assert must be able to catch a single-char mutation
2. Write/test separation — infer behavior from public API + docstrings only
3. Invariant-first — verify properties, not just fixed I/O
4. Boundary / error paths — runtime → regression
5. Mock only external I/O — health.py subprocess calls only
6. Draft is not production — reviewed with mutation lens before finalizing
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Path bootstrap ──────────────────────────────────────────────────────────
_LIB_DIR = str(Path(__file__).parent.parent)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

import pytest

from cli_rosetta import (
    CLAUDE_CODE,
    CODEX_CLI,
    COPILOT_CLI,
    GEMINI_CLI,
    QWEN_CODE,
    CLIEntry,
    ExitBehavior,
    ToolNameMap,
    detect_from_command,
    get,
    list_entries,
    list_names,
    register,
)
from cli_rosetta.health import check_one

# ══════════════════════════════════════════════════════════════════════════════
# Section 1 — Invariants (property-style tests across all entries)
# ══════════════════════════════════════════════════════════════════════════════


def _all_entries() -> list[CLIEntry]:
    return list_entries()


class TestIdentityInvariants:
    """Every registered entry must have non-empty identity fields."""

    def test_name_nonempty(self):
        for e in _all_entries():
            assert e.name, f"{e.display_name}: name must be non-empty"

    def test_binary_nonempty(self):
        for e in _all_entries():
            assert e.binary, f"{e.display_name}: binary must be non-empty"

    def test_vendor_nonempty(self):
        for e in _all_entries():
            assert e.vendor, f"{e.display_name}: vendor must be non-empty"

    def test_display_name_nonempty(self):
        for e in _all_entries():
            assert e.display_name, f"{e.name}: display_name must be non-empty"


class TestExitBehaviorInvariant:
    """Every exit_behavior must have at least one of command or key_sequence."""

    def test_exit_has_command_or_key_sequence(self):
        for e in _all_entries():
            eb = e.exit_behavior
            assert eb.command is not None or eb.key_sequence is not None, (
                f"{e.name}: exit_behavior has neither command nor key_sequence"
            )

    def test_exit_description_never_returns_empty_string(self):
        """exit_description() should always return a non-empty human-readable string."""
        for e in _all_entries():
            desc = e.exit_description()
            assert desc, f"{e.name}: exit_description() returned empty string"


class TestAliasesResolveToValidEntry:
    """All aliases in the registry must resolve to an actual CLIEntry."""

    def test_all_canonical_aliases_resolvable(self):
        # Test every known alias group
        alias_groups = [
            ["claude", "cc", "anthropic", "claude-code"],
            ["codex", "openai", "codex-cli"],
            ["copilot", "github", "gh", "copilot-cli"],
            ["gemini", "google", "gemini-cli"],
            ["qwen", "alibaba", "qwen-code"],
        ]
        for group in alias_groups:
            for alias in group:
                entry = get(alias)
                assert isinstance(entry, CLIEntry), f"Alias '{alias}' did not resolve to CLIEntry"
            # All aliases in the same group must resolve to the same entry
            canonical = get(group[0])
            for alias in group[1:]:
                assert get(alias).name == canonical.name, (
                    f"Alias '{alias}' resolved to different entry than '{group[0]}'"
                )


class TestDetectFromCommandConsistency:
    """detect_from_command() must be consistent with process_names."""

    def test_process_names_detect_back_to_same_entry(self):
        for e in _all_entries():
            for pname in e.process_names:
                detected = detect_from_command(pname)
                assert detected is not None, (
                    f"{e.name}: process_name '{pname}' not detected by detect_from_command()"
                )
                assert detected.name == e.name, (
                    f"process_name '{pname}' detected as '{detected.name}', expected '{e.name}'"
                )

    def test_process_name_with_full_path(self):
        """detect_from_command splits on / — a full path should also work."""
        for e in _all_entries():
            for pname in e.process_names:
                full = f"/usr/local/bin/{pname}"
                detected = detect_from_command(full)
                assert detected is not None, f"{e.name}: full path '{full}' not detected"
                assert detected.name == e.name


class TestToolNameMapTranslateUnknown:
    """translate() on an unknown CC tool name must return the original name (pass-through)."""

    def test_translate_unknown_returns_original(self):
        tm = ToolNameMap()  # default CC-canonical names
        unknown = "SomeFutureTool"
        result = tm.translate(unknown)
        assert result == unknown, (
            f"translate('{unknown}') returned '{result}', expected '{unknown}'"
        )

    def test_translate_list_unknown_preserves_unknown(self):
        tm = ToolNameMap()
        result = tm.translate_list("Read, SomeFutureTool")
        assert "SomeFutureTool" in result


class TestHeadlessCmdFirstElementIsBinary:
    """headless_cmd() must always return a list whose first element is the binary."""

    def test_headless_cmd_starts_with_binary(self):
        for e in _all_entries():
            cmd = e.headless_cmd("test prompt")
            assert cmd, f"{e.name}: headless_cmd() returned empty list"
            assert cmd[0] == e.binary, (
                f"{e.name}: headless_cmd()[0] == '{cmd[0]}', expected binary '{e.binary}'"
            )

    def test_headless_cmd_with_all_flags_still_starts_with_binary(self):
        for e in _all_entries():
            cmd = e.headless_cmd(
                "test",
                model="test-model",
                auto_approve=True,
                extra_flags=["--verbose"],
            )
            assert cmd[0] == e.binary, (
                f"{e.name}: headless_cmd with flags — first element is '{cmd[0]}'"
            )


class TestListLengthConsistency:
    """list_entries() and list_names() must return the same number of items."""

    def test_list_entries_and_names_same_length(self):
        entries = list_entries()
        names = list_names()
        assert len(entries) == len(names), (
            f"list_entries() has {len(entries)} items, list_names() has {len(names)}"
        )

    def test_list_names_match_entry_names(self):
        names_set = set(list_names())
        for e in list_entries():
            assert e.name in names_set, f"Entry '{e.name}' not in list_names()"


# ══════════════════════════════════════════════════════════════════════════════
# Section 2 — Boundary & Error Paths
# ══════════════════════════════════════════════════════════════════════════════


class TestGetErrors:
    def test_get_nonexistent_raises_key_error(self):
        with pytest.raises(KeyError):
            get("nonexistent_cli_tool_xyz")

    def test_get_empty_string_raises_key_error(self):
        with pytest.raises(KeyError):
            get("")


class TestDetectFromCommandEdgeCases:
    def test_empty_string_returns_none(self):
        assert detect_from_command("") is None

    def test_unknown_process_returns_none(self):
        assert detect_from_command("unknown_process_xyz") is None

    def test_partial_match_does_not_detect(self):
        # "claud" is not in process_names for any entry
        assert detect_from_command("claud") is None


class TestToolNameMapTranslateListEdgeCases:
    def test_translate_list_empty_string_returns_empty_string(self):
        tm = ToolNameMap()
        result = tm.translate_list("")
        # Empty string — split produces no parts → join of empty list → ""
        assert result == "", f"translate_list('') returned '{result}', expected ''"

    def test_translate_list_whitespace_only_returns_empty(self):
        tm = ToolNameMap()
        result = tm.translate_list("   ,  ,   ")
        assert result == "", f"translate_list(whitespace) returned '{result}'"

    def test_translate_list_empty_mapping_not_included(self):
        """Tools that map to "" (no equivalent) must be excluded from output."""
        # Codex has glob="" and grep="" — translating those names should not add empty strings
        codex_tm = CODEX_CLI.tool_names
        result = codex_tm.translate_list("Glob, Grep")
        # Both map to "" → both filtered → result should be ""
        assert result == "", f"translate_list with no-equiv tools returned '{result}'"


class TestHeadlessCmdAutoApproveEmpty:
    """auto_approve=True with empty flag should not inject extra tokens."""

    def test_auto_approve_true_empty_flag_no_extra_element(self):
        # Copilot has a non-empty flag; synthesize an entry with empty flag
        entry = CLIEntry(
            name="test-empty-approve",
            binary="test-bin",
            display_name="Test",
            vendor="test",
            exit_behavior=ExitBehavior(command="/exit"),
        )
        cmd_without = entry.headless_cmd("hello")
        cmd_with = entry.headless_cmd("hello", auto_approve=True)
        # With empty auto_approve.flag, both commands should be identical
        assert cmd_without == cmd_with, (
            f"auto_approve=True with empty flag changed the command: {cmd_with}"
        )


class TestExitDescriptionVariants:
    def test_command_with_needs_enter_true(self):
        eb = ExitBehavior(command="/exit", needs_enter=True)
        # Synthetic CLIEntry just to call exit_description
        entry = CLIEntry(
            name="x",
            binary="x",
            display_name="X",
            vendor="v",
            exit_behavior=eb,
        )
        desc = entry.exit_description()
        assert "Enter" in desc, f"needs_enter=True should include 'Enter': '{desc}'"
        assert "/exit" in desc

    def test_command_with_needs_enter_false(self):
        eb = ExitBehavior(command="/quit", needs_enter=False)
        entry = CLIEntry(
            name="x",
            binary="x",
            display_name="X",
            vendor="v",
            exit_behavior=eb,
        )
        desc = entry.exit_description()
        assert "Enter" not in desc, f"needs_enter=False must not include 'Enter': '{desc}'"
        assert "/quit" in desc

    def test_key_sequence_repeat_1_no_multiplication(self):
        eb = ExitBehavior(key_sequence="C-c", repeat=1)
        entry = CLIEntry(
            name="x",
            binary="x",
            display_name="X",
            vendor="v",
            exit_behavior=eb,
        )
        desc = entry.exit_description()
        assert "C-c" in desc
        assert "×" not in desc, f"repeat=1 must not include '×': '{desc}'"

    def test_key_sequence_repeat_greater_than_1_has_multiplication(self):
        eb = ExitBehavior(key_sequence="C-c", repeat=2)
        entry = CLIEntry(
            name="x",
            binary="x",
            display_name="X",
            vendor="v",
            exit_behavior=eb,
        )
        desc = entry.exit_description()
        assert "C-c" in desc
        assert "×" in desc, f"repeat=2 must include '×': '{desc}'"
        assert "2" in desc

    def test_no_command_no_key_returns_unknown(self):
        eb = ExitBehavior(command=None, key_sequence=None)
        entry = CLIEntry(
            name="x",
            binary="x",
            display_name="X",
            vendor="v",
            exit_behavior=eb,
        )
        desc = entry.exit_description()
        assert desc == "unknown", f"No command/key should return 'unknown': '{desc}'"


# ══════════════════════════════════════════════════════════════════════════════
# Section 3 — Concrete Value Validation (mutation killers)
# ══════════════════════════════════════════════════════════════════════════════


class TestVendorValues:
    """Vendor must match the exact string — wrong vendor = wrong upstream attribution."""

    def test_claude_vendor_is_anthropic(self):
        assert CLAUDE_CODE.vendor == "anthropic", (
            f"Claude Code vendor is '{CLAUDE_CODE.vendor}', expected 'anthropic'"
        )

    def test_codex_vendor_is_openai(self):
        assert CODEX_CLI.vendor == "openai", (
            f"Codex CLI vendor is '{CODEX_CLI.vendor}', expected 'openai'"
        )

    def test_copilot_vendor_is_github(self):
        assert COPILOT_CLI.vendor == "github", (
            f"Copilot CLI vendor is '{COPILOT_CLI.vendor}', expected 'github'"
        )

    def test_gemini_vendor_is_google(self):
        assert GEMINI_CLI.vendor == "google", (
            f"Gemini CLI vendor is '{GEMINI_CLI.vendor}', expected 'google'"
        )

    def test_qwen_vendor_is_alibaba(self):
        assert QWEN_CODE.vendor == "alibaba", (
            f"Qwen Code vendor is '{QWEN_CODE.vendor}', expected 'alibaba'"
        )


class TestMCPConfigKey:
    """MCP config_key determines the JSON/TOML key — wrong key breaks MCP wiring."""

    def test_claude_mcp_config_key(self):
        assert CLAUDE_CODE.mcp.config_key == "mcpServers", (
            f"Claude Code mcp.config_key is '{CLAUDE_CODE.mcp.config_key}'"
        )

    def test_codex_mcp_config_key(self):
        # Codex TOML uses underscore convention
        assert CODEX_CLI.mcp.config_key == "mcp_servers", (
            f"Codex CLI mcp.config_key is '{CODEX_CLI.mcp.config_key}', expected 'mcp_servers'"
        )

    def test_copilot_mcp_config_key(self):
        assert COPILOT_CLI.mcp.config_key == "mcpServers", (
            f"Copilot CLI mcp.config_key is '{COPILOT_CLI.mcp.config_key}'"
        )

    def test_gemini_mcp_config_key(self):
        assert GEMINI_CLI.mcp.config_key == "mcpServers", (
            f"Gemini CLI mcp.config_key is '{GEMINI_CLI.mcp.config_key}'"
        )

    def test_qwen_mcp_config_key(self):
        assert QWEN_CODE.mcp.config_key == "mcpServers", (
            f"Qwen Code mcp.config_key is '{QWEN_CODE.mcp.config_key}'"
        )


class TestCodexMCPFormat:
    """Codex uses TOML, not JSON — critical for config generation."""

    def test_codex_mcp_format_is_toml(self):
        assert CODEX_CLI.mcp.config_format == "toml", (
            f"Codex CLI mcp.config_format is '{CODEX_CLI.mcp.config_format}', expected 'toml'"
        )

    def test_codex_mcp_format_is_not_json(self):
        assert CODEX_CLI.mcp.config_format != "json"


class TestGeminiHTTPUrlKey:
    """Gemini uses 'httpUrl' not 'url' — mixing them breaks HTTP MCP wiring."""

    def test_gemini_http_url_key_is_httpUrl(self):
        assert GEMINI_CLI.mcp.http_url_key == "httpUrl", (
            f"Gemini CLI mcp.http_url_key is '{GEMINI_CLI.mcp.http_url_key}', expected 'httpUrl'"
        )

    def test_other_clis_http_url_key_is_url(self):
        for entry in [CLAUDE_CODE, CODEX_CLI, COPILOT_CLI, QWEN_CODE]:
            assert entry.mcp.http_url_key == "url", (
                f"{entry.name} mcp.http_url_key is '{entry.mcp.http_url_key}', expected 'url'"
            )


class TestQwenToolNames:
    """Qwen tool names differ from Gemini despite being a fork."""

    def test_qwen_edit_is_edit_not_edit_file(self):
        assert QWEN_CODE.tool_names.edit == "edit", (
            f"Qwen Code tool_names.edit is '{QWEN_CODE.tool_names.edit}', expected 'edit'"
        )
        assert QWEN_CODE.tool_names.edit != "edit_file"

    def test_qwen_glob_is_glob_not_glob_search(self):
        assert QWEN_CODE.tool_names.glob == "glob", (
            f"Qwen Code tool_names.glob is '{QWEN_CODE.tool_names.glob}', expected 'glob'"
        )
        assert QWEN_CODE.tool_names.glob != "glob_search"

    def test_gemini_glob_is_glob_search(self):
        """Confirm the fork divergence — Gemini still uses glob_search."""
        assert GEMINI_CLI.tool_names.glob == "glob_search", (
            f"Gemini CLI tool_names.glob is '{GEMINI_CLI.tool_names.glob}'"
        )

    def test_gemini_edit_is_edit_file(self):
        assert GEMINI_CLI.tool_names.edit == "edit_file", (
            f"Gemini CLI tool_names.edit is '{GEMINI_CLI.tool_names.edit}'"
        )


class TestQwenHookStyle:
    """Qwen hooks are CC-style (PreToolUse), not Gemini-style (BeforeTool)."""

    def test_qwen_hooks_has_pre_tool_use(self):
        assert "PreToolUse" in QWEN_CODE.hooks.events, (
            "Qwen Code hooks must include 'PreToolUse' (CC-style)"
        )

    def test_qwen_hooks_does_not_have_before_tool(self):
        assert "BeforeTool" not in QWEN_CODE.hooks.events, (
            "Qwen Code must NOT have 'BeforeTool' (Gemini-style)"
        )

    def test_gemini_hooks_has_before_tool(self):
        assert "BeforeTool" in GEMINI_CLI.hooks.events

    def test_gemini_hooks_does_not_have_pre_tool_use(self):
        assert "PreToolUse" not in GEMINI_CLI.hooks.events


class TestCopilotToolNames:
    """Copilot uses 'search' for grep and 'web_fetch' for web_fetch — exact strings matter."""

    def test_copilot_grep_is_search(self):
        assert COPILOT_CLI.tool_names.grep == "search", (
            f"Copilot CLI tool_names.grep is '{COPILOT_CLI.tool_names.grep}', expected 'search'"
        )
        assert COPILOT_CLI.tool_names.grep != ""
        assert COPILOT_CLI.tool_names.grep != "grep"

    def test_copilot_web_fetch_is_web_fetch(self):
        assert COPILOT_CLI.tool_names.web_fetch == "web_fetch", (
            f"Copilot CLI tool_names.web_fetch is '{COPILOT_CLI.tool_names.web_fetch}'"
        )
        assert COPILOT_CLI.tool_names.web_fetch != ""


class TestRegisterCustomEntry:
    """register() must make the entry accessible via get() and list_entries()."""

    def test_register_and_get(self):
        custom = CLIEntry(
            name="custom-test-cli",
            binary="custom-bin",
            display_name="Custom Test CLI",
            vendor="test-vendor",
            exit_behavior=ExitBehavior(command="/quit"),
        )
        initial_count = len(list_entries())
        register(custom, aliases=["customtest", "ct"])

        # get() by canonical name
        retrieved = get("custom-test-cli")
        assert retrieved.name == "custom-test-cli"
        assert retrieved.vendor == "test-vendor"

        # get() by alias
        by_alias = get("customtest")
        assert by_alias.name == "custom-test-cli"

        by_alias2 = get("ct")
        assert by_alias2.name == "custom-test-cli"

        # list_entries() count increased
        assert len(list_entries()) == initial_count + 1

        # list_names() includes the new entry
        assert "custom-test-cli" in list_names()

    def test_register_makes_binary_resolvable(self):
        """register() also adds the binary as an alias."""
        custom2 = CLIEntry(
            name="custom-test-cli-2",
            binary="custom-bin-2",
            display_name="Custom Test CLI 2",
            vendor="test-vendor-2",
            exit_behavior=ExitBehavior(command="/exit"),
        )
        register(custom2)
        by_binary = get("custom-bin-2")
        assert by_binary.name == "custom-test-cli-2"


# ══════════════════════════════════════════════════════════════════════════════
# Section 4 — health.py (mock subprocess)
# ══════════════════════════════════════════════════════════════════════════════


class TestHealthCheckOne:
    def test_installed_cli_returns_installed_true(self):
        """When shutil.which finds the binary, installed should be True."""
        with (
            patch("cli_rosetta.health.shutil.which", return_value="/usr/local/bin/claude"),
            patch("cli_rosetta.health.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                stdout=f"Claude Code {CLAUDE_CODE.known_version}\n",
                stderr="",
            )
            result = check_one(CLAUDE_CODE)

        assert result.installed is True, "installed should be True when binary found"
        assert result.path == "/usr/local/bin/claude"

    def test_not_installed_cli_returns_installed_false(self):
        """When shutil.which returns None, installed must be False."""
        with patch("cli_rosetta.health.shutil.which", return_value=None):
            result = check_one(CODEX_CLI)

        assert result.installed is False, "installed should be False when binary not found"
        assert result.path == ""
        assert result.current_version == ""
        assert result.outdated is False

    def test_outdated_when_version_differs(self):
        """If current_version != known_version, outdated should be True."""
        old_version = "0.100.0"
        assert old_version != CLAUDE_CODE.known_version, "Precondition: version must differ"

        with (
            patch("cli_rosetta.health.shutil.which", return_value="/usr/bin/claude"),
            patch("cli_rosetta.health.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                stdout=f"Claude Code {old_version}\n",
                stderr="",
            )
            result = check_one(CLAUDE_CODE)

        assert result.outdated is True, (
            f"outdated should be True when version is '{old_version}', known is '{CLAUDE_CODE.known_version}'"
        )
        assert result.current_version == old_version

    def test_not_outdated_when_version_matches(self):
        """If current_version == known_version, outdated must be False."""
        with (
            patch("cli_rosetta.health.shutil.which", return_value="/usr/bin/claude"),
            patch("cli_rosetta.health.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                stdout=f"Claude Code {CLAUDE_CODE.known_version}\n",
                stderr="",
            )
            result = check_one(CLAUDE_CODE)

        assert result.outdated is False

    def test_status_property_not_installed(self):
        with patch("cli_rosetta.health.shutil.which", return_value=None):
            result = check_one(GEMINI_CLI)
        assert result.status == "not_installed"

    def test_status_property_ok_when_version_matches(self):
        with (
            patch("cli_rosetta.health.shutil.which", return_value="/usr/bin/gemini"),
            patch("cli_rosetta.health.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                stdout=f"Gemini CLI {GEMINI_CLI.known_version}\n",
                stderr="",
            )
            result = check_one(GEMINI_CLI)
        assert result.status == "ok"

    def test_status_property_outdated(self):
        with (
            patch("cli_rosetta.health.shutil.which", return_value="/usr/bin/gemini"),
            patch("cli_rosetta.health.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                stdout="Gemini CLI 0.1.0\n",
                stderr="",
            )
            result = check_one(GEMINI_CLI)
        assert result.status == "outdated"

    def test_version_from_stderr_fallback(self):
        """If stdout is empty, health check should use stderr."""
        with (
            patch("cli_rosetta.health.shutil.which", return_value="/usr/bin/codex"),
            patch("cli_rosetta.health.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                stdout="",
                stderr=f"codex {CODEX_CLI.known_version}\n",
            )
            result = check_one(CODEX_CLI)
        assert result.current_version == CODEX_CLI.known_version

    def test_timeout_results_in_empty_version(self):
        """subprocess.TimeoutExpired must be caught; version stays empty."""
        import subprocess as sp

        with (
            patch("cli_rosetta.health.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "cli_rosetta.health.subprocess.run",
                side_effect=sp.TimeoutExpired(cmd="claude", timeout=10),
            ),
        ):
            result = check_one(CLAUDE_CODE)

        # Should still be installed (binary was found), but version unknown
        assert result.installed is True
        assert result.current_version == ""
        # outdated requires both known_version AND current_version — empty version → not outdated
        assert result.outdated is False


# ══════════════════════════════════════════════════════════════════════════════
# Section 5 — headless_cmd deeper validation
# ══════════════════════════════════════════════════════════════════════════════


class TestHeadlessCmdContents:
    def test_prompt_appears_in_cmd(self):
        for e in _all_entries():
            prompt = "do something useful"
            cmd = e.headless_cmd(prompt)
            assert prompt in cmd, (
                f"{e.name}: prompt '{prompt}' not found in headless_cmd output {cmd}"
            )

    def test_model_flag_and_value_both_present(self):
        for e in _all_entries():
            cmd = e.headless_cmd("test", model="my-model")
            assert e.model_flag in cmd, (
                f"{e.name}: model_flag '{e.model_flag}' missing from cmd {cmd}"
            )
            assert "my-model" in cmd

    def test_auto_approve_flag_injected_when_flag_nonempty(self):
        """For CLIs with a non-empty auto_approve.flag, auto_approve=True must inject the flag."""
        for e in _all_entries():
            if not e.auto_approve.flag:
                continue
            cmd_no = e.headless_cmd("test", auto_approve=False)
            cmd_yes = e.headless_cmd("test", auto_approve=True)
            # The auto-approve flag token must appear in cmd_yes but not necessarily in cmd_no
            flag_token = e.auto_approve.flag.split()[0]  # first token of the flag
            assert flag_token in cmd_yes, (
                f"{e.name}: auto_approve flag token '{flag_token}' missing when auto_approve=True"
            )

    def test_codex_headless_includes_exec_subcommand(self):
        """Codex has headless.subcommand='exec' — must appear after binary."""
        cmd = CODEX_CLI.headless_cmd("test prompt")
        assert cmd[0] == "codex"
        assert "exec" in cmd
        # exec must come before the prompt
        exec_idx = cmd.index("exec")
        prompt_idx = cmd.index("test prompt")
        assert exec_idx < prompt_idx, "exec subcommand must precede prompt"

    def test_claude_cwd_flag_injected(self):
        """Claude Code has cwd_flag='--cwd'; passing cwd should inject it."""
        cmd = CLAUDE_CODE.headless_cmd("test", cwd="/tmp/project")
        assert "--cwd" in cmd
        assert "/tmp/project" in cmd

    def test_gemini_no_cwd_flag_cwd_ignored(self):
        """Gemini has no cwd_flag — passing cwd must not inject anything."""
        cmd_no_cwd = GEMINI_CLI.headless_cmd("test")
        cmd_with_cwd = GEMINI_CLI.headless_cmd("test", cwd="/tmp/project")
        # cwd should be ignored (flag is empty)
        assert "/tmp/project" not in cmd_with_cwd
        # cmd should be identical
        assert cmd_no_cwd == cmd_with_cwd


# ══════════════════════════════════════════════════════════════════════════════
# Section 6 — ToolNameMap.to_dict() completeness
# ══════════════════════════════════════════════════════════════════════════════


class TestToolNameMapToDict:
    def test_to_dict_has_all_canonical_keys(self):
        canonical_keys = {
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "Agent",
            "NotebookEdit",
        }
        for e in _all_entries():
            d = e.tool_names.to_dict()
            missing = canonical_keys - set(d.keys())
            assert not missing, f"{e.name}: to_dict() missing keys: {missing}"

    def test_default_tool_name_map_is_identity_for_cc(self):
        """Default ToolNameMap maps CC names to themselves (Claude Code canonical)."""
        tm = ToolNameMap()
        d = tm.to_dict()
        assert d["Read"] == "Read"
        assert d["Write"] == "Write"
        assert d["Edit"] == "Edit"
        assert d["Bash"] == "Bash"

    def test_gemini_tool_names_differ_from_cc(self):
        """Gemini tool names are distinct from CC canonical."""
        d = GEMINI_CLI.tool_names.to_dict()
        assert d["Read"] == "read_file"
        assert d["Edit"] == "edit_file"
        assert d["Bash"] == "run_shell_command"
        assert d["Glob"] == "glob_search"

    def test_codex_no_glob_or_grep_equivalent(self):
        """Codex has no glob or grep equivalent — both map to empty string."""
        d = CODEX_CLI.tool_names.to_dict()
        assert d["Glob"] == "", f"Codex Glob mapping: '{d['Glob']}'"
        assert d["Grep"] == "", f"Codex Grep mapping: '{d['Grep']}'"
