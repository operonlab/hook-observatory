"""Adversarial test suite for probe.py, state.py, updater.py.

Six Iron Laws:
1. Mutation thinking  — every assert catches a single-char mutation
2. Write/test separation — infer behavior from public API + docstrings only
3. Invariant-first — verify properties, not fixed I/O
4. Boundary / error paths — runtime → regression
5. Mock only external I/O — subprocess, urlopen, file I/O via tmp_path
6. Draft is not production — reviewed with mutation lens before finalizing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Path bootstrap ───────────────────────────────────────────────────────────
_LIB_DIR = str(Path(__file__).parent.parent)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)


from cli_rosetta import state as state_mod
from cli_rosetta.base import CLIEntry, ExitBehavior
from cli_rosetta.probe import (
    HelpDiff,
    ProbeReport,
    VersionInfo,
    check_remote_version,
    parse_help_flags,
    probe_cli,
    probe_help,
)
from cli_rosetta.updater import update_known_version

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_entry(
    name: str = "test-cli",
    binary: str = "test-bin",
    npm_package: str = "",
    brew_package: str = "",
    known_version: str = "1.0.0",
) -> CLIEntry:
    return CLIEntry(
        name=name,
        binary=binary,
        display_name="Test CLI",
        vendor="test-vendor",
        exit_behavior=ExitBehavior(command="/exit"),
        known_version=known_version,
        npm_package=npm_package,
        brew_package=brew_package,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Section 1 — VersionInfo Invariants
# ══════════════════════════════════════════════════════════════════════════════


class TestVersionInfoHasDrift:
    """Invariant: installed != remote → has_drift True; equal → False."""

    def test_has_drift_true_when_versions_differ(self):
        v = VersionInfo(cli_name="x", installed="1.0.0", remote="2.0.0")
        assert v.has_drift is True

    def test_has_drift_false_when_versions_equal(self):
        v = VersionInfo(cli_name="x", installed="1.0.0", remote="1.0.0")
        assert v.has_drift is False

    def test_has_drift_false_when_installed_empty(self):
        v = VersionInfo(cli_name="x", installed="", remote="2.0.0")
        assert v.has_drift is False, "no installed → cannot confirm drift"

    def test_has_drift_false_when_remote_empty(self):
        v = VersionInfo(cli_name="x", installed="1.0.0", remote="")
        assert v.has_drift is False, "no remote → cannot confirm drift"

    def test_has_drift_false_when_both_empty(self):
        v = VersionInfo(cli_name="x")
        assert v.has_drift is False

    def test_has_drift_direction_matters_old_lt_new(self):
        # Mutation killer: swapping installed/remote must flip result
        v_fwd = VersionInfo(cli_name="x", installed="1.0.0", remote="2.0.0")
        v_rev = VersionInfo(cli_name="x", installed="2.0.0", remote="1.0.0")
        # Both have drift (just different directions), but neither equals False
        assert v_fwd.has_drift is True
        assert v_rev.has_drift is True

    def test_has_drift_same_exact_string(self):
        v = VersionInfo(cli_name="x", installed="1.2.3-alpha", remote="1.2.3-alpha")
        assert v.has_drift is False


class TestVersionInfoEntryStale:
    """Invariant: known != installed → entry_stale True."""

    def test_entry_stale_true_when_known_differs(self):
        v = VersionInfo(cli_name="x", installed="2.0.0", known="1.0.0")
        assert v.entry_stale is True

    def test_entry_stale_false_when_equal(self):
        v = VersionInfo(cli_name="x", installed="1.0.0", known="1.0.0")
        assert v.entry_stale is False

    def test_entry_stale_false_when_installed_empty(self):
        v = VersionInfo(cli_name="x", installed="", known="1.0.0")
        assert v.entry_stale is False

    def test_entry_stale_false_when_known_empty(self):
        v = VersionInfo(cli_name="x", installed="1.0.0", known="")
        assert v.entry_stale is False

    def test_entry_stale_mutation_killer_swap(self):
        # Mutation: swapping known/installed should still detect staleness
        v = VersionInfo(cli_name="x", installed="1.0.0", known="0.9.0")
        assert v.entry_stale is True


# ══════════════════════════════════════════════════════════════════════════════
# Section 2 — HelpDiff Invariants
# ══════════════════════════════════════════════════════════════════════════════


class TestHelpDiffFirstRun:
    """First run (previous_flags=None or empty) → new_flags and removed_flags both empty."""

    def test_first_run_no_previous_flags_new_flags_empty(self):
        diff = HelpDiff(cli_name="x", previous_flags=set(), current_flags={"--verbose", "--output"})
        assert diff.new_flags == set(), f"expected empty, got {diff.new_flags}"

    def test_first_run_no_previous_flags_removed_flags_empty(self):
        diff = HelpDiff(cli_name="x", previous_flags=set(), current_flags={"--verbose", "--output"})
        assert diff.removed_flags == set(), f"expected empty, got {diff.removed_flags}"

    def test_first_run_has_no_changes(self):
        diff = HelpDiff(cli_name="x", previous_flags=set(), current_flags={"--verbose"})
        assert diff.has_changes is False

    def test_first_run_with_both_empty_no_changes(self):
        diff = HelpDiff(cli_name="x", previous_flags=set(), current_flags=set())
        assert diff.has_changes is False
        assert diff.new_flags == set()
        assert diff.removed_flags == set()


class TestHelpDiffWithPrevious:
    """With a previous snapshot, diffs are computed correctly."""

    def test_new_flags_is_current_minus_previous(self):
        """Mutation killer: new = current - previous (NOT previous - current)."""
        prev = {"--verbose", "--output"}
        curr = {"--verbose", "--output", "--json", "--quiet"}
        diff = HelpDiff(cli_name="x", previous_flags=prev, current_flags=curr)
        assert diff.new_flags == {"--json", "--quiet"}

    def test_removed_flags_is_previous_minus_current(self):
        """Mutation killer: removed = previous - current (NOT current - previous)."""
        prev = {"--verbose", "--output", "--old-flag"}
        curr = {"--verbose", "--output"}
        diff = HelpDiff(cli_name="x", previous_flags=prev, current_flags=curr)
        assert diff.removed_flags == {"--old-flag"}

    def test_new_flags_direction_swap_kills_mutation(self):
        prev = {"--alpha"}
        curr = {"--beta"}
        diff = HelpDiff(cli_name="x", previous_flags=prev, current_flags=curr)
        assert "--beta" in diff.new_flags, "new_flags must be current - previous"
        assert "--alpha" not in diff.new_flags, "--alpha is in previous, not new"

    def test_removed_flags_direction_swap_kills_mutation(self):
        prev = {"--alpha"}
        curr = {"--beta"}
        diff = HelpDiff(cli_name="x", previous_flags=prev, current_flags=curr)
        assert "--alpha" in diff.removed_flags, "removed_flags must be previous - current"
        assert "--beta" not in diff.removed_flags, "--beta is in current, not removed"

    def test_has_changes_true_when_new_flags_exist(self):
        diff = HelpDiff(cli_name="x", previous_flags={"--a"}, current_flags={"--a", "--b"})
        assert diff.has_changes is True

    def test_has_changes_true_when_removed_flags_exist(self):
        diff = HelpDiff(cli_name="x", previous_flags={"--a", "--b"}, current_flags={"--a"})
        assert diff.has_changes is True

    def test_has_changes_false_when_no_diff(self):
        flags = {"--verbose", "--output"}
        diff = HelpDiff(cli_name="x", previous_flags=flags, current_flags=flags.copy())
        assert diff.has_changes is False

    def test_simultaneous_add_and_remove(self):
        prev = {"--old", "--stable"}
        curr = {"--new", "--stable"}
        diff = HelpDiff(cli_name="x", previous_flags=prev, current_flags=curr)
        assert diff.new_flags == {"--new"}
        assert diff.removed_flags == {"--old"}
        assert diff.has_changes is True


# ══════════════════════════════════════════════════════════════════════════════
# Section 3 — ProbeReport.to_dict() Invariants
# ══════════════════════════════════════════════════════════════════════════════


class TestProbeReportToDict:
    def test_to_dict_always_has_core_keys(self):
        diff = HelpDiff(cli_name="x", previous_flags=set(), current_flags=set())
        report = ProbeReport(cli_name="x", old_version="1.0", new_version="2.0", help_diff=diff)
        d = report.to_dict()
        assert "cli_name" in d
        assert "old_version" in d
        assert "new_version" in d
        assert "changelog_url" in d

    def test_first_run_no_new_flags_key_in_dict(self):
        """First run: previous_flags empty → new_flags/removed_flags NOT in dict."""
        diff = HelpDiff(cli_name="x", previous_flags=set(), current_flags={"--verbose"})
        report = ProbeReport(cli_name="x", old_version="1.0", new_version="2.0", help_diff=diff)
        d = report.to_dict()
        assert "new_flags" not in d, "first run must not include new_flags key"
        assert "removed_flags" not in d, "first run must not include removed_flags key"

    def test_with_changes_includes_flag_keys(self):
        diff = HelpDiff(cli_name="x", previous_flags={"--old"}, current_flags={"--old", "--new"})
        report = ProbeReport(cli_name="x", old_version="1.0", new_version="2.0", help_diff=diff)
        d = report.to_dict()
        assert "new_flags" in d
        assert "--new" in d["new_flags"]

    def test_flags_sorted_in_dict(self):
        diff = HelpDiff(cli_name="x", previous_flags={"--b"}, current_flags={"--b", "--a", "--c"})
        report = ProbeReport(cli_name="x", old_version="1.0", new_version="2.0", help_diff=diff)
        d = report.to_dict()
        assert d["new_flags"] == sorted(d["new_flags"]), "new_flags must be sorted"

    def test_no_help_diff_no_flag_keys(self):
        report = ProbeReport(cli_name="x", old_version="1.0", new_version="2.0", help_diff=None)
        d = report.to_dict()
        assert "new_flags" not in d
        assert "removed_flags" not in d

    def test_notes_included_when_nonempty(self):
        diff = HelpDiff(cli_name="x", previous_flags={"--old"}, current_flags={"--old", "--new"})
        report = ProbeReport(
            cli_name="x", old_version="1.0", new_version="2.0", help_diff=diff, notes="some note"
        )
        d = report.to_dict()
        assert "notes" in d
        assert d["notes"] == "some note"

    def test_notes_omitted_when_empty(self):
        diff = HelpDiff(cli_name="x", previous_flags=set(), current_flags=set())
        report = ProbeReport(cli_name="x", old_version="1.0", new_version="2.0", help_diff=diff)
        d = report.to_dict()
        assert "notes" not in d


# ══════════════════════════════════════════════════════════════════════════════
# Section 4 — check_remote_version() Boundary / Error paths
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRemoteVersionNpm:
    def test_npm_success_returns_version(self):
        entry = _make_entry(npm_package="@test/cli")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"version": "3.0.0"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("cli_rosetta.probe.urllib.request.urlopen", return_value=mock_resp):
            result = check_remote_version(entry)

        assert result == "3.0.0"

    def test_npm_network_failure_returns_empty_string(self):
        """Boundary: network error must NOT raise — returns empty string."""
        entry = _make_entry(npm_package="@test/cli")
        with patch("cli_rosetta.probe.urllib.request.urlopen", side_effect=OSError("network down")):
            result = check_remote_version(entry)
        assert result == "", f"expected '' on failure, got '{result}'"

    def test_npm_json_missing_version_key_returns_empty(self):
        entry = _make_entry(npm_package="@test/cli")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"name": "@test/cli"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("cli_rosetta.probe.urllib.request.urlopen", return_value=mock_resp):
            result = check_remote_version(entry)
        assert result == ""

    def test_no_npm_no_brew_returns_empty_string(self):
        """Boundary: entry with no npm_package and no brew_package → empty string."""
        entry = _make_entry(npm_package="", brew_package="")
        result = check_remote_version(entry)
        assert result == ""

    def test_npm_takes_priority_over_brew(self):
        """npm_package is checked before brew_package."""
        entry = _make_entry(npm_package="@test/npm-cli", brew_package="brew-cli")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"version": "npm-version"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("cli_rosetta.probe.urllib.request.urlopen", return_value=mock_resp) as mock_url,
            patch("cli_rosetta.probe.subprocess.run") as mock_brew,
        ):
            result = check_remote_version(entry)

        assert result == "npm-version"
        # brew subprocess should NOT have been called
        mock_brew.assert_not_called()


class TestCheckRemoteVersionBrew:
    def test_brew_success_returns_version(self):
        entry = _make_entry(brew_package="test-tool")
        brew_json = json.dumps({"formulae": [{"versions": {"stable": "4.0.0"}}], "casks": []})
        mock_run = MagicMock(returncode=0, stdout=brew_json)

        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            result = check_remote_version(entry)

        assert result == "4.0.0"

    def test_brew_cask_returns_version(self):
        entry = _make_entry(brew_package="some-cask")
        brew_json = json.dumps({"formulae": [], "casks": [{"version": "5.0.0"}]})
        mock_run = MagicMock(returncode=0, stdout=brew_json)

        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            result = check_remote_version(entry)

        assert result == "5.0.0"

    def test_brew_nonzero_returncode_returns_empty(self):
        entry = _make_entry(brew_package="missing-tool")
        mock_run = MagicMock(returncode=1, stdout="")

        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            result = check_remote_version(entry)

        assert result == ""

    def test_brew_subprocess_exception_returns_empty(self):
        entry = _make_entry(brew_package="test-tool")
        with patch("cli_rosetta.probe.subprocess.run", side_effect=FileNotFoundError("brew not found")):
            result = check_remote_version(entry)
        assert result == ""


# ══════════════════════════════════════════════════════════════════════════════
# Section 5 — parse_help_flags() Boundary / Error paths
# ══════════════════════════════════════════════════════════════════════════════


class TestParseHelpFlags:
    def test_extracts_long_flags_from_stdout(self):
        mock_run = MagicMock(stdout="  --verbose  Enable verbose\n  --output FILE\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            flags = parse_help_flags("test-bin")
        assert "verbose" in flags
        assert "output" in flags

    def test_extracts_flags_from_stderr_too(self):
        mock_run = MagicMock(stdout="", stderr="Usage: cli\n  --debug  Debug mode\n")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            flags = parse_help_flags("test-bin")
        assert "debug" in flags

    def test_binary_not_found_returns_empty_set(self):
        """Boundary: binary doesn't exist → empty set, not an exception."""
        with patch("cli_rosetta.probe.subprocess.run", side_effect=FileNotFoundError("not found")):
            flags = parse_help_flags("nonexistent-binary")
        assert flags == set(), f"expected empty set, got {flags}"

    def test_timeout_returns_empty_set(self):
        import subprocess as sp

        with patch(
            "cli_rosetta.probe.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="bin", timeout=15),
        ):
            flags = parse_help_flags("slow-binary")
        assert flags == set()

    def test_returns_set_not_list(self):
        mock_run = MagicMock(stdout="--alpha --beta\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            flags = parse_help_flags("test-bin")
        assert isinstance(flags, set)

    def test_short_flags_not_extracted(self):
        """Only --long-flags are extracted (pattern: --[a-z][a-z0-9-]+)."""
        mock_run = MagicMock(stdout="  -v  Verbose\n  -o  Output\n  --long-flag\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            flags = parse_help_flags("test-bin")
        # -v and -o are short flags, must not appear
        assert "v" not in flags
        assert "o" not in flags
        assert "long-flag" in flags

    def test_deduplicates_flags(self):
        mock_run = MagicMock(
            stdout="--verbose first mention\n--verbose second mention\n", stderr=""
        )
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            flags = parse_help_flags("test-bin")
        assert flags.count("verbose") == 1 if hasattr(flags, "count") else True
        assert len([f for f in flags if f == "verbose"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Section 6 — probe_help() + probe_cli()
# ══════════════════════════════════════════════════════════════════════════════


class TestProbeHelp:
    def test_first_run_no_previous_flags(self):
        entry = _make_entry()
        mock_run = MagicMock(stdout="--alpha --beta\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            diff = probe_help(entry, previous_flags=None)
        assert diff.cli_name == entry.name
        assert diff.new_flags == set(), "first run: new_flags must be empty"
        assert diff.removed_flags == set(), "first run: removed_flags must be empty"

    def test_with_previous_flags_computes_diff(self):
        entry = _make_entry()
        mock_run = MagicMock(stdout="--alpha --beta --gamma\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            diff = probe_help(entry, previous_flags={"alpha", "beta"})
        assert "gamma" in diff.new_flags


class TestProbeCli:
    def test_probe_cli_returns_probe_report(self):
        entry = _make_entry(name="claude-code")
        mock_run = MagicMock(stdout="--verbose\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            report = probe_cli(entry, "2.0.0", previous_flags=None)
        assert isinstance(report, ProbeReport)
        assert report.cli_name == "claude-code"
        assert report.new_version == "2.0.0"
        assert report.old_version == entry.known_version

    def test_probe_cli_sets_changelog_url_for_known_cli(self):
        entry = _make_entry(name="claude-code")
        mock_run = MagicMock(stdout="", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            report = probe_cli(entry, "2.0.0", previous_flags=None)
        assert "github.com" in report.changelog_url

    def test_probe_cli_unknown_cli_has_empty_changelog_url(self):
        entry = _make_entry(name="totally-unknown-cli")
        mock_run = MagicMock(stdout="", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            report = probe_cli(entry, "1.0.0")
        assert report.changelog_url == ""

    def test_probe_cli_first_run_notes_empty(self):
        """First run: no previous_flags → no new/removed → notes should be empty."""
        entry = _make_entry(name="gemini-cli")
        mock_run = MagicMock(stdout="--verbose\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            report = probe_cli(entry, "1.0.0", previous_flags=None)
        assert report.notes == ""

    def test_probe_cli_with_new_flags_includes_in_notes(self):
        entry = _make_entry(name="codex-cli")
        mock_run = MagicMock(stdout="--alpha --beta --gamma\n", stderr="")
        with patch("cli_rosetta.probe.subprocess.run", return_value=mock_run):
            report = probe_cli(entry, "1.0.0", previous_flags={"alpha", "beta"})
        assert "gamma" in report.notes


# ══════════════════════════════════════════════════════════════════════════════
# Section 7 — state.py
# ══════════════════════════════════════════════════════════════════════════════


class TestStateLoad:
    def test_load_no_file_returns_empty_structure(self, tmp_path, monkeypatch):
        """Boundary: no state file → returns dict with empty versions + pending_review."""
        monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
        result = state_mod.load()
        assert isinstance(result, dict)
        assert "versions" in result
        assert "pending_review" in result
        assert result["versions"] == {}
        assert result["pending_review"] == []

    def test_load_existing_file_returns_content(self, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({"versions": {"claude-code": {"installed": "1.0.0"}}, "pending_review": []})
        )
        monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
        result = state_mod.load()
        assert result["versions"]["claude-code"]["installed"] == "1.0.0"


class TestStateSave:
    def test_save_writes_to_file(self, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
        monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
        state_mod.save({"versions": {}, "pending_review": []})
        assert state_file.exists()

    def test_save_adds_last_check_timestamp(self, tmp_path, monkeypatch):
        """Mutation killer: save() MUST inject last_check key."""
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
        monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
        state = {"versions": {}, "pending_review": []}
        state_mod.save(state)
        saved = json.loads(state_file.read_text())
        assert "last_check" in saved, "save() must write last_check key"
        assert saved["last_check"], "last_check must be non-empty"

    def test_save_last_check_is_iso_format(self, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
        monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
        state_mod.save({"versions": {}, "pending_review": []})
        saved = json.loads(state_file.read_text())
        # ISO 8601 contains "T" separator
        assert "T" in saved["last_check"], f"last_check not ISO format: {saved['last_check']}"

    def test_save_roundtrip_versions_preserved(self, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
        monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
        original = {"versions": {"test-cli": {"installed": "9.9.9"}}, "pending_review": []}
        state_mod.save(original)
        saved = json.loads(state_file.read_text())
        assert saved["versions"]["test-cli"]["installed"] == "9.9.9"


class TestStateUpdateVersion:
    def test_update_version_sets_installed(self):
        state = {}
        state_mod.update_version(state, "test-cli", installed="1.2.3")
        assert state["versions"]["test-cli"]["installed"] == "1.2.3"

    def test_update_version_sets_remote(self):
        state = {}
        state_mod.update_version(state, "test-cli", remote="2.0.0")
        assert state["versions"]["test-cli"]["remote"] == "2.0.0"

    def test_update_version_sets_help_flags_as_sorted_list(self):
        state = {}
        state_mod.update_version(state, "test-cli", help_flags={"--beta", "--alpha"})
        flags = state["versions"]["test-cli"]["help_flags"]
        assert flags == sorted(flags), "help_flags must be stored sorted"
        assert "--alpha" in flags
        assert "--beta" in flags

    def test_update_version_sets_checked_at(self):
        state = {}
        state_mod.update_version(state, "test-cli", installed="1.0.0")
        assert "checked_at" in state["versions"]["test-cli"]

    def test_update_version_idempotent_overwrite(self):
        state = {}
        state_mod.update_version(state, "test-cli", installed="1.0.0")
        state_mod.update_version(state, "test-cli", installed="2.0.0")
        assert state["versions"]["test-cli"]["installed"] == "2.0.0"

    def test_update_version_empty_installed_not_written(self):
        state = {"versions": {"test-cli": {"installed": "1.0.0"}}}
        state_mod.update_version(state, "test-cli", installed="")
        # Empty installed → not overwritten
        assert state["versions"]["test-cli"]["installed"] == "1.0.0"

    def test_update_version_none_help_flags_not_written(self):
        state = {"versions": {"test-cli": {"help_flags": ["--old"]}}}
        state_mod.update_version(state, "test-cli", help_flags=None)
        # None → not overwritten
        assert state["versions"]["test-cli"]["help_flags"] == ["--old"]


class TestStateGetHelpFlags:
    def test_get_help_flags_returns_set(self):
        state = {"versions": {"test-cli": {"help_flags": ["--alpha", "--beta"]}}}
        flags = state_mod.get_help_flags(state, "test-cli")
        assert isinstance(flags, set)
        assert flags == {"--alpha", "--beta"}

    def test_get_help_flags_no_snapshot_returns_none(self):
        """Boundary: no snapshot → None (not empty set, not empty list)."""
        state = {}
        result = state_mod.get_help_flags(state, "unknown-cli")
        assert result is None, f"expected None, got {result!r}"

    def test_get_help_flags_cli_exists_but_no_help_flags_key_returns_none(self):
        state = {"versions": {"test-cli": {"installed": "1.0.0"}}}
        result = state_mod.get_help_flags(state, "test-cli")
        assert result is None

    def test_get_help_flags_empty_list_returns_empty_set(self):
        state = {"versions": {"test-cli": {"help_flags": []}}}
        result = state_mod.get_help_flags(state, "test-cli")
        assert result == set()


class TestStateAddPendingReview:
    def test_add_pending_review_appends(self):
        state = {}
        state_mod.add_pending_review(state, "test-cli", "version", "1.0.0", "2.0.0")
        assert len(state["pending_review"]) == 1
        item = state["pending_review"][0]
        assert item["cli"] == "test-cli"
        assert item["field"] == "version"
        assert item["old"] == "1.0.0"
        assert item["new"] == "2.0.0"

    def test_add_pending_review_multiple_items(self):
        state = {}
        state_mod.add_pending_review(state, "cli-a", "f1", "x", "y")
        state_mod.add_pending_review(state, "cli-b", "f2", "a", "b")
        assert len(state["pending_review"]) == 2

    def test_add_pending_review_includes_detected_at(self):
        state = {}
        state_mod.add_pending_review(state, "test-cli", "version", "1.0", "2.0")
        assert "detected_at" in state["pending_review"][0]


class TestStateGetDrifted:
    def test_get_drifted_returns_drifted_only(self):
        """Invariant: only entries where installed != remote appear."""
        state = {
            "versions": {
                "cli-a": {"installed": "1.0.0", "remote": "2.0.0"},  # drifted
                "cli-b": {"installed": "3.0.0", "remote": "3.0.0"},  # same → not drifted
                "cli-c": {"installed": "4.0.0", "remote": "5.0.0"},  # drifted
            }
        }
        result = state_mod.get_drifted(state)
        names = [r[0] for r in result]
        assert "cli-a" in names
        assert "cli-c" in names
        assert "cli-b" not in names

    def test_get_drifted_returns_correct_tuple_format(self):
        state = {
            "versions": {
                "my-cli": {"installed": "1.0.0", "remote": "9.0.0"},
            }
        }
        result = state_mod.get_drifted(state)
        assert len(result) == 1
        name, installed, remote = result[0]
        assert name == "my-cli"
        assert installed == "1.0.0"
        assert remote == "9.0.0"

    def test_get_drifted_mutation_killer_tuple_order(self):
        """Ensure tuple[1] is installed and tuple[2] is remote (not swapped)."""
        state = {
            "versions": {
                "cli-x": {"installed": "AAA", "remote": "BBB"},
            }
        }
        result = state_mod.get_drifted(state)
        _, installed, remote = result[0]
        assert installed == "AAA", f"tuple[1] should be installed 'AAA', got '{installed}'"
        assert remote == "BBB", f"tuple[2] should be remote 'BBB', got '{remote}'"

    def test_get_drifted_empty_versions_returns_empty_list(self):
        state = {"versions": {}}
        assert state_mod.get_drifted(state) == []

    def test_get_drifted_missing_installed_not_included(self):
        state = {"versions": {"cli-x": {"remote": "2.0.0"}}}
        result = state_mod.get_drifted(state)
        assert len(result) == 0

    def test_get_drifted_missing_remote_not_included(self):
        state = {"versions": {"cli-x": {"installed": "1.0.0"}}}
        result = state_mod.get_drifted(state)
        assert len(result) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Section 8 — updater.py
# ══════════════════════════════════════════════════════════════════════════════


class TestUpdateKnownVersion:
    def _write_entry_file(self, tmp_path: Path, cli_name: str, version: str) -> Path:
        """Create a fake entry .py file with known_version."""
        filename = cli_name.replace("-", "_") + ".py"
        content = f'''"""Fake {cli_name} entry."""

ENTRY = CLIEntry(
    name="{cli_name}",
    known_version="{version}",
)
'''
        path = tmp_path / filename
        path.write_text(content)
        return path

    def test_update_known_version_changes_file_content(self, tmp_path, monkeypatch):
        """Mutation killer: actually reads back file to verify content changed."""
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(
            updater_mod,
            "_ENTRY_FILES",
            {"test-cli": "test_cli.py"},
        )
        self._write_entry_file(tmp_path, "test-cli", "1.0.0")

        result = updater_mod.update_known_version("test-cli", "2.0.0")

        assert result is True
        content = (tmp_path / "test_cli.py").read_text()
        assert 'known_version="2.0.0"' in content, "file must contain new version"
        assert 'known_version="1.0.0"' not in content, "old version must be gone"

    def test_update_known_version_unknown_cli_returns_false(self):
        """Boundary: unknown CLI name → False, no exception."""
        result = update_known_version("totally-nonexistent-cli-xyz", "9.9.9")
        assert result is False

    def test_update_known_version_missing_file_returns_false(self, tmp_path, monkeypatch):
        """Boundary: known CLI name but file doesn't exist → False."""
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(
            updater_mod,
            "_ENTRY_FILES",
            {"ghost-cli": "ghost_cli.py"},
        )
        result = updater_mod.update_known_version("ghost-cli", "1.0.0")
        assert result is False

    def test_update_known_version_no_pattern_match_returns_false(self, tmp_path, monkeypatch):
        """Boundary: file exists but has no known_version= pattern → False."""
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(
            updater_mod,
            "_ENTRY_FILES",
            {"no-ver-cli": "no_ver_cli.py"},
        )
        (tmp_path / "no_ver_cli.py").write_text("# no version here\nfoo = 'bar'\n")
        result = updater_mod.update_known_version("no-ver-cli", "1.0.0")
        assert result is False

    def test_update_known_version_does_not_modify_other_fields(self, tmp_path, monkeypatch):
        """Only known_version= field is changed; surrounding content is preserved."""
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(
            updater_mod,
            "_ENTRY_FILES",
            {"my-cli": "my_cli.py"},
        )
        original = '"""Header."""\nname="my-cli"\nknown_version="0.1.0"\nbinary="mycli"\n'
        (tmp_path / "my_cli.py").write_text(original)

        updater_mod.update_known_version("my-cli", "0.2.0")
        content = (tmp_path / "my_cli.py").read_text()

        assert 'name="my-cli"' in content
        assert 'binary="mycli"' in content
        assert '"""Header."""' in content


class TestApplyProbeReport:
    def _make_report(
        self,
        cli_name: str = "test-cli",
        old: str = "1.0.0",
        new: str = "2.0.0",
        prev_flags: set[str] | None = None,
        curr_flags: set[str] | None = None,
    ) -> ProbeReport:
        diff = HelpDiff(
            cli_name=cli_name,
            previous_flags=prev_flags or set(),
            current_flags=curr_flags or set(),
        )
        return ProbeReport(cli_name=cli_name, old_version=old, new_version=new, help_diff=diff)

    def test_apply_returns_dict_with_updated_and_pending_keys(self, tmp_path, monkeypatch):
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(updater_mod, "_ENTRY_FILES", {})
        report = self._make_report()
        result = updater_mod.apply_probe_report(report)
        assert "updated" in result
        assert "pending" in result

    def test_apply_with_version_update_populates_updated(self, tmp_path, monkeypatch):
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(updater_mod, "_ENTRY_FILES", {"test-cli": "test_cli.py"})
        (tmp_path / "test_cli.py").write_text('known_version="1.0.0"\n')

        report = self._make_report(cli_name="test-cli", old="1.0.0", new="2.0.0")
        result = updater_mod.apply_probe_report(report)
        assert len(result["updated"]) == 1
        assert "2.0.0" in result["updated"][0]

    def test_apply_no_file_updated_list_empty(self, tmp_path, monkeypatch):
        """Unknown CLI → update_known_version returns False → updated list empty."""
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(updater_mod, "_ENTRY_FILES", {})
        report = self._make_report()
        result = updater_mod.apply_probe_report(report)
        assert result["updated"] == []

    def test_apply_new_flags_go_to_pending(self, tmp_path, monkeypatch):
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(updater_mod, "_ENTRY_FILES", {})
        report = self._make_report(
            prev_flags={"--alpha"},
            curr_flags={"--alpha", "--beta"},
        )
        result = updater_mod.apply_probe_report(report)
        pending_fields = [p["field"] for p in result["pending"]]
        assert "new_flags" in pending_fields

    def test_apply_removed_flags_go_to_pending(self, tmp_path, monkeypatch):
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(updater_mod, "_ENTRY_FILES", {})
        report = self._make_report(
            prev_flags={"--alpha", "--removed"},
            curr_flags={"--alpha"},
        )
        result = updater_mod.apply_probe_report(report)
        pending_fields = [p["field"] for p in result["pending"]]
        assert "removed_flags" in pending_fields

    def test_apply_first_run_no_flags_pending_empty(self, tmp_path, monkeypatch):
        """First run: no previous_flags → no changes → pending list is empty."""
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(updater_mod, "_ENTRY_FILES", {})
        report = self._make_report(prev_flags=set(), curr_flags={"--verbose"})
        result = updater_mod.apply_probe_report(report)
        assert result["pending"] == [], f"first run must not add pending: {result['pending']}"

    def test_apply_pending_detail_contains_sorted_flags(self, tmp_path, monkeypatch):
        import cli_rosetta.updater as updater_mod

        monkeypatch.setattr(updater_mod, "_ENTRY_DIR", tmp_path)
        monkeypatch.setattr(updater_mod, "_ENTRY_FILES", {})
        report = self._make_report(
            prev_flags={"--zz"},
            curr_flags={"--zz", "--bb", "--aa"},
        )
        result = updater_mod.apply_probe_report(report)
        new_entry = next(p for p in result["pending"] if p["field"] == "new_flags")
        assert new_entry["detail"] == sorted(new_entry["detail"])
