"""BrowserRender SDK — HTTP client for browser-render station (port 10221).

HTTP API (axum-based Rust station):
    POST /render         — render URL to frames
    POST /pipeline       — full pipeline: probe + render + subtitles + compose
    POST /probe-durations — probe chapter durations from project
    POST /build-subtitles — build .srt / .vtt from narrations + durations
    POST /compose-final  — compose frames + audio → mp4
    GET  /healthz        — liveness probe

Usage:
    from sdk_client.browser_render import BrowserRenderClient
    from pathlib import Path

    client = BrowserRenderClient()
    result = client.pipeline(
        project_root=Path("./presentation"),
        dev_url="http://localhost:5174",
        out_dir=Path("./dist-video"),
        fps=30,
        parallel=4,
    )
    print(result["mp4_path"])
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

from ._base import APIError

logger = logging.getLogger(__name__)

# Default port for browser-render station.
# Agent A will add BROWSER_RENDER = 10221 to port_registry.yaml.
# Until then we try to load from registry with a fallback.
_DEFAULT_PORT = 10221
_DEFAULT_BASE_URL = f"http://127.0.0.1:{_DEFAULT_PORT}"


def _resolve_base_url() -> str:
    """Resolve base URL: env var → port_registry → hardcoded fallback."""
    env = os.environ.get("BROWSER_RENDER_URL")
    if env:
        return env.rstrip("/")
    try:
        from sdk_client.port_registry import get_url

        return get_url("browser-render")
    except KeyError:
        logger.warning(
            "browser-render not found in port_registry — falling back to %s. "
            "Add BROWSER_RENDER=10221 to shared/schemas/port_registry.yaml.",
            _DEFAULT_BASE_URL,
        )
        return _DEFAULT_BASE_URL


# ── Result dataclasses (typed dicts for now, proper dataclasses when spec firms) ──


class RenderResult:
    """Result of a single /render call."""

    __slots__ = ("frames_dir", "manifest_path", "raw", "total_frames")

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.frames_dir: str = data.get("frames_dir", "")
        self.manifest_path: str = data.get("manifest_path", "")
        self.total_frames: int = data.get("total_frames", 0)

    def __repr__(self) -> str:
        return f"RenderResult(frames_dir={self.frames_dir!r}, total_frames={self.total_frames})"


class PipelineResult:
    """Result of a full /pipeline call."""

    __slots__ = (
        "mp4_burnin_path",
        "mp4_path",
        "raw",
        "srt_path",
        "total_frames",
        "vtt_path",
        "wall_clock_seconds",
    )

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.mp4_path: str = data.get("mp4_path", "")
        self.mp4_burnin_path: str | None = data.get("mp4_burnin_path")
        self.srt_path: str = data.get("srt_path", "")
        self.vtt_path: str = data.get("vtt_path", "")
        self.total_frames: int = data.get("total_frames", 0)
        self.wall_clock_seconds: float = data.get("wall_clock_seconds", 0.0)

    def __repr__(self) -> str:
        return (
            f"PipelineResult(mp4_path={self.mp4_path!r}, "
            f"total_frames={self.total_frames}, "
            f"wall_clock_seconds={self.wall_clock_seconds:.1f}s)"
        )


class ProbeDurationsResult:
    """Result of a /probe-durations call."""

    __slots__ = ("durations", "raw", "written_to")

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.durations: dict[str, list[int]] = data.get("durations", {})
        self.written_to: str = data.get("written_to", "")

    def __repr__(self) -> str:
        chapters = list(self.durations.keys())
        return f"ProbeDurationsResult(chapters={chapters!r}, written_to={self.written_to!r})"


class SubtitlesResult:
    """Result of a /build-subtitles call."""

    __slots__ = ("raw", "srt_path", "total_ms", "vtt_path")

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.srt_path: str = data.get("srt_path", "")
        self.vtt_path: str = data.get("vtt_path", "")
        self.total_ms: int = data.get("total_ms", 0)

    def __repr__(self) -> str:
        return f"SubtitlesResult(srt_path={self.srt_path!r}, total_ms={self.total_ms})"


class ComposeFinalResult:
    """Result of a /compose-final call."""

    __slots__ = ("mp4_burnin_path", "mp4_path", "raw")

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.mp4_path: str = data.get("mp4_path", "")
        self.mp4_burnin_path: str | None = data.get("mp4_burnin_path")

    def __repr__(self) -> str:
        return f"ComposeFinalResult(mp4_path={self.mp4_path!r})"


# ── Client ────────────────────────────────────────────────────────────────────


class BrowserRenderClient:
    """HTTP client for browser-render station (port 10221).

    The station is a Rust axum service that uses chromiumoxide + CDP virtual
    time to render web apps deterministically into frames, then compose mp4.

    Args:
        base_url: Station URL. Checks BROWSER_RENDER_URL env first,
                  then port_registry "browser-render", then fallback 10221.
        timeout:  Default request timeout (seconds). Render jobs can be slow;
                  use per-call ``timeout`` overrides when needed.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 60,
    ) -> None:
        self.base_url = (base_url or _resolve_base_url()).rstrip("/")
        self._timeout = timeout
        self._client: httpx.Client | None = None

    # ── httpx client lifecycle ────────────────────────────────

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    # ── Internal helpers ──────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(
                method,
                url,
                timeout=timeout or self._timeout,
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise APIError(
                0,
                f"Cannot connect to browser-render at {self.base_url}. "
                "Start: launchctl start workshop.browser-render "
                "or: cd stations/browser-render && cargo run",
                module="browser-render",
            ) from None
        except httpx.TimeoutException as e:
            raise APIError(
                0,
                f"Request to browser-render timed out after {timeout or self._timeout}s. "
                "Consider increasing timeout for long render jobs.",
                module="browser-render",
            ) from e
        except httpx.HTTPStatusError as e:
            raise APIError(
                e.response.status_code,
                e.response.text[:500],
                module="browser-render",
            ) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(
        self,
        path: str,
        body: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._request("POST", path, json=body or {}, timeout=timeout).json()

    # ── API methods ───────────────────────────────────────────

    def healthz(self) -> dict:
        """Liveness probe. GET /healthz

        Returns:
            {"status": "ok", "version": "..."}
        """
        return self._get("/healthz")

    def is_running(self) -> bool:
        """Return True if the station is reachable."""
        try:
            self.healthz()
            return True
        except Exception:
            return False

    def render(
        self,
        url: str,
        durations: dict[str, list[int]],
        out_dir: Path,
        *,
        fps: int = 30,
        viewport: tuple[int, int] = (1920, 1080),
        chapter: int | None = None,
        frame_offset: int | None = None,
        format: str = "png",
        timeout: float = 600,
    ) -> RenderResult:
        """Render a URL to frames using CDP virtual time.

        POST /render

        Args:
            url:          Web app URL (must expose ``window.__renderState``).
            durations:    Map of chapter_id → list[step_duration_ms].
            out_dir:      Directory where frames will be written.
            fps:          Frames per second (default 30).
            viewport:     (width, height) in pixels (default 1920×1080).
            chapter:      Optional chapter index (0-based) to render only that chapter.
            frame_offset: Starting frame number for output filenames.
            format:       Image format: "png" or "jpeg".
            timeout:      Per-request timeout in seconds (default 600).

        Returns:
            RenderResult with frames_dir, manifest_path, total_frames.
        """
        body: dict[str, Any] = {
            "url": url,
            "durations": durations,
            "out_dir": str(out_dir),
            "fps": fps,
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "format": format,
        }
        if chapter is not None:
            body["chapter"] = chapter
        if frame_offset is not None:
            body["frame_offset"] = frame_offset

        data = self._post("/render", body, timeout=timeout)
        return RenderResult(data)

    def pipeline(
        self,
        project_root: Path,
        dev_url: str,
        out_dir: Path,
        *,
        fps: int = 30,
        parallel: int = 1,
        viewport: tuple[int, int] = (1920, 1080),
        crf: int | None = None,
        preset: str | None = None,
        sub_font: str | None = None,
        loudnorm: bool = True,
        timeout: float = 3600,
    ) -> PipelineResult:
        """Run the full offline render pipeline.

        POST /pipeline

        Internally the station runs:
          1. probe-durations (read chapters.ts + audio)
          2. render (CDP virtual time, per chapter)
          3. build-subtitles (srt + vtt)
          4. compose-final (frames + audio → mp4)

        Args:
            project_root: Path to the presentation project directory.
            dev_url:      Vite dev server URL (e.g. "http://localhost:5174").
            out_dir:      Output directory for mp4, srt, vtt, frames.
            fps:          Frames per second (default 30).
            parallel:     Number of chapters to render in parallel (default 1).
            viewport:     (width, height) in pixels.
            crf:          ffmpeg CRF quality (lower = better; default station decides).
            preset:       ffmpeg preset (e.g. "slow", "medium").
            sub_font:     Subtitle font name.
            loudnorm:     Apply EBU R128 loudness normalization (default True).
            timeout:      Per-request timeout in seconds (default 3600 for long jobs).

        Returns:
            PipelineResult with mp4_path, srt_path, vtt_path, total_frames, wall_clock_seconds.
        """
        body: dict[str, Any] = {
            "project_root": str(project_root),
            "dev_url": dev_url,
            "out_dir": str(out_dir),
            "fps": fps,
            "parallel": parallel,
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "loudnorm": loudnorm,
        }
        if crf is not None:
            body["crf"] = crf
        if preset is not None:
            body["preset"] = preset
        if sub_font is not None:
            body["sub_font"] = sub_font

        data = self._post("/pipeline", body, timeout=timeout)
        return PipelineResult(data)

    def probe_durations(
        self,
        project_root: Path,
        *,
        timeout: float = 60,
    ) -> ProbeDurationsResult:
        """Probe chapter durations from a project.

        POST /probe-durations

        Reads ``src/registry/chapters.ts`` and audio files inside project_root
        to determine per-step durations.

        Args:
            project_root: Path to the presentation project directory.
            timeout:      Per-request timeout in seconds.

        Returns:
            ProbeDurationsResult with durations dict and written_to path.
        """
        data = self._post(
            "/probe-durations",
            {"project_root": str(project_root)},
            timeout=timeout,
        )
        return ProbeDurationsResult(data)

    def build_subtitles(
        self,
        project_root: Path,
        durations: dict[str, list[int]],
        out_dir: Path,
        *,
        timeout: float = 60,
    ) -> SubtitlesResult:
        """Build .srt and .vtt subtitle files.

        POST /build-subtitles

        Args:
            project_root: Path to the presentation project (for narrations).
            durations:    Map of chapter_id → list[step_duration_ms].
            out_dir:      Directory where srt/vtt will be written.
            timeout:      Per-request timeout in seconds.

        Returns:
            SubtitlesResult with srt_path, vtt_path, total_ms.
        """
        body: dict[str, Any] = {
            "project_root": str(project_root),
            "durations": durations,
            "out_dir": str(out_dir),
        }
        data = self._post("/build-subtitles", body, timeout=timeout)
        return SubtitlesResult(data)

    def compose_final(
        self,
        frames_dir: Path,
        audio_dir: Path,
        out_dir: Path,
        *,
        crf: int | None = None,
        preset: str | None = None,
        sub_font: str | None = None,
        loudnorm: bool = True,
        timeout: float = 600,
    ) -> ComposeFinalResult:
        """Compose frames + audio into mp4.

        POST /compose-final

        Args:
            frames_dir: Directory containing frame images.
            audio_dir:  Directory containing per-step mp3 audio files.
            out_dir:    Output directory for mp4.
            crf:        ffmpeg CRF quality value.
            preset:     ffmpeg encoding preset.
            sub_font:   Subtitle font name for burn-in variant.
            loudnorm:   Apply EBU R128 loudness normalization.
            timeout:    Per-request timeout in seconds.

        Returns:
            ComposeFinalResult with mp4_path and optional mp4_burnin_path.
        """
        body: dict[str, Any] = {
            "frames_dir": str(frames_dir),
            "audio_dir": str(audio_dir),
            "out_dir": str(out_dir),
            "loudnorm": loudnorm,
        }
        if crf is not None:
            body["crf"] = crf
        if preset is not None:
            body["preset"] = preset
        if sub_font is not None:
            body["sub_font"] = sub_font

        data = self._post("/compose-final", body, timeout=timeout)
        return ComposeFinalResult(data)

    # ── Context manager ───────────────────────────────────────

    def __enter__(self) -> BrowserRenderClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"BrowserRenderClient(base_url={self.base_url!r})"
