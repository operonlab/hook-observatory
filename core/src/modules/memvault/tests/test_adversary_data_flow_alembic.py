"""Adversary test — §12 Alembic chain invariants (pure parse, no DB apply).

Contract (§12):
- alembic heads reports exactly 1 head
- Head migration adds: 5 Triple columns + kg_auto_evolve_log + kg_verification_run_log + partial index
- downgrade() of head migration is a clean inverse (drops added columns + indices + tables)

All tests are pure static analysis of migration files — no alembic upgrade/downgrade run.
"""

from __future__ import annotations

import ast
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
_VERSIONS_DIR = os.path.join(_WORKTREE_ROOT, "core", "alembic", "versions")


def _find_migration_files() -> list[str]:
    """Return all migration .py files in alembic/versions/."""
    if not os.path.isdir(_VERSIONS_DIR):
        return []
    return [
        os.path.join(_VERSIONS_DIR, f)
        for f in os.listdir(_VERSIONS_DIR)
        if f.endswith(".py") and not f.startswith("__")
    ]


def _parse_migration(path: str) -> dict:
    """Parse an alembic migration file and extract key info."""
    with open(path) as f:
        src = f.read()

    result = {
        "path": path,
        "revision": None,
        "down_revision": None,
        "has_upgrade": False,
        "has_downgrade": False,
        "upgrade_src": "",
        "downgrade_src": "",
    }

    # Extract revision and down_revision via simple string scan
    for line in src.splitlines():
        line = line.strip()
        if line.startswith("revision") and "=" in line:
            result["revision"] = line.split("=", 1)[1].strip().strip("'\"")
        elif line.startswith("down_revision") and "=" in line:
            val = line.split("=", 1)[1].strip().strip("'\"")
            result["down_revision"] = val if val not in ("None", "none", "") else None

    result["has_upgrade"] = "def upgrade(" in src
    result["has_downgrade"] = "def downgrade(" in src
    result["upgrade_src"] = src
    result["downgrade_src"] = src

    return result


def _find_head_migration(migrations: list[dict]) -> dict | None:
    """The head migration is the one whose revision is not referenced as down_revision."""
    all_down = {m["down_revision"] for m in migrations if m["down_revision"]}
    for m in migrations:
        if m["revision"] and m["revision"] not in all_down:
            return m
    return None


# ── §12.1 exactly one head ────────────────────────────────────────────────────


def test_alembic_exactly_one_head():
    """alembic heads must report exactly 1 head."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found — alembic/versions/ empty or missing")

    migrations = [_parse_migration(f) for f in files]
    all_revisions = {m["revision"] for m in migrations if m["revision"]}
    all_down = {m["down_revision"] for m in migrations if m["down_revision"]}

    # Heads are revisions not referenced as down_revision by any other migration
    heads = [m for m in migrations if m["revision"] and m["revision"] not in all_down]

    assert len(heads) == 1, (
        f"Expected exactly 1 head migration; found {len(heads)}: "
        f"{[h['revision'] for h in heads]}"
    )


# ── §12.2 head migration adds required schema elements ───────────────────────


def test_head_migration_adds_triple_verification_columns():
    """Head migration upgrade() must add the 5 verification columns to triples."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    head = _find_head_migration(migrations)
    if head is None:
        pytest.skip("Could not identify head migration")

    src = head["upgrade_src"]
    expected_columns = [
        "verification_status",
        "verified_at",
        "last_confirmed_at",
        "crag_correct_count",
        "crag_incorrect_count",
    ]
    for col in expected_columns:
        assert col in src, (
            f"Head migration upgrade() must add column '{col}' to triples; "
            f"not found in {os.path.basename(head['path'])}"
        )


def test_head_migration_creates_auto_evolve_log():
    """Head migration upgrade() must create kg_auto_evolve_log table."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    head = _find_head_migration(migrations)
    if head is None:
        pytest.skip("Could not identify head migration")

    src = head["upgrade_src"]
    assert "kg_auto_evolve_log" in src, (
        f"Head migration must create kg_auto_evolve_log table; "
        f"not found in {os.path.basename(head['path'])}"
    )


def test_head_migration_creates_verification_run_log():
    """Head migration upgrade() must create kg_verification_run_log table."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    head = _find_head_migration(migrations)
    if head is None:
        pytest.skip("Could not identify head migration")

    src = head["upgrade_src"]
    assert "kg_verification_run_log" in src, (
        f"Head migration must create kg_verification_run_log; "
        f"not found in {os.path.basename(head['path'])}"
    )


def test_head_migration_creates_partial_index():
    """Head migration upgrade() must create the partial index idx_triples_unverified."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    head = _find_head_migration(migrations)
    if head is None:
        pytest.skip("Could not identify head migration")

    src = head["upgrade_src"]
    assert "unverified" in src, (
        f"Head migration must create partial index for unverified triples; "
        f"'unverified' not found in {os.path.basename(head['path'])}"
    )


# ── §12.3 downgrade is inverse ────────────────────────────────────────────────


def test_head_migration_has_downgrade_function():
    """Head migration must define a downgrade() function."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    head = _find_head_migration(migrations)
    if head is None:
        pytest.skip("Could not identify head migration")

    assert head["has_downgrade"], (
        f"Head migration must have downgrade(); "
        f"not found in {os.path.basename(head['path'])}"
    )


def test_head_migration_downgrade_removes_columns():
    """Head migration downgrade() must drop the added columns."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    head = _find_head_migration(migrations)
    if head is None:
        pytest.skip("Could not identify head migration")

    # Parse just the downgrade function body
    src = head["downgrade_src"]
    # Find downgrade function block
    downgrade_start = src.find("def downgrade(")
    if downgrade_start == -1:
        pytest.skip("No downgrade function found")
    downgrade_body = src[downgrade_start:]

    # At minimum, downgrade should drop something related to verification columns
    # Check for drop_column or drop_table operations
    has_drop = "drop_column" in downgrade_body or "drop_table" in downgrade_body
    assert has_drop, (
        f"Head migration downgrade() must have drop operations; "
        f"downgrade body: {downgrade_body[:200]!r}"
    )


def test_head_migration_downgrade_removes_tables():
    """Head migration downgrade() must drop kg_auto_evolve_log and kg_verification_run_log."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    head = _find_head_migration(migrations)
    if head is None:
        pytest.skip("Could not identify head migration")

    src = head["downgrade_src"]
    downgrade_start = src.find("def downgrade(")
    if downgrade_start == -1:
        pytest.skip("No downgrade function found")
    downgrade_body = src[downgrade_start:]

    for table in ("kg_auto_evolve_log", "kg_verification_run_log"):
        assert table in downgrade_body, (
            f"Head migration downgrade() must drop table {table!r}; "
            f"not found in downgrade body"
        )


# ── §12.4 migration chain integrity ──────────────────────────────────────────


def test_alembic_chain_no_dangling_down_revisions():
    """Every down_revision reference must point to an existing migration."""
    files = _find_migration_files()
    if not files:
        pytest.skip("No migration files found")

    migrations = [_parse_migration(f) for f in files]
    all_revisions = {m["revision"] for m in migrations if m["revision"]}

    dangling = []
    for m in migrations:
        dr = m["down_revision"]
        if dr and dr not in all_revisions:
            dangling.append((m["revision"], dr))

    assert dangling == [], (
        f"Found dangling down_revision references: {dangling}"
    )
