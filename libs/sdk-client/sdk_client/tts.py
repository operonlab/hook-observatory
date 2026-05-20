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

import base64
import json
import logging
import os
import time
from collections.abc import Iterator
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
    "zh": "qwen3-tts",  # mlx-audio Mac 版（注意：不是 v2 的 qwen3tts_gpu）
    "en": "qwen3-tts",  # mlx-audio 也支援英文，音色一致性勝跨 engine
    "ja": "qwen3-tts",  # mlx-audio 4 lang native
    "ko": "qwen3-tts",
}
_V1_FALLBACK_DEFAULT = "edge"  # 雲端 fallback；mlx-audio 載不出時走 edge

# Circuit breaker — v2 連不上後冷卻 N 秒不重試，避免每次都吃 ConnectError 超時
_V2_FAILURE_COOLDOWN_SEC = float(os.environ.get("TTS_V2_COOLDOWN_SEC", "30"))


class TTSClient:
    """HTTP client for TTS station (port 10201)."""

    # ── engine_specific helpers (purely string assembly — no network) ──
    # Locked to worker_indextts_daemon.EMOTION_PRESETS keys; new names must
    # be added in both places together.
    EMOTION_NAMES = (
        "happy", "angry", "sad", "afraid",
        "disgusted", "melancholic", "surprised", "calm", "neutral",
    )

    # alpha=0.4 chosen from speaker-similarity sweep (outputs/tts-emotion-smoke/
    # similarity_bar.png, 2026-05-20). Resemblyzer d-vector vs master.wav:
    #   alpha 0.2 → 0.890 (~ baseline 0.872, emotion barely audible)
    #   alpha 0.4 → 0.841  ← sweet spot: emotion clear, voice still recognisable
    #   alpha 0.6 → 0.794  (audible drift)
    #   alpha 0.8 → 0.664  ← cliff: voice identity collapses
    #   alpha 1.0 → 0.681
    # IndexTTS-2's emo_vec is additive to the conditioning mel, so strong
    # emotion overwhelms speaker identity by design. Callers who genuinely
    # need maximum emotion expressiveness can pass alpha=1.0 explicitly.
    DEFAULT_EMOTION_ALPHA = 0.4

    @staticmethod
    def emotion_preset(name: str, alpha: float | None = None) -> dict:
        """Build engine_specific={"emotion":...} for IndexTTS-2 preset mode.

        alpha defaults to DEFAULT_EMOTION_ALPHA (0.4) — chosen from a sweep
        showing voice fidelity holds until alpha=0.6 then collapses.
        """
        if name not in TTSClient.EMOTION_NAMES:
            raise ValueError(
                f"unknown emotion '{name}'; choose from {TTSClient.EMOTION_NAMES}"
            )
        a = TTSClient.DEFAULT_EMOTION_ALPHA if alpha is None else float(alpha)
        return {"emotion": {"preset": name, "alpha": a}}

    @staticmethod
    def emotion_text(text: str, alpha: float | None = None) -> dict:
        """Build engine_specific for IndexTTS-2 emotion-from-text mode."""
        a = TTSClient.DEFAULT_EMOTION_ALPHA if alpha is None else float(alpha)
        return {"emotion": {"text": text, "alpha": a}}

    @staticmethod
    def emotion_audio(audio_path: str, alpha: float | None = None) -> dict:
        """Build engine_specific for IndexTTS-2 emotion-from-audio mode."""
        a = TTSClient.DEFAULT_EMOTION_ALPHA if alpha is None else float(alpha)
        return {"emotion": {"audio": audio_path, "alpha": a}}

    @staticmethod
    def instruct(text: str) -> dict:
        """Build engine_specific={"instruct":...} for CosyVoice instruct2."""
        return {"instruct": text}

    @staticmethod
    def wrap_laughter(text: str) -> str:
        """Wrap a span in CosyVoice's <laughter>...</laughter> tag."""
        return f"<laughter>{text}</laughter>"

    @staticmethod
    def wrap_strong(text: str) -> str:
        """Wrap a span in CosyVoice's <strong>...</strong> tag."""
        return f"<strong>{text}</strong>"

    def __init__(self, base_url: str | None = None, timeout: float = 180):
        self.base_url = (base_url or os.environ.get("TTS_URL", get_url("tts"))).rstrip("/")
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
                "text": text,
                "voice": voice,
                "speed": speed,
                "engine": engine,
                "format": format,
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
        mode: str | None = None,
    ) -> dict:
        """v2 synthesize — JSON body, output ∈ {file,buffer,numpy,tensor,base64,stream}.

        Auto-routing presets (mode):
          "quality" (default) — indextts2_base/jmica (best fidelity, RTF ~1.0)
          "live"              — cosyvoice_v3_native (sub-realtime, RTF 0.5-0.8)
        engine="<name>" overrides preset entirely.

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
        if mode is not None:
            body["mode"] = mode
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
                logger.warning("TTS v2 unreachable (%s), falling back to v1 Mac engine", e)
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

    # ======================== v2 Long-text synthesis ========================

    def synthesize_long(
        self,
        text: str,
        lang: str,
        voice: str = "master",
        engine: str = "auto",
        output: str = "buffer",
        out_path: str | None = None,
        max_chars: int | None = None,
        speed: float = 1.0,
        mode: str | None = None,
        engine_specific: dict | None = None,
    ) -> dict:
        """POST /v2/synthesize/long — auto-segment + per-segment synth + concat.

        TTS engines (cosyvoice / qwen3 / vibevoice / indextts2) degrade on inputs
        beyond ~150 zh chars. This endpoint splits at sentence/punctuation
        boundaries and concatenates the resulting waveforms server-side.

        engine_specific applies to every segment (whole-passage emotion /
        instruct). Pass `TTSClient.emotion_preset("sad")` or similar helpers
        for ergonomics, or `{"instruct": "..."}` for CosyVoice instruct.

        Returns the standard v2 payload (duration_s, sample_rate, engine,
        output_mode, audio_path/audio_bytes_b64/audio_base64) plus:
            - segments: int
            - seg_durations_s: list[float]
            - seg_chunks: list[str]  (echo of how text was split, for debug)
        """
        body: dict[str, Any] = {
            "text": text,
            "lang": lang,
            "voice_id": voice,
            "engine": engine,
            "output": output,
            "speed": speed,
        }
        if mode is not None:
            body["mode"] = mode
        if out_path:
            body["output_path"] = out_path
        if max_chars is not None:
            body["max_chars"] = max_chars
        if engine_specific:
            body["engine_specific"] = engine_specific
        return self._post_json("/v2/synthesize/long", body)

    # ======================== v2 Multi-speaker podcast ========================

    def synthesize_podcast(
        self,
        script: str,
        voices: dict[str, str],
        lang: str = "zh",
        engine: str = "auto",
        output: str = "base64",
        out_path: str | None = None,
        speed: float = 1.0,
        mode: str | None = None,
        engine_specific: dict | None = None,
        engine_specific_by_speaker: dict[str, dict] | None = None,
    ) -> dict:
        """POST /v2/synthesize/podcast — multi-speaker fake-via-dispatch.

        Script uses "Speaker N: text" lines (one speaker per line). `voices`
        maps speaker id → voice_id; each segment is dispatched to the engine
        with the corresponding reference. vibevoice currently runs in the
        same fake-dispatch mode as the others; native multi-speaker would
        need a worker-side opcode extension.

        engine_specific is a default applied to every segment;
        engine_specific_by_speaker fully overrides the default per speaker
        id (no shallow-merge — give the full dict for that speaker).
        """
        body: dict[str, Any] = {
            "script": script,
            "voices": {str(k): v for k, v in voices.items()},
            "lang": lang,
            "engine": engine,
            "output": output,
            "speed": speed,
        }
        if mode is not None:
            body["mode"] = mode
        if out_path:
            body["output_path"] = out_path
        if engine_specific:
            body["engine_specific"] = engine_specific
        if engine_specific_by_speaker:
            body["engine_specific_by_speaker"] = {
                str(k): v for k, v in engine_specific_by_speaker.items()
            }
        return self._post_json("/v2/synthesize/podcast", body)

    # ======================== v2 SSE streaming ========================

    def synthesize_stream(
        self,
        text: str,
        lang: str,
        voice: str = "master",
        engine: str = "auto",
        max_chars: int | None = None,
        speed: float = 1.0,
        ref_text: str | None = None,
        timeout: float = 600.0,
        mode: str | None = None,
        engine_specific: dict | None = None,
    ) -> Iterator[dict[str, Any]]:
        """POST /v2/synthesize/stream — SSE generator yielding parsed events.

        Yields dicts with `event` ∈ {"meta", "audio", "done", "error"} and the
        parsed `data` payload. For "audio" events `data["audio"]` is decoded
        bytes (raw float32 PCM at the sample_rate announced in meta); `data["audio_b64"]`
        is preserved if caller wants to forward unmodified.

        Engines with safe_rtf > 2.5 (e.g. indextts2) are rejected server-side
        with HTTP 400 directing to /v2/synthesize/long; this method re-raises
        APIError in that case.

        Example:
            meta = None
            chunks = []
            for evt in client.synthesize_stream("...", lang="zh", engine="vibevoice"):
                if evt["event"] == "meta": meta = evt["data"]
                elif evt["event"] == "audio": chunks.append(evt["data"]["audio"])
                elif evt["event"] == "done": print(evt["data"])
        """
        body: dict[str, Any] = {
            "text": text,
            "lang": lang,
            "voice_id": voice,
            "engine": engine,
            "speed": speed,
        }
        if mode is not None:
            body["mode"] = mode
        if max_chars is not None:
            body["max_chars"] = max_chars
        if ref_text is not None:
            body["ref_text"] = ref_text
        if engine_specific:
            body["engine_specific"] = engine_specific

        with self.client.stream(
            "POST",
            f"{self.base_url}/v2/synthesize/stream",
            json=body,
            timeout=timeout,
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                detail = resp.text
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                raise APIError(resp.status_code, detail)

            event_name: str | None = None
            data_buf = ""
            for raw in resp.iter_lines():
                line = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
                line = line.rstrip("\r")
                if line.startswith("event: "):
                    event_name = line[7:].strip()
                elif line.startswith("data: "):
                    data_buf = line[6:]
                elif line == "" and event_name and data_buf:
                    try:
                        payload = json.loads(data_buf)
                    except Exception as e:
                        logger.warning("bad SSE data on event %s: %s", event_name, e)
                        event_name, data_buf = None, ""
                        continue
                    if event_name == "audio" and "audio_b64" in payload:
                        payload["audio"] = base64.b64decode(payload["audio_b64"])
                    yield {"event": event_name, "data": payload}
                    if event_name in ("done", "error"):
                        return
                    event_name, data_buf = None, ""

    # ======================== v2 Voices / Engines / Routing ========================

    def list_voices_v2(self) -> dict:
        return self._get("/v2/voices")

    def list_engines_v2(self) -> dict:
        return self._get("/v2/engines")

    def engine_detail(self, name: str) -> dict:
        return self._get(f"/v2/engines/{name}")

    def explain_route(
        self,
        lang: str,
        multi_speaker: bool = False,
        prefer_fast: bool = False,
        mode: str | None = None,
    ) -> dict:
        params = {
            "lang": lang,
            "multi_speaker": multi_speaker,
            "prefer_fast": prefer_fast,
        }
        if mode is not None:
            params["mode"] = mode
        return self._get("/v2/route", params)

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
