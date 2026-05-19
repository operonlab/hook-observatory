"""TTS SDK — HTTP client for TTS station (port 10201).

v1 (existing): /synthesize, /voices, /engines — POST query-params.
v2 (new):      /v2/synthesize, /v2/engines, /v2/voices, /v2/route, /v2/lifecycle
               — JSON body, unified OutputMode (file/buffer/numpy/tensor/base64/stream),
               auto-routing (engine="auto" + lang).

Usage:
    from sdk_client.tts import TTSClient

    client = TTSClient()
    res = client.synthesize_v2("你好", lang="zh", voice="master", out_path="/tmp/o.wav")
    print(res["audio_path"])
"""

import logging
import os
import time
from typing import Any

import httpx

from sdk_client.port_registry import get_url

from ._base import APIError

logger = logging.getLogger(__name__)

# ---- Offline fallback config ----
# 當 v2 (win-gpu) service 連不上時，自動降級到 v1 Mac engine。
# Mac engine 永遠在 Mac 本機，cosyvoice/indextts/vibevoice 等 GPU engine 需 win-gpu。

# lang → v1 engine (Mac native，永遠可用)
_V1_FALLBACK_BY_LANG = {
    "zh": "qwen3-tts",   # mlx-audio Mac 版（注意：不是 v2 的 qwen3tts_gpu）
    "en": "qwen3-tts",   # mlx-audio 也支援英文，音色一致性勝跨 engine
    "ja": "qwen3-tts",   # mlx-audio 4 lang native
    "ko": "qwen3-tts",
}
_V1_FALLBACK_DEFAULT = "edge"  # 雲端 fallback；mlx-audio 載不出時走 edge

# Circuit breaker — v2 連不上後冷卻 N 秒不重試，避免每次都吃 ConnectError 超時
_V2_FAILURE_COOLDOWN_SEC = float(os.environ.get("TTS_V2_COOLDOWN_SEC", "30"))


