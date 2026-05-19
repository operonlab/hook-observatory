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

import os
from typing import Any

import httpx

from sdk_client.port_registry import get_url

from ._base import APIError


class TTSClient:
    """HTTP client for TTS station (port 10201)."""

    def __init__(self, base_url: str | None = None, timeout: float = 180):
        self.base_url = (
            base_url or os.environ.get("TTS_URL", get_url("tts"))
        ).rstrip("/")
        self._timeout = timeout
        self._client: httpx.Client | None = None

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
    ) -> dict:
        """v2 synthesize — JSON body, output ∈ {file,buffer,numpy,tensor,base64,stream}.

        Auto-routing: engine="auto" + lang → routing.py 預設選 (zh→indextts2_base /
        en→cosyvoice_v3_vllm / ja→indextts2_jmica)。
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
        return self._post_json("/v2/synthesize", body)

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
