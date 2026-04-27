"""Adversary tests for pre_write_conflict_check.

Mutation thinking targets:
- author flips scoped_to_children polarity (None -> True)
- author raises on lint.check_contradictions exception (must fail-OPEN, not fail-closed)
- author returns dict instead of ConflictCheckResult dataclass
- author short-circuits has_conflict to True on any exception (would block all writes)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.memvault.fold_verifier import (
    ConflictCheckResult,
    pre_write_conflict_check,
)


def _run(coro):
    return asyncio.run(coro)


def _mock_db():
    """AsyncMock for an SQLAlchemy AsyncSession surface used by the function.

    We don't know the exact internal queries — mock the common surface:
    db.execute returns an object with .scalars().all() and .all().
    """
    db = MagicMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    exec_result.all.return_value = []
    exec_result.fetchall.return_value = []
    exec_result.scalar_one_or_none.return_value = None
    exec_result.scalar.return_value = 0
    db.execute = AsyncMock(return_value=exec_result)
    return db


def test_returns_conflict_check_result_dataclass():
    """INVARIANT: return type is always ConflictCheckResult.

    Mutation: author returns a dict / tuple -> downstream type errors.
    """
    db = _mock_db()
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(return_value={"contradictions": [], "findings": []}),
    ):
        out = _run(pre_write_conflict_check(db, "space-1"))
    assert isinstance(out, ConflictCheckResult)


def test_children_ids_none_scoped_to_children_false():
    """children_ids=None -> scoped_to_children == False.

    Mutation: polarity flip (default True) -> consumer gets misleading flag.
    """
    db = _mock_db()
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(return_value={"contradictions": [], "findings": []}),
    ):
        out = _run(pre_write_conflict_check(db, "space-1", children_ids=None))
    assert out.scoped_to_children is False


def test_children_ids_provided_scoped_to_children_true():
    """children_ids=['b1'] -> scoped_to_children == True."""
    db = _mock_db()
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(return_value={"contradictions": [], "findings": []}),
    ):
        out = _run(
            pre_write_conflict_check(db, "space-1", children_ids=["b1", "b2"])
        )
    assert out.scoped_to_children is True


def test_children_ids_empty_list_design_choice():
    """children_ids=[] is the ambiguous case.

    Empty list != None semantically — caller asked for scope but provided
    no children. Design choice:
      (A) treat as None (scoped_to_children=False)
      (B) treat as 'scoped to no children' (scoped_to_children=True)

    We assert (A): falsy check, since [] also implies 'no scope info'.
    Mutation: author uses ``is None`` instead of truthy check -> [] becomes
    True and downstream consumer thinks scope was requested.
    """
    db = _mock_db()
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(return_value={"contradictions": [], "findings": []}),
    ):
        out = _run(pre_write_conflict_check(db, "space-1", children_ids=[]))
    # Per the dataclass docstring: "scoped_to_children records whether the
    # caller asked for a per-fold scope (children_ids was provided)". An
    # empty list is technically 'provided' but contains no scope info. Both
    # answers defensible; we test for the conservative one and let it
    # surface the design.
    assert out.scoped_to_children is False, (
        "empty children_ids treated as scope-requested; consider using "
        "truthy check instead of `is None`"
    )


def test_lint_exception_fail_open():
    """When lint.check_contradictions raises, must fail OPEN (no conflict).

    Mutation: author propagates exception -> entire fold-write pipeline
    crashes on any KG hiccup. The dataclass has an `error` field for a
    reason: degrade gracefully.
    """
    db = _mock_db()
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(side_effect=RuntimeError("KG service down")),
    ):
        try:
            out = _run(pre_write_conflict_check(db, "space-1"))
        except RuntimeError:
            pytest.fail(
                "pre_write_conflict_check propagated lint exception; "
                "must fail-open with error= populated"
            )
    assert isinstance(out, ConflictCheckResult)
    assert out.has_conflict is False, "must fail-open (no conflict) on lint error"
    assert out.error is not None, "error field must capture failure reason"


def test_no_conflicts_returns_has_conflict_false():
    """Happy path: lint returns empty -> has_conflict == False."""
    db = _mock_db()
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(return_value={"contradictions": [], "findings": []}),
    ):
        out = _run(pre_write_conflict_check(db, "space-1"))
    assert out.has_conflict is False
    assert out.error is None


def test_findings_field_is_list_type_invariant():
    """`findings` must always be a list, never None — dataclass default
    is `field(default_factory=list)`. Consumer iterates over it.
    """
    db = _mock_db()
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        out = _run(pre_write_conflict_check(db, "space-1"))
    assert isinstance(out.findings, list), (
        f"findings must be list (got {type(out.findings).__name__})"
    )


def test_db_exception_does_not_raise():
    """If db.execute itself raises, function should still return a result
    (fail-open) rather than propagate. Defense-in-depth.

    Mutation: author wraps only the lint call in try/except, not the db
    sample query -> db hiccup crashes the writer.
    """
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))
    with patch(
        "src.modules.memvault.lint.check_contradictions",
        new=AsyncMock(return_value={"contradictions": [], "findings": []}),
    ):
        try:
            out = _run(pre_write_conflict_check(db, "space-1"))
        except RuntimeError:
            pytest.fail(
                "pre_write_conflict_check propagated DB exception; "
                "must fail-open"
            )
    assert isinstance(out, ConflictCheckResult)
    assert out.has_conflict is False
