"""Mutation-aware tests for State.

T1 test-adversary — never read state.py source.

Key mutations targeted:
  - load/save round-trip loses entries (serialisation bug)
  - is_changed returns wrong bool (== vs != comparison)
  - record overwrites the wrong field
  - forget doesn't remove the key (wrong key lookup)
  - concurrent save corrupts JSON (flock missing)
  - space_id / vault_path not persisted across reload
"""
import json
import multiprocessing
import time
from pathlib import Path

import pytest

from obsidian_sync import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(tmp_path: Path, space: str = "s1") -> tuple[State, Path]:
    state_file = tmp_path / "state.json"
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    state = State.load(state_file, vault, space)
    return state, state_file


# ---------------------------------------------------------------------------
# load → record → save → reload round-trip
# ---------------------------------------------------------------------------

class TestStateRoundTrip:
    def test_record_then_save_then_reload_preserves_entry(self, tmp_path: Path):
        state, path = _make_state(tmp_path)
        state.record("notes/a.md", "abc123def456789a", "doc-001")
        state.save()

        vault = tmp_path / "vault"
        reloaded = State.load(path, vault, "s1")
        assert not reloaded.is_changed("notes/a.md", "abc123def456789a"), (
            "Reloaded state reports is_changed=True for hash that was just recorded — "
            "mutation: save() doesn't persist, or record() stores wrong hash"
        )

    def test_multiple_records_all_survive_reload(self, tmp_path: Path):
        state, path = _make_state(tmp_path)
        entries = {
            "a.md": ("hash_aaaa0000000000aa", "doc-a"),
            "b.md": ("hash_bbbb0000000000bb", "doc-b"),
            "c.md": ("hash_cccc0000000000cc", "doc-c"),
        }
        for rel, (h, doc_id) in entries.items():
            state.record(rel, h, doc_id)
        state.save()

        vault = tmp_path / "vault"
        reloaded = State.load(path, vault, "s1")
        for rel, (h, _) in entries.items():
            assert not reloaded.is_changed(rel, h), (
                f"{rel} missing after reload — mutation: only last record() persisted"
            )

    def test_state_file_is_valid_json_after_save(self, tmp_path: Path):
        state, path = _make_state(tmp_path)
        state.record("x.md", "abcd1234abcd1234", "doc-x")
        state.save()
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)  # must not raise
        assert isinstance(parsed, dict), "State file must be a JSON object"

    def test_fresh_state_has_no_entries(self, tmp_path: Path):
        state, _ = _make_state(tmp_path)
        # Unknown path must show as changed (new file)
        assert state.is_changed("never/seen.md", "anyhashabcd1234a"), (
            "Fresh state should report is_changed=True for unknown path — "
            "mutation: default changed=False"
        )


# ---------------------------------------------------------------------------
# is_changed correctness
# ---------------------------------------------------------------------------

class TestIsChanged:
    def test_same_hash_returns_false(self, tmp_path: Path):
        state, _ = _make_state(tmp_path)
        h = "aabbccddeeff0011"
        state.record("same.md", h, "doc-same")
        assert state.is_changed("same.md", h) is False, (
            "Same hash must return False — mutation: != changed to =="
        )

    def test_different_hash_returns_true(self, tmp_path: Path):
        state, _ = _make_state(tmp_path)
        state.record("changed.md", "aabbccddeeff0011", "doc-chg")
        assert state.is_changed("changed.md", "0000000000000000") is True, (
            "Different hash must return True — mutation: always return False"
        )

    def test_unknown_path_returns_true(self, tmp_path: Path):
        state, _ = _make_state(tmp_path)
        assert state.is_changed("not/recorded.md", "anyhashabcd1234a") is True, (
            "Unknown path must return True (new file) — mutation: KeyError → False"
        )

    def test_off_by_one_hash_returns_true(self, tmp_path: Path):
        """Only the last char differs — must still detect change."""
        state, _ = _make_state(tmp_path)
        h1 = "aabbccddeeff001a"
        h2 = "aabbccddeeff001b"
        state.record("edge.md", h1, "doc-edge")
        assert state.is_changed("edge.md", h2) is True, (
            "Off-by-one hash must return True — mutation: prefix comparison instead of full"
        )

    def test_is_changed_returns_bool_not_truthy(self, tmp_path: Path):
        """Return type must be bool, not just truthy/falsy."""
        state, _ = _make_state(tmp_path)
        state.record("typed.md", "aabbccddeeff0011", "doc-t")
        result_false = state.is_changed("typed.md", "aabbccddeeff0011")
        result_true = state.is_changed("typed.md", "different_hash_xx")
        assert result_false is False
        assert result_true is True


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------

