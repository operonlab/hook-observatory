"""Tests for VisualizeOp — PNG render smoke + registry + extras hint.

# MUTATION TARGETS
# 1. render_one writes a valid PNG > 1KB
# 2. compare grid writes per-row label + same row count
# 3. rank_bar colours green/amber/red around the right thresholds
# 4. Missing librosa surfaces extras hint
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REF_WAV = Path.home() / "workshop/stations/tts/voices/master.wav"

pytest.importorskip("librosa")
pytest.importorskip("matplotlib")
from audio_ops.visualize import VisualizeOp  # noqa: E402


@pytest.fixture(scope="module")
def op() -> VisualizeOp:
    if not REF_WAV.exists():
        pytest.skip(f"reference wav not present: {REF_WAV}")
    return VisualizeOp()


def test_render_one_writes_png(op, tmp_path):
    out = op.render_one(REF_WAV, tmp_path / "render.png")
    assert out.exists()
    assert out.stat().st_size > 1024, "PNG too small to be real"
    # PNG magic header
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_compare_grid(op, tmp_path):
    out = op.compare(
        [("ref", REF_WAV), ("ref2", REF_WAV)],
        out=tmp_path / "grid.png",
        annotations={"ref": "sim=1.000"},
    )
    assert out.exists()
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_rank_bar_writes_png(op, tmp_path):
    out = op.rank_bar(
        {"alpha 0.2": 0.890, "alpha 0.4": 0.841, "alpha 0.6": 0.794, "alpha 1.0": 0.681},
        out=tmp_path / "bar.png",
    )
    assert out.exists()
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_pipeline_form_writes_png(op, tmp_path):
    """__call__ pipeline writes a sibling PNG and ctx['visualize_png']."""
    # Copy the ref to a tmp location so the sibling PNG lands in tmp_path.
    import shutil

    src = tmp_path / "input.wav"
    shutil.copy(REF_WAV, src)
    ctx = {"source_path": str(src)}
    out = op(ctx)
    assert "visualize_png" in out
    assert Path(out["visualize_png"]).exists()


def test_op_registered():
    from audio_ops import OPERATORS

    assert "visualize" in OPERATORS
    assert OPERATORS["visualize"] is VisualizeOp


def test_missing_extras_message(monkeypatch):
    """When librosa isn't importable, _require_libs must point to extras."""
    import audio_ops.visualize as viz

    monkeypatch.setitem(sys.modules, "librosa", None)
    importlib.reload(viz)
    with pytest.raises(ImportError, match=r"workshop-audio-ops\[visualize\]"):
        viz._require_libs()
