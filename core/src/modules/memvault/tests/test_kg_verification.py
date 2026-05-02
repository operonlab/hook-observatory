"""Unit test — kg_verification.PromotionStats + thresholds + model wiring.

Pure unit test: validates dataclass arithmetic, threshold constants, and that
the audit-log model is correctly declared. End-to-end promotion logic against
real triples is left to integration tests (needs PG fixtures).
"""

from __future__ import annotations

import os
import sys

# Path fixup
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(_WORKTREE_CORE, "src"))
sys.path.insert(0, _WORKTREE_CORE)
for libname in ("text-ops", "kg-ops", "sdk-client", "tmux-lib"):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.insert(0, p)


def test_promotion_stats_counts_derived_from_lists():
    from src.modules.memvault.kg_verification import PromotionStats

    s = PromotionStats(candidates_scanned=5, dry_run=True)
    s.promoted_ids = ["a", "b"]
    s.demoted_ids = ["c"]
    assert s.promoted_count == 2
    assert s.demoted_count == 1
    assert s.dry_run is True


def test_thresholds_have_sane_defaults():
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        DEMOTE_INCORRECT_THRESHOLD,
        RECENT_CONFIRM_ACCESS_THRESHOLD,
        RECENT_CONFIRM_DAYS,
    )

    # Promotion bar must require multiple confirmations (no single-vote upgrade).
    assert CORRECT_COUNT_THRESHOLD >= 2
    # Recent-confirmation window stays in days, not seconds, and is monthly+.
    assert RECENT_CONFIRM_DAYS >= 30
    # Recent-access threshold is at least 2 (avoid one-touch promotions).
    assert RECENT_CONFIRM_ACCESS_THRESHOLD >= 2
    # Demotion bar same — no single-vote demote.
    assert DEMOTE_INCORRECT_THRESHOLD >= 2


def test_kg_verification_run_log_model_importable():
    from src.modules.memvault.kg_models import KGVerificationRunLog

    assert KGVerificationRunLog.__tablename__ == "kg_verification_run_log"
    cols = {c.name for c in KGVerificationRunLog.__table__.columns}
    assert {
        "started_at",
        "finished_at",
        "dry_run",
        "candidates_scanned",
        "promoted_count",
        "demoted_count",
    } <= cols


def test_triple_has_verification_fields():
    """Schema-level smoke — the new verification columns exist on Triple."""
    from src.modules.memvault.kg_models import Triple

    cols = {c.name for c in Triple.__table__.columns}
    assert "verification_status" in cols
    assert "verified_at" in cols
    assert "last_confirmed_at" in cols
    assert "crag_correct_count" in cols
    assert "crag_incorrect_count" in cols


if __name__ == "__main__":
    test_promotion_stats_counts_derived_from_lists()
    test_thresholds_have_sane_defaults()
    test_kg_verification_run_log_model_importable()
    test_triple_has_verification_fields()
    print("ok 4/4")
