"""Tests for SpeakerSimilarityOp.

# MUTATION TARGETS
# 1. Cosine formula — symmetry score(A,B) == score(B,A)
# 2. Identity — score(A,A) == 1.0
# 3. Verdict thresholds — same_speaker > close > drift
# 4. batch() preserves insertion order labels
# 5. ImportError when extras missing surfaces extras hint
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

REF_WAV = Path.home() / "workshop/stations/tts/voices/master.wav"

# All cases need resemblyzer installed; skip the file if not.
pytest.importorskip("resemblyzer")
from audio_ops.speaker_similarity import (  # noqa: E402
    SIMILARITY_THRESHOLDS,
    SpeakerSimilarityOp,
)


@pytest.fixture(scope="module")
def op() -> SpeakerSimilarityOp:
    if not REF_WAV.exists():
        pytest.skip(f"reference wav not present: {REF_WAV}")
    return SpeakerSimilarityOp(ref=REF_WAV)


def test_self_similarity_is_one(op):
    """score(A, A) must be ≥ 0.999 — same waveform → same d-vector."""
    score = op.score(REF_WAV)
    assert score > 0.999, f"self-similarity should be ≈ 1, got {score}"


def test_cosine_in_unit_interval():
    """Cosine of L2-normalised dense embeddings stays in [-1, 1]; for d-vectors
    in practice it is in [0, 1] because all embeddings live in the same hemisphere."""
    a = np.random.RandomState(0).randn(256)
    b = np.random.RandomState(1).randn(256)
    cos = SpeakerSimilarityOp._cosine(a, b)
    assert -1.0 <= cos <= 1.0


def test_cosine_symmetry():
    a = np.random.RandomState(2).randn(256)
    b = np.random.RandomState(3).randn(256)
    assert SpeakerSimilarityOp._cosine(a, b) == pytest.approx(
        SpeakerSimilarityOp._cosine(b, a)
    )


def test_cosine_zero_vector_returns_zero():
    """Defensive: linear-algebra would divide by zero, but we clamp to 0."""
    assert SpeakerSimilarityOp._cosine(np.zeros(8), np.ones(8)) == 0.0


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.95, "same_speaker"),
        (0.85, "same_speaker"),
        (0.80, "close"),
        (0.75, "close"),
        (0.70, "drift"),
        (0.0, "drift"),
    ],
)
def test_verdict_buckets(op, score, expected):
    assert op.verdict(score) == expected


def test_verdict_thresholds_constant():
    """Sanity: the defaults make biological sense (same > close > 0)."""
    assert SIMILARITY_THRESHOLDS["same_speaker"] > SIMILARITY_THRESHOLDS["close"]
    assert SIMILARITY_THRESHOLDS["close"] > 0


def test_batch_preserves_labels(op, tmp_path):
    """batch() must return one score per labelled input, label-keyed."""
    out = op.batch({"ref": REF_WAV, "ref_again": REF_WAV})
    assert set(out) == {"ref", "ref_again"}
    assert out["ref"] > 0.999
    assert out["ref_again"] > 0.999


def test_pipeline_form_writes_ctx(op):
    """__call__ pipeline writes similarity + pass + verdict into ctx."""
    ctx = {"source_path": str(REF_WAV)}
    out = op(ctx)
    assert out["speaker_similarity"] > 0.999
    assert out["speaker_similarity_pass"] is True
    assert out["speaker_similarity_verdict"] == "same_speaker"


def test_pipeline_form_rejects_empty_ctx(op):
    with pytest.raises(ValueError, match="source_path"):
        op({})


def test_op_registered_in_registry():
    """Catalogue registration so AudioPipe parser can resolve it."""
    from audio_ops import OPERATORS

    assert "speaker_similarity" in OPERATORS
    assert OPERATORS["speaker_similarity"] is SpeakerSimilarityOp


def test_missing_extras_message(monkeypatch):
    """When resemblyzer isn't importable, _require_resemblyzer must point to extras."""
    import audio_ops.speaker_similarity as ss

    # simulate missing resemblyzer
    monkeypatch.setitem(sys.modules, "resemblyzer", None)
    importlib.reload(ss)
    with pytest.raises(ImportError, match=r"workshop-audio-ops\[similarity\]"):
        ss._require_resemblyzer()
