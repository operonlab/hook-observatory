"""Mutation-aware tests for walk_vault and compute_hash.

T1 test-adversary: tests written without reading walker.py source.
Each assertion is designed to catch concrete mutation bugs:
  - sort order swap / unstable sort
  - off-by-one in glob pattern
  - wrong skip predicate (> vs >=, is vs ==)
  - hash truncation error (15 vs 16 chars)
  - collision between different byte sequences
  - returning Path objects vs strings
"""
import hashlib
import os
from pathlib import Path

import pytest

from obsidian_sync import compute_hash, walk_vault


# ---------------------------------------------------------------------------
# walk_vault — sorting invariant
# ---------------------------------------------------------------------------


class TestWalkVaultSorting:
    """Two consecutive calls on same vault must return identical order."""

    def test_sort_is_stable_across_calls(self, nested_vault: Path):
        first = list(walk_vault(nested_vault))
        second = list(walk_vault(nested_vault))
        assert first == second, (
            "walk_vault order is non-deterministic between calls — "
            "sort is not stable (mutation: sorted() removed or rel_path key wrong)"
        )

    def test_sort_is_by_relative_path_lexicographic(self, tmp_path: Path):
        """Sorted by relpath means 'a/z.md' < 'b/a.md' < 'root.md'."""
        v = tmp_path / "lex"
        v.mkdir()
        (v / "root.md").write_text("r")
        b_dir = v / "b"
        b_dir.mkdir()
        (b_dir / "a.md").write_text("b/a")
        a_dir = v / "a"
        a_dir.mkdir()
        (a_dir / "z.md").write_text("a/z")

        paths = list(walk_vault(v))
        rel_paths = [str(p.relative_to(v)) for p in paths]
        assert rel_paths == sorted(rel_paths), (
            f"walk_vault order {rel_paths} is not lexicographically sorted — "
            "mutation: sort key uses absolute path instead of relative path"
        )


# ---------------------------------------------------------------------------
# walk_vault — exclusion invariant
# ---------------------------------------------------------------------------


class TestWalkVaultExclusions:
    """Internal directories must be completely excluded."""

    def test_excludes_obsidian_directory(self, nested_vault: Path):
        paths = list(walk_vault(nested_vault))
        for p in paths:
            assert ".obsidian" not in p.parts, (
                f"{p} is inside .obsidian — mutation: skip condition uses '!=' instead of 'not in'"
            )

    def test_excludes_git_directory(self, nested_vault: Path):
        paths = list(walk_vault(nested_vault))
        for p in paths:
            assert ".git" not in p.parts, (
                f"{p} is inside .git — mutation: .git missing from skip set"
            )

    def test_excludes_assets_directory(self, nested_vault: Path):
        paths = list(walk_vault(nested_vault))
        for p in paths:
            assert "assets" not in p.parts, (
                f"{p} is inside assets/ — mutation: assets/ missing from skip set"
            )

    def test_only_yields_md_files(self, vault: Path):
        """Non-.md files must never appear."""
        paths = list(walk_vault(vault))
        for p in paths:
            assert p.suffix == ".md", (
                f"{p} is not a .md file — mutation: glob pattern too broad"
            )
        assert len(paths) > 0, "walk_vault returned empty — glob pattern too narrow"

    def test_all_md_files_are_yielded(self, nested_vault: Path):
        """Every .md in the vault root and sub-directories must appear (excluding internals)."""
        paths = set(walk_vault(nested_vault))
        # root.md and sub/deep.md must be present
        assert nested_vault / "root.md" in paths, (
            "root.md not yielded — mutation: rglob('*.md') changed to glob('*.md')"
        )
        assert nested_vault / "sub" / "deep.md" in paths, (
            "sub/deep.md not yielded — mutation: recursion missing"
        )
        # internal .md files must NOT be present
        assert nested_vault / ".obsidian" / "config.md" not in paths
        assert nested_vault / "assets" / "banner.md" not in paths

    def test_empty_vault_returns_empty(self, tmp_path: Path):
        """Empty vault must yield nothing, not raise."""
        v = tmp_path / "empty"
        v.mkdir()
        result = list(walk_vault(v))
        assert result == [], (
            "Empty vault should return empty list — mutation: initial check missing"
        )

    def test_yields_path_objects_not_strings(self, vault: Path):
        """All yielded values must be Path instances, not strings."""
        for p in walk_vault(vault):
            assert isinstance(p, Path), (
                f"Expected Path, got {type(p)} — mutation: Path() wrapper removed"
            )

    def test_vault_with_only_internal_dirs_returns_empty(self, tmp_path: Path):
        """Vault containing only .obsidian/ and assets/ must yield nothing."""
        v = tmp_path / "internal_only"
        v.mkdir()
        obsidian = v / ".obsidian"
        obsidian.mkdir()
        (obsidian / "workspace.md").write_text("internal")
        assets = v / "assets"
        assets.mkdir()
        (assets / "cover.md").write_text("cover")
        result = list(walk_vault(v))
        assert result == [], (
            "Internal-only vault must yield nothing — "
            "mutation: exclusion check is suffix-based not directory-based"
        )


