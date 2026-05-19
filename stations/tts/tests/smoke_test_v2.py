"""v2 engine smoke test — 每 engine × 各 OutputMode 跑一句驗證。

執行（win-gpu）：
    cd ~/workshop/stations/tts
    .venv/bin/python3 -m pytest tests/smoke_test_v2.py -v

Mac 端只能跑 import + capability + routing 部分（subprocess 路徑會 fail
因為 PYTHON 路徑指向 Windows / WSL）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent.parent / "libs" / "sdk-client"))

from engines.base_v2 import OutputMode, SynthesizeRequest
from engines.registry_v2 import V2_ENGINES, list_v2_engines
from routing import explain_route, pick_engine


# --- Pure logic tests (run anywhere) ---


def test_six_engines_registered():
    assert set(V2_ENGINES.keys()) == {
        "cosyvoice_v3_native",
        "cosyvoice_v3_vllm",
        "indextts2_base",
        "indextts2_jmica",
        "vibevoice",
        "qwen3tts_gpu",
    }


def test_capability_complete():
    for name, eng in V2_ENGINES.items():
        cap = eng.capability()
        assert cap.name == name
        assert cap.sample_rate > 0
        assert cap.rtf_typical > 0
        assert cap.vram_mb > 0
        assert OutputMode.FILE in cap.supported_outputs
        assert cap.languages, f"{name} has no languages"


def test_routing_defaults():
    assert pick_engine("zh") == "indextts2_base"
    assert pick_engine("en") == "cosyvoice_v3_vllm"
    assert pick_engine("ja") == "indextts2_jmica"
    assert pick_engine("ko") == "qwen3tts_gpu"
    assert pick_engine("zh", multi_speaker=True) == "vibevoice"


def test_routing_fallback_chain():
    chain = explain_route("zh")["fallback_chain"]
    assert chain[0] == "indextts2_base"
    assert "cosyvoice_v3_vllm" in chain


def test_jmica_rejects_zh():
    """indextts2_jmica 只接 ja，zh/en 應該 ValueError."""
    eng = V2_ENGINES["indextts2_jmica"]
    req = SynthesizeRequest(text="你好", lang="zh", voice_id="master")
    with pytest.raises(ValueError, match="只接 ja"):
        eng._build_input(req, "/tmp/_out.npy")


def test_vibevoice_rejects_ja():
    """vibevoice 不支援 ja."""
    eng = V2_ENGINES["vibevoice"]
    req = SynthesizeRequest(text="こんにちは", lang="ja", voice_id="master")
    with pytest.raises(ValueError, match="不支援日語"):
        eng._build_input(req, "/tmp/_out.npy")


def test_output_mode_validation():
    """STREAM 只允許 cosyvoice_v3_vllm + vibevoice."""
    qwen = V2_ENGINES["qwen3tts_gpu"]
    assert OutputMode.STREAM not in qwen.capability().supported_outputs

    vllm = V2_ENGINES["cosyvoice_v3_vllm"]
    assert OutputMode.STREAM in vllm.capability().supported_outputs

    vibe = V2_ENGINES["vibevoice"]
    assert OutputMode.STREAM in vibe.capability().supported_outputs


# --- Live tests (win-gpu only, skip elsewhere) ---


GPU_HOST = os.environ.get("TTS_HOST", "").lower()
LIVE_TEST = GPU_HOST in ("win-gpu", "windows", "wsl") or os.environ.get("TTS_LIVE") == "1"

pytestmark_live = pytest.mark.skipif(not LIVE_TEST, reason="TTS_LIVE=1 not set (win-gpu only)")


@pytestmark_live
@pytest.mark.parametrize(
    "engine_name,lang,text",
    [
        ("cosyvoice_v3_vllm", "en", "Hello from cosyvoice vllm"),
        ("indextts2_base", "zh", "你好，這是 IndexTTS 測試"),
        ("indextts2_jmica", "ja", "こんにちは"),
        ("qwen3tts_gpu", "zh", "你好"),
    ],
)
def test_engine_live(engine_name: str, lang: str, text: str, tmp_path):
    eng = V2_ENGINES[engine_name]
    out_path = str(tmp_path / "out.wav")
    req = SynthesizeRequest(
        text=text, lang=lang, voice_id="master",
        output=OutputMode.FILE, output_path=out_path,
    )
    res = eng.synthesize(req)
    assert res.audio_path == out_path
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 1000
    assert res.duration_s > 0
    assert res.rtf > 0
    print(f"[{engine_name}] dur={res.duration_s:.2f}s rtf={res.rtf:.2f}")


@pytestmark_live
def test_output_mode_base64():
    eng = V2_ENGINES["cosyvoice_v3_vllm"]
    req = SynthesizeRequest(text="Test", lang="en", output=OutputMode.BASE64)
    res = eng.synthesize(req)
    assert res.audio_base64
    assert len(res.audio_base64) > 100


@pytestmark_live
def test_output_mode_numpy():
    import numpy as np
    eng = V2_ENGINES["cosyvoice_v3_vllm"]
    req = SynthesizeRequest(text="Test", lang="en", output=OutputMode.NUMPY)
    res = eng.synthesize(req)
    assert isinstance(res.audio_numpy, np.ndarray)
    assert res.audio_numpy.dtype == np.float32
    assert res.audio_numpy.ndim == 1


@pytestmark_live
def test_lifecycle_unload():
    """Trigger a synth then verify lifecycle status sees the engine."""
    from lifecycle import MANAGER
    eng = V2_ENGINES["cosyvoice_v3_vllm"]
    MANAGER.mark_used("cosyvoice_v3_vllm")
    status = MANAGER.status()
    assert "cosyvoice_v3_vllm" in status
    assert status["cosyvoice_v3_vllm"]["idle_sec"] < 5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
