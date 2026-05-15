"""Shared fixtures for obsidian-sync tests.

T1 test-adversary: fixtures build realistic vault structures
from scratch using tmp_path — no mocking of filesystem.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal flat vault: 3 .md files + 1 non-.md file."""
    v = tmp_path / "vault"
    v.mkdir()
    (v / "note_a.md").write_text("# A\nHello", encoding="utf-8")
    (v / "note_b.md").write_text("# B\nWorld", encoding="utf-8")
    (v / "note_c.md").write_text("---\ntitle: C\n---\nBody C", encoding="utf-8")
    (v / "image.png").write_bytes(b"\x89PNG")
    return v


@pytest.fixture()
def nested_vault(tmp_path: Path) -> Path:
    """Vault with sub-directories, including Obsidian internals."""
    v = tmp_path / "nested"
    v.mkdir()
    # regular notes
    (v / "root.md").write_text("root note")
    sub = v / "sub"
    sub.mkdir()
    (sub / "deep.md").write_text("deep note")
    # obsidian internals — must be excluded
    obsidian_dir = v / ".obsidian"
    obsidian_dir.mkdir()
    (obsidian_dir / "config.md").write_text("obsidian config — must be excluded")
    # git dir — must be excluded
    git_dir = v / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main")
    # assets folder — must be excluded
    assets_dir = v / "assets"
    assets_dir.mkdir()
    (assets_dir / "banner.md").write_text("caption — must be excluded")
    return v


@pytest.fixture()
def state_file(tmp_path: Path) -> Path:
    """Empty state file path (does not yet exist on disk)."""
    return tmp_path / "state.json"


@pytest.fixture()
def space_id() -> str:
    return "test-space-001"
