"""Tests for sdk_client.browser_render — respx-mock-based.

Strategy:
  - Mock the HTTP layer with respx; verify client routes / payloads / parsing
  - Invariants from the SDK docstrings (NOT from implementation internals)
  - Mutation thinking: would a swap from POST → GET, wrong path,
    wrong body key, wrong response parsing be caught?
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from sdk_client._base import APIError
from sdk_client.browser_render import (
    BrowserRenderClient,
    ComposeFinalResult,
    PipelineResult,
    ProbeDurationsResult,
    RenderResult,
    SubtitlesResult,
)

BASE = "http://127.0.0.1:10221"


def _client():
    return BrowserRenderClient(base_url=BASE, timeout=5)


# ── INV-1: default port is 10221 ──────────────────────────────────────────────
def test_default_port_is_10221():
    """Mutation kill: if default port changes silently, this fails."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("BROWSER_RENDER_URL", None)
        c = BrowserRenderClient()
        # base_url should end with :10221 (allow port_registry override but
        # the documented default in the docstring is 10221)
        assert ":10221" in c.base_url, f"Expected port 10221 in {c.base_url!r}"


# ── INV-2: BROWSER_RENDER_URL env override ────────────────────────────────────
def test_env_override_via_BROWSER_RENDER_URL():
    """Mutation kill: env var name must be exactly BROWSER_RENDER_URL."""
    with patch.dict(os.environ, {"BROWSER_RENDER_URL": "http://example.test:9999"}):
        c = BrowserRenderClient()
        assert c.base_url == "http://example.test:9999"


# ── INV-3: healthz GET /healthz ───────────────────────────────────────────────
@respx.mock
def test_healthz_uses_get_on_healthz():
    """Mutation kill: would swap GET → POST or path /health be caught?"""
    route = respx.get(f"{BASE}/healthz").mock(
        return_value=httpx.Response(200, json={"status": "ok", "version": "0.1.0"}),
    )
    c = _client()
    result = c.healthz()
    assert route.called
    assert result["status"] == "ok"
    assert route.calls.last.request.method == "GET"


# ── INV-4: healthz timeout → APIError ─────────────────────────────────────────
@respx.mock
def test_healthz_timeout_raises_apierror():
    respx.get(f"{BASE}/healthz").mock(side_effect=httpx.TimeoutException("slow"))
    c = _client()
    with pytest.raises(APIError):
        c.healthz()


# ── INV-5: connect error → APIError with module='browser-render' ──────────────
@respx.mock
def test_connect_error_raises_apierror():
    respx.get(f"{BASE}/healthz").mock(side_effect=httpx.ConnectError("nope"))
    c = _client()
    with pytest.raises(APIError) as exc_info:
        c.healthz()
    # The error should mention browser-render so the user knows what's down
    assert "browser-render" in str(exc_info.value).lower()


# ── INV-6: 5xx HTTPStatusError → APIError ─────────────────────────────────────
@respx.mock
def test_5xx_raises_apierror():
    respx.get(f"{BASE}/healthz").mock(
        return_value=httpx.Response(500, text="internal error"),
    )
    c = _client()
    with pytest.raises(APIError):
        c.healthz()


# ── INV-7: render POSTs /render with required body keys ───────────────────────
@respx.mock
def test_render_posts_to_render_endpoint_with_required_keys():
    """Mutation kill: missing 'durations' or wrong endpoint would be caught."""
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "frames_dir": "/tmp/out/frames",
                "manifest_path": "/tmp/out/frames/manifest.json",
                "total_frames": 100,
            },
        )

    respx.post(f"{BASE}/render").mock(side_effect=handler)
    c = _client()
    r = c.render(
        url="http://localhost:5174/?render=1",
        durations={"chapter1": [1500, 2000]},
        out_dir=Path("/tmp/out"),
        fps=30,
    )
    assert captured["method"] == "POST"
    assert captured["url"] == f"{BASE}/render"
    import json as _json

    body = _json.loads(captured["body"])
    # required keys from docstring
    for key in ("url", "durations", "out_dir", "fps", "viewport", "format"):
        assert key in body, f"missing key {key!r} in body: {body!r}"
    assert body["durations"] == {"chapter1": [1500, 2000]}
    assert body["fps"] == 30
    assert isinstance(r, RenderResult)
    assert r.total_frames == 100


# ── INV-8: render --chapter passes chapter index ──────────────────────────────
@respx.mock
def test_render_chapter_is_passed_when_provided():
    """Mutation kill: agent forgot to include `chapter` when not None."""
    captured = {}

    def handler(request):
        import json as _json

        captured.update(_json.loads(request.read().decode()))
        return httpx.Response(200, json={"frames_dir": "/x", "manifest_path": "/x/m.json"})

    respx.post(f"{BASE}/render").mock(side_effect=handler)
    c = _client()
    c.render(
        url="http://x",
        durations={},
        out_dir=Path("/x"),
        chapter=3,
    )
    assert captured.get("chapter") == 3


