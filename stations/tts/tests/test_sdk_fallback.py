"""SDK offline-fallback tests — TTSClient.synthesize_v2 win-gpu down 場景.

對應 step 5：v2 (win-gpu) ConnectError 時自動降級 v1 Mac engine。
跑這份 test：
    PYTHONPATH=stations/tts:libs/sdk-client \
      /tmp/_pytest_venv/bin/pytest stations/tts/tests/test_sdk_fallback.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "libs" / "sdk-client"))

from sdk_client._base import APIError
from sdk_client.tts import TTSClient


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("", request=None, response=self)  # type: ignore[arg-type]

    def json(self):
        return self._payload


def _make_client_with_v2_unreachable():
    """TTSClient where /v2/synthesize raises ConnectError, /synthesize returns fake v1 result."""
    client = TTSClient(base_url="http://127.0.0.1:65535")  # 不會通的 port

    v1_calls: list[dict] = []

    def fake_request(method, path, timeout=None, **kwargs):
        if path == "/v2/synthesize":
            raise APIError(0, "Cannot connect to TTS", module="tts")
        if path == "/synthesize":
            v1_calls.append(kwargs.get("params", {}))
            return _FakeResponse(
                200,
                {"audio_path": "/tmp/fake.wav", "duration": 2.5, "sample_rate": 24000, "engine": kwargs.get("params", {}).get("engine", "?")},
            )
        raise NotImplementedError(path)

    client._request = fake_request  # type: ignore[assignment]
    return client, v1_calls


def test_fallback_on_v2_unreachable():
    """v2 ConnectError → 自動降級 v1，回 wrapped 結構."""
    client, v1_calls = _make_client_with_v2_unreachable()

    result = client.synthesize_v2("你好", lang="zh", voice="master")

    assert result["fallback"] is True
    assert result["engine"].endswith("_fallback")
    assert result["audio_path"] == "/tmp/fake.wav"
    # 應對 zh 走 qwen3-tts (mlx)
    assert v1_calls[0]["engine"] == "qwen3-tts"
    assert v1_calls[0]["text"] == "你好"


def test_fallback_lang_routing():
    """每個 lang 都該對到正確的 v1 engine."""
    for lang in ("zh", "en", "ja", "ko"):
        client, v1_calls = _make_client_with_v2_unreachable()
        client.synthesize_v2("test", lang=lang)
        assert v1_calls[0]["engine"] == "qwen3-tts", f"lang={lang}"


def test_fallback_unknown_lang_uses_edge():
    """未知 lang → edge (cloud fallback)."""
    client, v1_calls = _make_client_with_v2_unreachable()
    client.synthesize_v2("bonjour", lang="fr")
    assert v1_calls[0]["engine"] == "edge"
    assert v1_calls[0]["voice"] == "default"  # edge 不認 master


def test_circuit_breaker_cooldown():
    """連續兩次呼叫只該打 v2 一次（第二次走 cooldown）."""
    client = TTSClient(base_url="http://127.0.0.1:65535")

    v2_attempts = 0
    v1_attempts = 0

    def fake_request(method, path, timeout=None, **kwargs):
        nonlocal v2_attempts, v1_attempts
        if path == "/v2/synthesize":
            v2_attempts += 1
            raise APIError(0, "Cannot connect", module="tts")
        if path == "/synthesize":
            v1_attempts += 1
            return _FakeResponse(200, {
                "audio_path": "/tmp/x.wav", "duration": 1, "sample_rate": 24000, "engine": "qwen3-tts"
            })

    client._request = fake_request  # type: ignore[assignment]

    # First call → tries v2, fails, falls back
    client.synthesize_v2("a", lang="en")
    # Second call → circuit open, should skip v2 entirely
    client.synthesize_v2("b", lang="en")

    assert v2_attempts == 1, "v2 should only be tried once during cooldown"
    assert v1_attempts == 2


def test_circuit_reset_after_manual():
    """reset_v2_circuit() 後下一次重新嘗試 v2."""
    client = TTSClient(base_url="http://127.0.0.1:65535")

    v2_attempts = 0

    def fake_request(method, path, timeout=None, **kwargs):
        nonlocal v2_attempts
        if path == "/v2/synthesize":
            v2_attempts += 1
            raise APIError(0, "boom", module="tts")
        if path == "/synthesize":
            return _FakeResponse(200, {
                "audio_path": "/tmp/x.wav", "duration": 1, "sample_rate": 24000, "engine": "qwen3-tts"
            })

    client._request = fake_request  # type: ignore[assignment]

    client.synthesize_v2("a", lang="en")
    assert v2_attempts == 1
    client.synthesize_v2("b", lang="en")  # cooldown skip
    assert v2_attempts == 1

    client.reset_v2_circuit()
    client.synthesize_v2("c", lang="en")  # tries v2 again
    assert v2_attempts == 2


def test_no_fallback_on_400():
    """v2 回 400 (user-input bug) 不該降級 — 必須暴露錯誤."""
    client = TTSClient(base_url="http://127.0.0.1:65535")

    def fake_request(method, path, timeout=None, **kwargs):
        if path == "/v2/synthesize":
            raise APIError(400, "Invalid lang", module="tts")
        raise NotImplementedError

    client._request = fake_request  # type: ignore[assignment]

    with pytest.raises(APIError) as exc:
        client.synthesize_v2("hi", lang="invalid_lang")
    assert exc.value.status_code == 400


def test_no_fallback_when_disabled():
    """allow_fallback=False 即使 v2 不通也不降級."""
    client = TTSClient(base_url="http://127.0.0.1:65535")

    def fake_request(method, path, timeout=None, **kwargs):
        raise APIError(0, "Cannot connect", module="tts")

    client._request = fake_request  # type: ignore[assignment]

    with pytest.raises(APIError):
        client.synthesize_v2("hi", lang="zh", allow_fallback=False)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
