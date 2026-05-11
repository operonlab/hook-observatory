"""鐵律 1 — Unit tests for Phase B evidence_signal helpers.

Tests pure functions — no DB / no I/O.

Covers:
  - _verify_strategy_from_signal() for all three signal tiers
  - EVIDENCE_SIGNAL_WEIGHT constants in community_summary_pipeline
  - signal_from_score() boundary combos with _verify_strategy_from_signal()
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_WORKTREE_CORE_SRC = os.path.join(_WORKTREE_CORE, "src")
sys.path = [
    p for p in sys.path if "/workshop/" not in p or ".claude/worktrees/" in p or "/.venv/" in p
]
sys.path.insert(0, _WORKTREE_CORE_SRC)
sys.path.insert(0, _WORKTREE_CORE)
for libname in ("text-ops", "kg-ops", "sdk-client", "tmux-lib", "audio-ops", "image-ops", "video-ops"):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.append(p)

import sys as _sys
_PIPELINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", "..", "mcp", "memvault"))
if _PIPELINE_DIR not in _sys.path:
    _sys.path.insert(0, _PIPELINE_DIR)


class TestVerifyStrategyFromSignal:
    """_verify_strategy_from_signal() returns correct strategy dict per signal tier."""

    def test_ambiguous_force_web_verify_true(self):
        from src.modules.memvault.crag_evaluator import (
            EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD,
            _verify_strategy_from_signal,
        )

        strategy = _verify_strategy_from_signal("ambiguous")
        assert strategy["force_web_verify"] is True, (
            "ambiguous signal must set force_web_verify=True"
        )
        assert strategy["promote_threshold"] == EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD, (
            "ambiguous signal promote_threshold must equal extracted threshold"
        )

    def test_inferred_promote_threshold_lower(self):
        from src.modules.memvault.crag_evaluator import (
            _INFERRED_PROMOTE_THRESHOLD,
            _verify_strategy_from_signal,
        )

        strategy = _verify_strategy_from_signal("inferred")
        assert strategy["force_web_verify"] is False, (
            "inferred signal must not force web verify"
        )
        assert strategy["promote_threshold"] == _INFERRED_PROMOTE_THRESHOLD, (
            f"inferred signal promote_threshold must equal {_INFERRED_PROMOTE_THRESHOLD}"
        )

    def test_extracted_default_threshold(self):
        from src.modules.memvault.crag_evaluator import (
            EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD,
            _verify_strategy_from_signal,
        )

        strategy = _verify_strategy_from_signal("extracted")
        assert strategy["force_web_verify"] is False, (
            "extracted signal must not force web verify"
        )
        assert strategy["promote_threshold"] == EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD, (
            "extracted signal promote_threshold must equal extracted threshold (0.8)"
        )

    def test_inferred_promote_threshold_less_than_extracted(self):
        from src.modules.memvault.crag_evaluator import (
            _INFERRED_PROMOTE_THRESHOLD,
            _verify_strategy_from_signal,
        )

        inferred_strategy = _verify_strategy_from_signal("inferred")
        extracted_strategy = _verify_strategy_from_signal("extracted")
        assert inferred_strategy["promote_threshold"] < extracted_strategy["promote_threshold"], (
            "inferred promote_threshold must be < extracted promote_threshold"
        )

    def test_unknown_signal_falls_back_to_extracted(self):
        """Unknown signal string should behave like 'extracted'."""
        from src.modules.memvault.crag_evaluator import (
            EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD,
            _verify_strategy_from_signal,
        )

        strategy = _verify_strategy_from_signal("some_unknown_signal")
        # Falls through to default branch — same as extracted
        assert strategy["force_web_verify"] is False
        assert strategy["promote_threshold"] == EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD


class TestEvidenceSignalWeightConstants:
    """EVIDENCE_SIGNAL_WEIGHT in community_summary_pipeline.py."""

    def test_weight_constants_correct_values(self):
        from pipelines.community_summary_pipeline import EVIDENCE_SIGNAL_WEIGHT

        assert EVIDENCE_SIGNAL_WEIGHT["extracted"] == 1.0, (
            "extracted signal weight must be 1.0"
        )
        assert EVIDENCE_SIGNAL_WEIGHT["inferred"] == 0.7, (
            "inferred signal weight must be 0.7"
        )
        assert EVIDENCE_SIGNAL_WEIGHT["ambiguous"] == 0.3, (
            "ambiguous signal weight must be 0.3"
        )

    def test_weight_ordering(self):
        """extracted > inferred > ambiguous — monotonically decreasing."""
        from pipelines.community_summary_pipeline import EVIDENCE_SIGNAL_WEIGHT

        assert (
            EVIDENCE_SIGNAL_WEIGHT["extracted"]
            > EVIDENCE_SIGNAL_WEIGHT["inferred"]
            > EVIDENCE_SIGNAL_WEIGHT["ambiguous"]
        ), "Signal weights must be monotonically: extracted > inferred > ambiguous"

    def test_all_three_tiers_present(self):
        from pipelines.community_summary_pipeline import EVIDENCE_SIGNAL_WEIGHT

        assert set(EVIDENCE_SIGNAL_WEIGHT.keys()) >= {"extracted", "inferred", "ambiguous"}, (
            "All three evidence_signal tiers must be present in EVIDENCE_SIGNAL_WEIGHT"
        )

    def test_ambiguous_weight_nonzero(self):
        """Ambiguous should still contribute (just downweighted), not silenced."""
        from pipelines.community_summary_pipeline import EVIDENCE_SIGNAL_WEIGHT

        assert EVIDENCE_SIGNAL_WEIGHT["ambiguous"] > 0.0, (
            "ambiguous weight must be > 0 (triples still count, just less)"
        )


class TestSignalFromScoreWithStrategy:
    """Combine signal_from_score() → _verify_strategy_from_signal() pipeline."""

    def test_high_score_extracted_no_force_verify(self):
        from src.modules.memvault.crag_evaluator import (
            _verify_strategy_from_signal,
            signal_from_score,
        )

        signal = signal_from_score(0.9)
        strategy = _verify_strategy_from_signal(signal)
        assert signal == "extracted"
        assert strategy["force_web_verify"] is False

    def test_mid_score_inferred_no_force_verify(self):
        from src.modules.memvault.crag_evaluator import (
            _verify_strategy_from_signal,
            signal_from_score,
        )

        signal = signal_from_score(0.6)
        strategy = _verify_strategy_from_signal(signal)
        assert signal == "inferred"
        assert strategy["force_web_verify"] is False

    def test_low_score_ambiguous_force_verify(self):
        from src.modules.memvault.crag_evaluator import (
            _verify_strategy_from_signal,
            signal_from_score,
        )

        signal = signal_from_score(0.2)
        strategy = _verify_strategy_from_signal(signal)
        assert signal == "ambiguous"
        assert strategy["force_web_verify"] is True

    def test_none_score_extracted_no_force_verify(self):
        """None confidence → extracted → no force verify."""
        from src.modules.memvault.crag_evaluator import (
            _verify_strategy_from_signal,
            signal_from_score,
        )

        signal = signal_from_score(None)
        strategy = _verify_strategy_from_signal(signal)
        assert signal == "extracted"
        assert strategy["force_web_verify"] is False

    def test_inferred_promote_threshold_is_07(self):
        """_INFERRED_PROMOTE_THRESHOLD constant value must be 0.7."""
        from src.modules.memvault.crag_evaluator import _INFERRED_PROMOTE_THRESHOLD

        assert _INFERRED_PROMOTE_THRESHOLD == 0.7, (
            f"_INFERRED_PROMOTE_THRESHOLD must be 0.7, got {_INFERRED_PROMOTE_THRESHOLD}"
        )