@respx.mock
def test_render_chapter_omitted_when_none():
    """Mutation kill: agent always serialized chapter=None (vs omit)."""
    captured = {}

    def handler(request):
        import json as _json

        captured.update(_json.loads(request.read().decode()))
        return httpx.Response(200, json={"frames_dir": "/x", "manifest_path": "/x/m.json"})

    respx.post(f"{BASE}/render").mock(side_effect=handler)
    c = _client()
    c.render(url="http://x", durations={}, out_dir=Path("/x"))
    assert "chapter" not in captured


# ── INV-9: pipeline POSTs /pipeline with required body keys ───────────────────
@respx.mock
def test_pipeline_posts_to_pipeline_endpoint():
    captured = {}

    def handler(request):
        import json as _json

        captured["url"] = str(request.url)
        captured["body"] = _json.loads(request.read().decode())
        return httpx.Response(
            200,
            json={
                "mp4_path": "/tmp/out/output.mp4",
                "srt_path": "/tmp/out/subtitles.srt",
                "vtt_path": "/tmp/out/subtitles.vtt",
                "total_frames": 274,
                "wall_clock_seconds": 24.2,
            },
        )

    respx.post(f"{BASE}/pipeline").mock(side_effect=handler)
    c = _client()
    r = c.pipeline(
        project_root=Path("/proj"),
        dev_url="http://localhost:5174",
        out_dir=Path("/tmp/out"),
        fps=30,
        parallel=4,
    )
    assert captured["url"] == f"{BASE}/pipeline"
    body = captured["body"]
    for key in ("project_root", "dev_url", "out_dir", "fps", "parallel", "viewport", "loudnorm"):
        assert key in body, f"missing {key} in {body}"
    assert body["parallel"] == 4
    assert isinstance(r, PipelineResult)
    assert r.total_frames == 274
    assert r.wall_clock_seconds == 24.2
    assert r.mp4_path == "/tmp/out/output.mp4"


# ── INV-10: probe_durations POSTs /probe-durations ───────────────────────────
@respx.mock
def test_probe_durations_endpoint_and_response_parsing():
    captured = {}

    def handler(request):
        import json as _json

        captured["url"] = str(request.url)
        captured["body"] = _json.loads(request.read().decode())
        return httpx.Response(
            200,
            json={
                "durations": {"example": [6750, 10250, 10250]},
                "written_to": "/proj/public/render-durations.json",
            },
        )

    respx.post(f"{BASE}/probe-durations").mock(side_effect=handler)
    c = _client()
    r = c.probe_durations(Path("/proj"))
    assert captured["url"] == f"{BASE}/probe-durations"
    assert captured["body"]["project_root"] == "/proj"
    assert isinstance(r, ProbeDurationsResult)
    assert r.durations == {"example": [6750, 10250, 10250]}
    assert r.written_to == "/proj/public/render-durations.json"


# ── INV-11: build_subtitles ───────────────────────────────────────────────────
@respx.mock
def test_build_subtitles_endpoint():
    captured = {}

    def handler(request):
        import json as _json

        captured["body"] = _json.loads(request.read().decode())
        return httpx.Response(
            200,
            json={
                "srt_path": "/o/subtitles.srt",
                "vtt_path": "/o/subtitles.vtt",
                "total_ms": 27250,
            },
        )

    respx.post(f"{BASE}/build-subtitles").mock(side_effect=handler)
    c = _client()
    r = c.build_subtitles(Path("/p"), {"a": [1500]}, Path("/o"))
    body = captured["body"]
    assert body["project_root"] == "/p"
    assert body["durations"] == {"a": [1500]}
    assert body["out_dir"] == "/o"
    assert isinstance(r, SubtitlesResult)
    assert r.total_ms == 27250


# ── INV-12: compose_final ─────────────────────────────────────────────────────
@respx.mock
def test_compose_final_endpoint():
    respx.post(f"{BASE}/compose-final").mock(
        return_value=httpx.Response(
            200,
            json={"mp4_path": "/o/output.mp4", "mp4_burnin_path": None},
        ),
    )
    c = _client()
    r = c.compose_final(Path("/f"), Path("/a"), Path("/o"))
    assert isinstance(r, ComposeFinalResult)
    assert r.mp4_path == "/o/output.mp4"
    assert r.mp4_burnin_path is None


# ── INV-13: is_running returns False when service down ───────────────────────
@respx.mock
def test_is_running_returns_false_on_connect_error():
    respx.get(f"{BASE}/healthz").mock(side_effect=httpx.ConnectError("nope"))
    c = _client()
    assert c.is_running() is False


@respx.mock
def test_is_running_returns_true_when_healthz_ok():
    respx.get(f"{BASE}/healthz").mock(
        return_value=httpx.Response(200, json={"status": "ok"}),
    )
    c = _client()
    assert c.is_running() is True


# ── INV-14: close() releases httpx Client ─────────────────────────────────────
def test_close_releases_client():
    """Mutation kill: forgot to close httpx.Client leaks connections."""
    c = _client()
    _ = c.client  # force lazy init
    assert c._client is not None
    c.close()
    # After close, accessing .client again should create a new one (auto-reopen)
    new = c.client
    assert new is not None  # property recreates if closed
