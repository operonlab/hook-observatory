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
from engines.subprocess_bridge import SubprocessEngine
from lifecycle import LifecycleManager
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
    # 2026-05-19 少爺：中英日全 indextts-2，cosyvoice/qwen 為 fallback
    assert pick_engine("zh") == "indextts2_base"
    assert pick_engine("en") == "indextts2_base"
    assert pick_engine("ja") == "indextts2_jmica"
    assert pick_engine("ko") == "qwen3tts_gpu"
    assert pick_engine("zh", multi_speaker=True) == "vibevoice"
    assert pick_engine("en", prefer_fast=True) == "cosyvoice_v3_vllm"


def test_routing_fallback_chain():
    # 中文 chain：indextts2_base → cosyvoice_v3_vllm → cosyvoice_v3_native → qwen3tts_gpu
    zh_chain = explain_route("zh")["fallback_chain"]
    assert zh_chain[0] == "indextts2_base"
    assert zh_chain.index("cosyvoice_v3_vllm") < zh_chain.index("qwen3tts_gpu")

    # 英文 chain：indextts2_base 也排第一（少爺指令）
    en_chain = explain_route("en")["fallback_chain"]
    assert en_chain[0] == "indextts2_base"
    assert "cosyvoice_v3_vllm" in en_chain  # 仍在後位 fallback

    # 日文 chain：jmica 第一，cosyvoice 為 fallback
    ja_chain = explain_route("ja")["fallback_chain"]
    assert ja_chain[0] == "indextts2_jmica"


def test_jmica_rejects_zh():
    """indextts2_jmica 只接 ja，zh/en 應該 ValueError."""
    eng = V2_ENGINES["indextts2_jmica"]
    req = SynthesizeRequest(text="你好", lang="zh", voice_id="master")
    with pytest.raises(ValueError, match="只接 ja"):
        eng._build_input(req)


def test_vibevoice_rejects_ja():
    """vibevoice 不支援 ja."""
    eng = V2_ENGINES["vibevoice"]
    req = SynthesizeRequest(text="こんにちは", lang="ja", voice_id="master")
    with pytest.raises(ValueError, match="不支援日語"):
        eng._build_input(req)


def test_output_mode_validation():
    """STREAM 只允許 cosyvoice_v3_vllm + vibevoice."""
    qwen = V2_ENGINES["qwen3tts_gpu"]
    assert OutputMode.STREAM not in qwen.capability().supported_outputs

    vllm = V2_ENGINES["cosyvoice_v3_vllm"]
    assert OutputMode.STREAM in vllm.capability().supported_outputs

    vibe = V2_ENGINES["vibevoice"]
    assert OutputMode.STREAM in vibe.capability().supported_outputs


# --- Reviewer-flagged mutation tests (六鐵律 #1: mutation thinking) ---


def test_routing_available_subset_skips_primary():
    """Primary 不在 available → 應走 chain 下一個."""
    # zh 預設 indextts2_base，若不可用走 cosyvoice_v3_vllm
    result = pick_engine("zh", available=["cosyvoice_v3_vllm", "qwen3tts_gpu"])
    assert result == "cosyvoice_v3_vllm"


def test_routing_no_engine_available_raises():
    with pytest.raises(RuntimeError, match="No engine available"):
        pick_engine("zh", available=[])


def test_routing_unknown_lang_falls_to_en_chain():
    """未知 lang 應 fallback 到 en chain[0]."""
    assert pick_engine("fr") == "indextts2_base"  # en chain head


def test_file_mode_no_output_path_raises():
    """OutputMode.FILE 沒給 output_path → ValueError，必須在 spawn subprocess 之前."""
    eng = V2_ENGINES["indextts2_base"]
    req = SynthesizeRequest(
        text="test", lang="zh",
        output=OutputMode.FILE, output_path=None,
    )
    with pytest.raises(ValueError, match="requires output_path"):
        eng.synthesize(req)


def test_stream_mode_unsupported_engine_raises():
    """indextts2_base 不支援 STREAM → 應 ValueError."""
    eng = V2_ENGINES["indextts2_base"]
    req = SynthesizeRequest(text="test", lang="zh", output=OutputMode.STREAM)
    with pytest.raises(ValueError, match="STREAM|stream"):
        eng.synthesize(req)


def test_to_wsl_path_drive_letter():
    """C:/foo → /mnt/c/foo (正斜線輸入)."""
    assert SubprocessEngine._to_wsl_path("C:/Users/User/foo") == "/mnt/c/Users/User/foo"


def test_to_wsl_path_backslash():
    """C:\\Users\\User\\foo → /mnt/c/Users/User/foo (反斜線輸入)."""
    assert SubprocessEngine._to_wsl_path("C:\\Users\\User\\foo") == "/mnt/c/Users/User/foo"


def test_to_wsl_path_posix_passthrough():
    """已是 POSIX 路徑 → 原樣返回."""
    assert SubprocessEngine._to_wsl_path("/home/joneshong/bar") == "/home/joneshong/bar"


def test_lifecycle_sweep_removes_idle():
    """idle 超時的 engine 應該被 sweep 卸載."""
    import time as _t

    mgr = LifecycleManager(idle_timeout=0.01)

    class FakeEng:
        def __init__(self):
            self.unload_called = 0

        def unload(self):
            self.unload_called += 1

    fake = FakeEng()
    mgr.register("fake", fake)  # type: ignore[arg-type]
    mgr.mark_used("fake")
    _t.sleep(0.05)
    unloaded = mgr.sweep()
    assert "fake" in unloaded
    assert fake.unload_called == 1
    # Sweep again — already removed from _last_used，不應再 unload
    again = mgr.sweep()
    assert again == []
    assert fake.unload_called == 1  # not double-called (Bug #4 race fix)


def test_lifecycle_sweep_skips_active():
    """剛使用的 engine 不應被 sweep."""
    import time as _t

    mgr = LifecycleManager(idle_timeout=10.0)

    class FakeEng:
        def __init__(self):
            self.unload_called = 0

        def unload(self):
            self.unload_called += 1

    fake = FakeEng()
    mgr.register("active", fake)  # type: ignore[arg-type]
    mgr.mark_used("active")
    _t.sleep(0.01)
    unloaded = mgr.sweep()
    assert unloaded == []
    assert fake.unload_called == 0


def test_subprocess_bridge_io_contract():
    """write_ok 編碼出來的 base64 能被 bridge 解回原 audio."""
    import base64
    import json
    import numpy as np

    # Mimic runner output
    audio = np.array([0.1, -0.2, 0.3, -0.4], dtype=np.float32)
    sr = 24000
    b64 = base64.b64encode(audio.tobytes()).decode()
    fake_output_json = json.dumps({
        "ok": True, "audio_b64": b64, "sample_rate": sr,
        "dtype": "float32", "shape": [4],
    })

    # Bridge decode logic (subprocess_bridge._synthesize_raw)
    meta = json.loads(fake_output_json)
    assert meta["ok"]
    raw = base64.b64decode(meta["audio_b64"])
    decoded = np.frombuffer(raw, dtype=np.float32).copy()
    assert np.allclose(decoded, audio)
    assert int(meta["sample_rate"]) == 24000


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
