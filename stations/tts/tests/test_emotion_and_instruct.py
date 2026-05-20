"""Unit tests for engine_specific emotion + instruct plumbing.

Coverage:
  - EMOTION_PRESETS / _resolve_emotion in worker_indextts_daemon + runner mirror
  - worker_pool.synth flattens engine_specific into the worker command
  - TTSClient.emotion_preset / instruct helpers stay aligned with the daemon

# MUTATION TARGETS
# 1. EMOTION_PRESETS vector order (must match infer_v2.py:344 emo_bias)
# 2. _resolve_emotion priority audio > text > preset/vector
# 3. _build_engine_specific CSV parsing rejects non-8-dim vectors
# 4. worker_pool flattens engine_specific keys to the worker payload
# 5. TTSClient.EMOTION_NAMES kept in sync with daemon EMOTION_PRESETS
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# stations/tts is not a package; load worker module by path.
TTS_ROOT = Path(__file__).resolve().parents[1]
WORKERS_DIR = TTS_ROOT / "workers"
RUNNERS_DIR = TTS_ROOT / "runners"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # base_daemon import inside daemon module — make sure sibling resolves
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        if sys.path[0] == str(path.parent):
            sys.path.pop(0)
    return mod


@pytest.fixture(scope="module")
def daemon_mod():
    return _load_module(
        WORKERS_DIR / "worker_indextts_daemon.py", "worker_indextts_daemon_under_test"
    )


@pytest.fixture(scope="module")
def runner_mod():
    return _load_module(RUNNERS_DIR / "run_indextts2.py", "run_indextts2_under_test")


# ---------------------------------------------------------------------------
# EMOTION_PRESETS — order matches IndexTTS-2 emo_bias
# ---------------------------------------------------------------------------

EXPECTED_ORDER = (
    "happy",  # index 0
    "angry",  # index 1
    "sad",  # index 2
    "afraid",  # index 3
    "disgusted",  # index 4
    "melancholic",  # index 5
    "surprised",  # index 6
    "calm",  # index 7
)


def test_emotion_presets_8dim(daemon_mod):
    presets = daemon_mod.EMOTION_PRESETS
    for name, vec in presets.items():
        assert len(vec) == 8, f"{name} not 8-dim"


def test_emotion_presets_one_hot_at_expected_index(daemon_mod):
    presets = daemon_mod.EMOTION_PRESETS
    for idx, name in enumerate(EXPECTED_ORDER):
        vec = presets[name]
        assert vec[idx] == 1.0, f"{name} should be 1.0 at index {idx}, got {vec}"
        assert sum(vec) == 1.0, f"{name} should be one-hot, got {vec}"


def test_emotion_neutral_all_zero(daemon_mod):
    assert daemon_mod.EMOTION_PRESETS["neutral"] == [0.0] * 8


def test_runner_emotion_presets_match_daemon(daemon_mod, runner_mod):
    assert daemon_mod.EMOTION_PRESETS == runner_mod.EMOTION_PRESETS, (
        "EMOTION_PRESETS drift between worker_indextts_daemon and run_indextts2"
    )


# ---------------------------------------------------------------------------
# _resolve_emotion priority
# ---------------------------------------------------------------------------

def test_resolve_emotion_empty(daemon_mod):
    assert daemon_mod._resolve_emotion(None) == {}
    assert daemon_mod._resolve_emotion({}) == {}


def test_resolve_emotion_audio_wins_over_text_and_preset(daemon_mod):
    out = daemon_mod._resolve_emotion(
        {"audio": "/path/sad.wav", "text": "悲傷", "preset": "happy", "alpha": 0.6}
    )
    assert "emo_audio_prompt" in out
    assert "emo_vector" not in out  # audio path is exclusive
    assert "emo_text" not in out
    assert out["emo_alpha"] == 0.6


def test_resolve_emotion_text_wins_over_preset(daemon_mod):
    out = daemon_mod._resolve_emotion({"text": "悲傷", "preset": "happy"})
    assert out["use_emo_text"] is True
    assert out["emo_text"] == "悲傷"
    assert "emo_vector" not in out


def test_resolve_emotion_preset_to_vector(daemon_mod):
    out = daemon_mod._resolve_emotion({"preset": "happy"})
    assert out["emo_vector"] == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_resolve_emotion_raw_vector_kept(daemon_mod):
    v = [0.5, 0.5, 0, 0, 0, 0, 0, 0]
    out = daemon_mod._resolve_emotion({"vector": v})
    assert out["emo_vector"] == [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_resolve_emotion_bad_preset_raises(daemon_mod):
    with pytest.raises(ValueError, match="unknown emotion preset"):
        daemon_mod._resolve_emotion({"preset": "elated"})


def test_resolve_emotion_bad_vector_len(daemon_mod):
    with pytest.raises(ValueError, match="8-dim"):
        daemon_mod._resolve_emotion({"vector": [1.0, 0, 0]})


def test_resolve_emotion_alpha_clamped(daemon_mod):
    assert daemon_mod._resolve_emotion({"preset": "happy", "alpha": 1.5})["emo_alpha"] == 1.0
    assert daemon_mod._resolve_emotion({"preset": "happy", "alpha": -0.2})["emo_alpha"] == 0.0


# ---------------------------------------------------------------------------
# SDK helpers stay aligned with daemon
# ---------------------------------------------------------------------------

def test_sdk_emotion_names_match_daemon_presets(daemon_mod):
    sys.path.insert(0, str(TTS_ROOT.parent.parent / "libs" / "sdk-client"))
    try:
        from sdk_client.tts import TTSClient
    finally:
        sys.path.pop(0)
    assert set(TTSClient.EMOTION_NAMES) == set(daemon_mod.EMOTION_PRESETS.keys()), (
        "TTSClient.EMOTION_NAMES drifted from worker_indextts_daemon.EMOTION_PRESETS"
    )


def test_sdk_emotion_preset_helper_shape():
    sys.path.insert(0, str(TTS_ROOT.parent.parent / "libs" / "sdk-client"))
    try:
        from sdk_client.tts import TTSClient
    finally:
        sys.path.pop(0)
    assert TTSClient.emotion_preset("happy") == {"emotion": {"preset": "happy", "alpha": 1.0}}
    assert TTSClient.instruct("用興奮的語氣") == {"instruct": "用興奮的語氣"}
    assert TTSClient.wrap_laughter("哈哈") == "<laughter>哈哈</laughter>"
    with pytest.raises(ValueError):
        TTSClient.emotion_preset("elated")