class TTSClient:
    """HTTP client for TTS station (port 10201)."""

    def __init__(self, base_url: str | None = None, timeout: float = 180):
        self.base_url = (
            base_url or os.environ.get("TTS_URL", get_url("tts"))
        ).rstrip("/")
        self._timeout = timeout
        self._client: httpx.Client | None = None
        # Circuit breaker — last v2 connect failure timestamp
        self._v2_last_failure_ts: float = 0.0

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def _request(
        self, method: str, path: str, timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(method, url, timeout=timeout or self._timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise APIError(
                0,
                f"Cannot connect to TTS at {self.base_url}. "
                "Start server: cd stations/tts && .venv/bin/python3 main.py",
                module="tts",
            ) from None
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500], module="tts") from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post_params(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("POST", path, params=filtered).json()

    def _post_json(self, path: str, body: dict | None = None) -> Any:
        return self._request("POST", path, json=body or {}).json()

    # ======================== Health ========================

    def health(self) -> dict:
        return self._get("/health")

    def is_running(self) -> bool:
        try:
            self.health()
            return True
        except Exception:
            return False

    def healthz_v2(self) -> dict:
        return self._get("/v2/healthz")

    # ======================== v1 Synthesize (backwards compat) ========================

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        engine: str = "apple",
        format: str = "wav",
    ) -> dict:
        """v1 synthesize — query-params, single-shot file output."""
        return self._post_params(
            "/synthesize",
            params={
                "text": text, "voice": voice, "speed": speed,
                "engine": engine, "format": format,
            },
        )

    # ======================== v2 Synthesize (unified OutputMode) ========================

    def synthesize_v2(
        self,
        text: str,
        lang: str,
        voice: str = "master",
        engine: str = "auto",
        output: str = "file",
        out_path: str | None = None,
        target_sample_rate: int | None = None,
        speed: float = 1.0,
        engine_specific: dict | None = None,
        allow_fallback: bool = True,
    ) -> dict:
        """v2 synthesize — JSON body, output ∈ {file,buffer,numpy,tensor,base64,stream}.

        Auto-routing: engine="auto" + lang → routing.py 預設選 (zh/en→indextts2_base,
        ja→indextts2_jmica, ko→qwen3tts_gpu, multi_speaker→vibevoice).

        Offline fallback: 若 v2 service (win-gpu) 連不上且 allow_fallback=True，
        自動降級到 v1 Mac engine（mlx-qwen3 / edge）。同 circuit breaker 30s 冷卻。
        """
        body: dict[str, Any] = {
            "text": text,
            "lang": lang,
            "voice_id": voice,
            "engine": engine,
            "output": output,
            "speed": speed,
            "engine_specific": engine_specific or {},
        }
        if out_path:
            body["output_path"] = out_path
        if target_sample_rate:
            body["target_sample_rate"] = target_sample_rate

        # Circuit breaker — 若最近 v2 連不上，直接走 fallback 不再嘗試
        if allow_fallback and self._v2_in_cooldown():
            logger.info(
                "TTS v2 in cooldown (%.1fs left), using v1 fallback",
                self._v2_cooldown_remaining(),
            )
            return self._fallback_to_v1(text, lang, voice, speed, out_path)

        try:
            return self._post_json("/v2/synthesize", body)
        except APIError as e:
            # ConnectError → APIError(0, ...). 其他狀態（400 / 500）不 fallback —
            # 那些是真正的 user-input bug，fallback 會遮蓋問題。
            if e.status_code == 0 and allow_fallback:
                logger.warning(
                    "TTS v2 unreachable (%s), falling back to v1 Mac engine", e
                )
                self._v2_last_failure_ts = time.monotonic()
                return self._fallback_to_v1(text, lang, voice, speed, out_path)
            raise

    # ---- Offline fallback helpers ----

    def _v2_in_cooldown(self) -> bool:
        return self._v2_cooldown_remaining() > 0

    def _v2_cooldown_remaining(self) -> float:
        if self._v2_last_failure_ts == 0:
            return 0.0
        elapsed = time.monotonic() - self._v2_last_failure_ts
        return max(0.0, _V2_FAILURE_COOLDOWN_SEC - elapsed)

    def reset_v2_circuit(self) -> None:
        """Manually clear circuit breaker (e.g. after operator reboots win-gpu)."""
        self._v2_last_failure_ts = 0.0

    def _fallback_to_v1(
        self,
        text: str,
        lang: str,
        voice: str,
        speed: float,
        out_path: str | None,
    ) -> dict:
        """Translate v2 → v1 API + best-effort engine selection."""
        v1_engine = _V1_FALLBACK_BY_LANG.get(lang, _V1_FALLBACK_DEFAULT)
        v1_result = self._post_params(
            "/synthesize",
            params={
                "text": text,
                "voice": voice if v1_engine != "edge" else "default",
                "speed": speed,
                "engine": v1_engine,
                "format": "wav",
            },
        )
        # Wrap v1 response into v2-shaped dict so caller code doesn't break
        return {
            "duration_s": v1_result.get("duration", 0),
            "sample_rate": v1_result.get("sample_rate", 24000),
            "rtf": 0.0,
            "engine": f"{v1_engine}_fallback",
            "output_mode": "file",
            "audio_path": v1_result.get("audio_path"),
            "fallback": True,
            "fallback_reason": "v2 unreachable" if not self._v2_in_cooldown() else "v2 cooldown",
        }

    # ======================== v1 Voices / Engines ========================

    def list_voices(self, engine: str = "apple") -> dict:
        return self._get("/voices", params={"engine": engine})

    def list_engines(self) -> dict:
        return self._get("/engines")

    # ======================== v2 Voices / Engines / Routing ========================

    def list_voices_v2(self) -> dict:
        return self._get("/v2/voices")

    def list_engines_v2(self) -> dict:
        return self._get("/v2/engines")

    def engine_detail(self, name: str) -> dict:
        return self._get(f"/v2/engines/{name}")

    def explain_route(
        self, lang: str, multi_speaker: bool = False, prefer_fast: bool = False
    ) -> dict:
        return self._get(
            "/v2/route",
            {"lang": lang, "multi_speaker": multi_speaker, "prefer_fast": prefer_fast},
        )

    # ======================== Lifecycle ========================

    def lifecycle_status(self) -> dict:
        return self._get("/v2/lifecycle")

    def lifecycle_sweep(self) -> dict:
        return self._post_json("/v2/lifecycle/sweep")

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"TTSClient(base_url={self.base_url!r})"