# ---------------------------------------------------------------------------
# walk_vault — count invariant
# ---------------------------------------------------------------------------


class TestWalkVaultCount:
    def test_exact_count_matches_md_outside_internals(self, tmp_path: Path):
        """Walk must yield exactly the .md files not inside excluded dirs."""
        v = tmp_path / "count_vault"
        v.mkdir()
        (v / "n1.md").write_text("1")
        (v / "n2.md").write_text("2")
        sub = v / "notes"
        sub.mkdir()
        (sub / "n3.md").write_text("3")
        (sub / "n4.md").write_text("4")
        internal = v / ".obsidian"
        internal.mkdir()
        (internal / "hidden.md").write_text("x")

        paths = list(walk_vault(v))
        # Exactly 4 files: n1, n2, notes/n3, notes/n4
        assert len(paths) == 4, (
            f"Expected 4, got {len(paths)} — mutation: exclusion skips whole dir vs. per-file check"
        )


# ---------------------------------------------------------------------------
# compute_hash — determinism invariant
# ---------------------------------------------------------------------------


class TestComputeHash:
    def test_same_file_same_hash(self, tmp_path: Path):
        f = tmp_path / "stable.md"
        f.write_text("stable content", encoding="utf-8")
        h1 = compute_hash(f)
        h2 = compute_hash(f)
        assert h1 == h2, (
            "compute_hash is non-deterministic — mutation: randomness injected"
        )

    def test_hash_length_is_exactly_16(self, tmp_path: Path):
        f = tmp_path / "len_test.md"
        f.write_text("length test", encoding="utf-8")
        h = compute_hash(f)
        assert len(h) == 16, (
            f"Hash length {len(h)} != 16 — mutation: [:16] changed to [:15] or [:32]"
        )

    def test_hash_is_hex_string(self, tmp_path: Path):
        f = tmp_path / "hex_test.md"
        f.write_text("hex test", encoding="utf-8")
        h = compute_hash(f)
        assert all(c in "0123456789abcdef" for c in h), (
            f"Hash '{h}' contains non-hex chars — mutation: digest() instead of hexdigest()"
        )

    def test_hash_matches_sha256_prefix(self, tmp_path: Path):
        """compute_hash must match sha256(bytes).hexdigest()[:16]."""
        content = "known content for cross-check"
        f = tmp_path / "cross.md"
        f.write_bytes(content.encode("utf-8"))
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        actual = compute_hash(f)
        assert actual == expected, (
            f"Hash mismatch: expected {expected}, got {actual} — "
            "mutation: uses sha1/md5 instead of sha256, or wrong slice"
        )

    def test_different_content_different_hash(self, tmp_path: Path):
        """Even 1-byte difference must produce different hash."""
        f1 = tmp_path / "content_a.md"
        f2 = tmp_path / "content_b.md"
        f1.write_bytes(b"Hello, World!")
        f2.write_bytes(b"Hello, World?")
        h1 = compute_hash(f1)
        h2 = compute_hash(f2)
        assert h1 != h2, (
            "Different content produced same hash — "
            "mutation: hash function returns constant or ignores content"
        )

    def test_hash_uses_bytes_not_text(self, tmp_path: Path):
        """Hash must be computed on raw bytes so encoding variations matter."""
        content_utf8 = "日本語テスト"
        f_utf8 = tmp_path / "utf8.md"
        f_latin = tmp_path / "latin.md"
        f_utf8.write_bytes(content_utf8.encode("utf-8"))
        # Same text encoded differently (UTF-16) → different bytes → different hash
        f_latin.write_bytes(content_utf8.encode("utf-16"))
        h1 = compute_hash(f_utf8)
        h2 = compute_hash(f_latin)
        assert h1 != h2, (
            "UTF-8 vs UTF-16 encoding produced same hash — "
            "mutation: file read with .read_text() strips encoding differences"
        )

    @pytest.mark.parametrize("seed", [b"alpha", b"beta", b"gamma delta epsilon", b"\x00\xff\xfe\xfd"])
    def test_randomized_collision_resistance(self, tmp_path: Path, seed: bytes):
        """Distinct byte sequences must not collide on first 16 hex chars."""
        f1 = tmp_path / f"r1_{seed.hex()[:4]}.md"
        f2 = tmp_path / f"r2_{seed.hex()[:4]}.md"
        f1.write_bytes(seed)
        f2.write_bytes(seed + b"\x01")
        assert compute_hash(f1) != compute_hash(f2), (
            f"Collision for seed {seed!r} — unexpected hash equality"
        )

    def test_empty_file_hash_is_valid_16_hex(self, tmp_path: Path):
        """Empty file must produce a valid 16-hex hash, not raise or return ''."""
        f = tmp_path / "empty.md"
        f.write_bytes(b"")
        h = compute_hash(f)
        assert isinstance(h, str)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_large_file_does_not_raise(self, tmp_path: Path):
        """100 KB file must hash without error."""
        f = tmp_path / "large.md"
        f.write_bytes(b"x" * 100_000)
        h = compute_hash(f)
        assert len(h) == 16