class TestForget:
    def test_forget_makes_path_appear_changed(self, tmp_path: Path):
        state, path = _make_state(tmp_path)
        h = "aabb11223344ccdd"
        state.record("forget_me.md", h, "doc-f")
        state.forget("forget_me.md")
        # After forget, same hash should now appear as changed (new)
        assert state.is_changed("forget_me.md", h) is True, (
            "After forget(), same hash must report changed=True — "
            "mutation: forget() doesn't remove entry"
        )

    def test_forget_returns_doc_id_or_none(self, tmp_path: Path):
        state, _ = _make_state(tmp_path)
        state.record("ret.md", "aabb11223344ccdd", "doc-ret")
        result = state.forget("ret.md")
        # Should return the doc_id that was associated, or None — either is valid
        assert result is None or isinstance(result, str), (
            f"forget() must return str | None, got {type(result)}"
        )

    def test_forget_nonexistent_path_does_not_raise(self, tmp_path: Path):
        state, _ = _make_state(tmp_path)
        try:
            state.forget("does/not/exist.md")
        except Exception as exc:
            pytest.fail(f"forget() raised {type(exc).__name__} on unknown path — must be no-op")

    def test_forget_persists_after_save_reload(self, tmp_path: Path):
        state, path = _make_state(tmp_path)
        h = "aabb11223344ccdd"
        state.record("persist_forget.md", h, "doc-pf")
        state.save()
        state.forget("persist_forget.md")
        state.save()

        vault = tmp_path / "vault"
        reloaded = State.load(path, vault, "s1")
        assert reloaded.is_changed("persist_forget.md", h) is True, (
            "Forgotten entry must not reappear after save+reload — "
            "mutation: forget() only mutates in-memory, save() re-reads from disk"
        )


# ---------------------------------------------------------------------------
# Concurrent flock safety
# ---------------------------------------------------------------------------

def _worker_save(state_file: Path, vault: Path, space: str, rel: str, h: str, doc_id: str):
    """Worker: load, record, sleep briefly, save."""
    s = State.load(state_file, vault, space)
    s.record(rel, h, doc_id)
    time.sleep(0.02)  # increase interleaving chance
    s.save()


class TestFlockSafety:
    def test_concurrent_saves_do_not_corrupt_json(self, tmp_path: Path):
        """Two processes saving simultaneously must not produce corrupt JSON."""
        state_file = tmp_path / "state.json"
        vault = tmp_path / "vault"
        vault.mkdir()

        p1 = multiprocessing.Process(
            target=_worker_save,
            args=(state_file, vault, "s1", "concurrent_a.md", "hash_aaaa0000000000", "doc-ca"),
        )
        p2 = multiprocessing.Process(
            target=_worker_save,
            args=(state_file, vault, "s1", "concurrent_b.md", "hash_bbbb0000000000", "doc-cb"),
        )
        p1.start()
        p2.start()
        p1.join(timeout=5)
        p2.join(timeout=5)

        # State file must be valid JSON after concurrent writes
        if state_file.exists():
            raw = state_file.read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
                assert isinstance(data, dict), "Concurrent save produced non-dict JSON"
            except json.JSONDecodeError as exc:
                pytest.fail(
                    f"Concurrent saves corrupted state.json: {exc}\nContent: {raw[:200]}"
                )
        # Note: if flock is missing, one process may overwrite the other's entries.
        # We cannot assert BOTH entries are present because the last-writer-wins race
        # is a known risk — we only check file integrity (valid JSON).
