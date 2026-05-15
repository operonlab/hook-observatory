"""Regression tests for docvault per-space content_hash dedup.

Source-level assertions on services.py and routes.py — avoids the
pytest collection path issue that blocks importing core modules
without the full app context.

六鐵律 #4 (runtime→回歸): every fix needs a regression test that
fails before the fix and passes after.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[4]
_SERVICES = _REPO / "core" / "src" / "modules" / "docvault" / "services.py"
_ROUTES = _REPO / "core" / "src" / "modules" / "docvault" / "routes.py"


def _services_source() -> str:
    return _SERVICES.read_text(encoding="utf-8")


def _routes_source() -> str:
    return _ROUTES.read_text(encoding="utf-8")


# ---------- Service-layer signature -----------------------------------------


def test_get_by_content_hash_signature_includes_space_id():
    """If space_id ever drops out of the signature, dedup goes global again."""
    src = _services_source()
    assert "async def get_by_content_hash(" in src, "function renamed or removed"
    # Either positional or keyword — both signatures contain 'space_id:'
    fn_start = src.index("async def get_by_content_hash(")
    fn_signature = src[fn_start : src.index(":", fn_start + 50) + 1]
    assert "space_id" in fn_signature, (
        f"regression: space_id parameter missing from get_by_content_hash signature: {fn_signature!r}"
    )


def test_get_by_content_hash_query_filters_by_space():
    """The Document.space_id equality clause must be in the WHERE."""
    src = _services_source()
    assert "Document.space_id == space_id" in src, (
        "regression: space_id WHERE clause missing — dedup became global again"
    )


def test_get_by_content_hash_still_filters_soft_delete():
    """Pre-existing invariant: soft-deleted docs should not collide on hash."""
    src = _services_source()
    assert "Document.deleted_at == None" in src, (
        "soft-delete filter accidentally removed alongside the dedup change"
    )


# ---------- Route-layer wiring ----------------------------------------------


def test_routes_pass_space_id_to_dedup():
    """All callers of get_by_content_hash must thread space_id through."""
    src = _routes_source()
    call_lines = [
        line for line in src.splitlines() if "get_by_content_hash(" in line
    ]
    assert call_lines, "no caller found — endpoints renamed?"
    for line in call_lines:
        assert "space_id" in line, (
            f"caller does not forward space_id: {line.strip()}"
        )


def test_conflict_error_mentions_space():
    """Operator readability: error message should identify the offending space."""
    src = _routes_source()
    occurrences = src.count("already exists in space")
    assert occurrences >= 2, (
        f"both dedup ConflictError messages should mention the space (found {occurrences})"
    )


# ---------- End-to-end placeholder ------------------------------------------


@pytest.mark.skip(
    reason="e2e: requires core service restarted with merged code. "
    "Verify by uploading the SAME file to space_id=A and space_id=B — "
    "both should succeed (each space gets its own Document row). "
    "Before this fix, the second upload failed with content_hash_conflict."
)
def test_same_hash_can_exist_in_two_spaces_e2e():
    pass
