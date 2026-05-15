#!/Users/joneshong/.local/bin/python3
"""Browser-Render MCP Server — SDK adapter for Claude Code integration.

6 tools:
  - render_pipeline     : End-to-end: build subtitles → render URL frames → compose final video
  - render_url_to_frames: Render a URL over time segments → PNG frame sequence
  - probe_durations     : Extract chapter/slide durations from a Remotion project manifest
  - build_subtitles     : Generate SRT/VTT subtitle files from project transcript data
  - compose_final       : Combine frame sequence + audio tracks → final MP4
  - healthz             : Check station liveness + headless browser status

All logic lives in sdk_client.browser_render (SDK layer, written by Agent C).
This server uses the "expected signature" pattern — if the SDK module is not yet
available, the tools return a clear ImportError message rather than crashing the MCP server.

Expected SDK contracts (Agent C will implement):
  BrowserRenderClient.pipeline(project_root, dev_url, out_dir, fps?, ...)
    -> PipelineResult { mp4_path, srt_path, vtt_path, total_frames, wall_clock_seconds }

  BrowserRenderClient.render(url, durations, out_dir, fps?, chapter?)
    -> RenderResult { mp4_path?, frames_dir, manifest_path }

  BrowserRenderClient.probe(project_root)
    -> dict { chapters: [{name, duration_ms}], total_ms, slide_count }

  BrowserRenderClient.build_subtitles(project_root, out_dir)
    -> dict { srt_path, vtt_path, cue_count }

  BrowserRenderClient.compose(frames_dir, audio_dir, out_dir)
    -> dict { mp4_path, duration_seconds, frame_count }

  BrowserRenderClient.healthz()
    -> dict { "status": "ok"|"error", "browser_alive": bool, "station_url": str }

Usage:
    /Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/mcp/browser-render/server.py

Configure in ~/.mcpproxy/mcp_config.json via mcp-lazy-wrapper (see README).
"""

import asyncio

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# SDK import — graceful degradation if Agent C has not landed yet
# ---------------------------------------------------------------------------

try:
    from sdk_client.browser_render import BrowserRenderClient

    _SDK_AVAILABLE = True
    _SDK_ERROR = ""
except ImportError as _e:
    _SDK_AVAILABLE = False
    _SDK_ERROR = str(_e)
    # TODO(Agent C): implement sdk_client/browser_render.py
    # Expected class: BrowserRenderClient with methods:
    #   pipeline(), render(), probe(), build_subtitles(), compose(), healthz()


mcp = FastMCP("browser-render")


def _client():
    """Create a BrowserRenderClient instance."""
    return BrowserRenderClient()


def _sdk_unavailable_msg(tool_name: str) -> str:
    return (
        f"## Error: SDK Not Available\n\n"
        f"Tool `{tool_name}` requires `sdk_client.browser_render` (Agent C deliverable).\n\n"
        f"**ImportError**: {_SDK_ERROR}\n\n"
        "Once `sdk_client/browser_render.py` is in place, re-invoke this tool."
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_pipeline_result(result: dict) -> str:
    """Format PipelineResult as a markdown report."""
    parts = [
        "## Browser-Render Pipeline Complete",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| MP4 | `{result.get('mp4_path', '-')}` |",
        f"| SRT | `{result.get('srt_path', '-')}` |",
        f"| VTT | `{result.get('vtt_path', '-')}` |",
        f"| Total Frames | {result.get('total_frames', '-')} |",
        f"| Wall Clock | {result.get('wall_clock_seconds', '-'):.1f}s |"
        if isinstance(result.get("wall_clock_seconds"), (int, float))
        else f"| Wall Clock | {result.get('wall_clock_seconds', '-')} |",
    ]
    if result.get("errors"):
        parts += ["", "### Warnings / Errors"]
        for e in result["errors"]:
            parts.append(f"- {e}")
    return "\n".join(parts)


def _format_render_result(result: dict) -> str:
    """Format RenderResult (URL→frames) as markdown."""
    parts = [
        "## Render URL → Frames",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Frames Dir | `{result.get('frames_dir', '-')}` |",
        f"| Manifest | `{result.get('manifest_path', '-')}` |",
        f"| MP4 (if composed) | `{result.get('mp4_path') or 'not yet composed'}` |",
    ]
    frame_count = result.get("frame_count")
    if frame_count is not None:
        parts.append(f"| Frame Count | {frame_count} |")
    chapters = result.get("chapters", [])
    if chapters:
        parts += [
            "",
            "### Chapters Rendered",
            "| Chapter | Duration (ms) | Frame Range |",
            "|---------|--------------|-------------|",
        ]
        for ch in chapters:
            parts.append(
                f"| {ch.get('name', '?')} | {ch.get('duration_ms', '?')} | "
                f"{ch.get('frame_start', '?')}–{ch.get('frame_end', '?')} |"
            )
    return "\n".join(parts)


def _format_probe_result(result: dict) -> str:
    """Format probe_durations result as markdown."""
    parts = [
        "## Project Duration Probe",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Slide Count | {result.get('slide_count', '-')} |",
        f"| Total Duration | {result.get('total_ms', 0) / 1000:.1f}s ({result.get('total_ms', 0)} ms) |",
    ]
    chapters = result.get("chapters", [])
    if chapters:
        parts += [
            "",
            "### Chapters",
            "| # | Name | Duration (ms) |",
            "|---|------|--------------|",
        ]
        for i, ch in enumerate(chapters, 1):
            parts.append(f"| {i} | {ch.get('name', '?')} | {ch.get('duration_ms', '?')} |")
    return "\n".join(parts)


def _format_subtitles_result(result: dict) -> str:
    """Format build_subtitles result as markdown."""
    parts = [
        "## Subtitle Build Complete",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| SRT | `{result.get('srt_path', '-')}` |",
        f"| VTT | `{result.get('vtt_path', '-')}` |",
        f"| Cue Count | {result.get('cue_count', '-')} |",
    ]
    warnings = result.get("warnings", [])
    if warnings:
        parts += ["", "### Warnings"]
        for w in warnings:
            parts.append(f"- {w}")
    return "\n".join(parts)


def _format_compose_result(result: dict) -> str:
    """Format compose_final result as markdown."""
    parts = [
        "## Compose Final Video Complete",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| MP4 | `{result.get('mp4_path', '-')}` |",
        f"| Duration | {result.get('duration_seconds', '-')}s |",
        f"| Frame Count | {result.get('frame_count', '-')} |",
    ]
    if result.get("ffmpeg_cmd"):
        parts += ["", "```", result["ffmpeg_cmd"], "```"]
    return "\n".join(parts)


def _format_healthz(result: dict) -> str:
    """Format health check as markdown."""
    status = result.get("status", "unknown")
    browser_alive = result.get("browser_alive", False)
    icon_status = "OK" if status == "ok" else "ERROR"
    icon_browser = "alive" if browser_alive else "DEAD"
    parts = [
        f"## Browser-Render Station Health: {icon_status}",
        "",
        "| Component | Status |",
        "|-----------|--------|",
        f"| Station | {status} |",
        f"| Headless Browser | {icon_browser} |",
        f"| Station URL | {result.get('station_url', '-')} |",
    ]
    if result.get("version"):
        parts.append(f"| Version | {result['version']} |")
    if result.get("error"):
        parts += ["", f"**Error**: {result['error']}"]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def render_pipeline(
    project_root: str,
    dev_url: str,
    out_dir: str,
    fps: int = 30,
) -> str:
    """Run the full browser-render pipeline for a Remotion/web presentation project.

    Typical use case: After editing slides in a Remotion project, call this once
    to generate the final MP4 + SRT/VTT subtitle files. Internally it:
      1. Probes chapter durations from the project manifest
      2. Builds subtitle files (SRT + VTT)
      3. Renders URL → PNG frame sequence at the given fps
      4. Composes frames + audio → final MP4

    Args:
        project_root: Absolute path to the Remotion project directory
                      (must contain package.json + src/Root.tsx or equivalent)
        dev_url:      URL of the running dev server (e.g. http://localhost:3000)
        out_dir:      Absolute path where output files will be written
        fps:          Frames per second for rendering (default: 30)

    Returns:
        Markdown report with paths to mp4_path, srt_path, vtt_path, total_frames,
        and wall_clock_seconds.
    """
    if not _SDK_AVAILABLE:
        return _sdk_unavailable_msg("render_pipeline")

    def _run():
        with _client() as c:
            return c.pipeline(project_root, dev_url, out_dir, fps=fps)

    try:
        result = await asyncio.to_thread(_run)
        return _format_pipeline_result(result)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def render_url_to_frames(
    url: str,
    durations: str,
    out_dir: str,
    fps: int = 30,
    chapter: str = "",
) -> str:
    """Render a web URL over time segments, producing a PNG frame sequence.

    Typical use case: Capture a specific chapter/slide of a presentation at
    a controlled frame rate. The station controls a headless browser, navigates
    to `url`, seeks through each duration segment, and screenshots each frame.

    Args:
        url:       Full URL to render (e.g. http://localhost:3000/?chapter=intro)
        durations: Comma-separated list of duration segments in milliseconds
                   (e.g. "2000,3500,1800" for three segments)
        out_dir:   Absolute path for output PNG frames and manifest.json
        fps:       Frames per second (default: 30; higher = more frames, slower)
        chapter:   Optional chapter name tag for the manifest (default: empty)

    Returns:
        Markdown report with frames_dir, manifest_path, frame count, and per-chapter info.
    """
    if not _SDK_AVAILABLE:
        return _sdk_unavailable_msg("render_url_to_frames")

    def _run():
        duration_list = [int(d.strip()) for d in durations.split(",") if d.strip()]
        with _client() as c:
            return c.render(url, duration_list, out_dir, fps=fps, chapter=chapter or None)

    try:
        result = await asyncio.to_thread(_run)
        return _format_render_result(result)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def probe_durations(project_root: str) -> str:
    """Extract chapter/slide duration data from a Remotion project manifest.

    Typical use case: Before rendering, call this to discover how many chapters
    the project has and their durations (in ms), so you can plan fps and out_dir.

    Args:
        project_root: Absolute path to the Remotion project directory

    Returns:
        Markdown table with slide_count, total_ms, and per-chapter durations.
    """
    if not _SDK_AVAILABLE:
        return _sdk_unavailable_msg("probe_durations")

    def _run():
        with _client() as c:
            return c.probe(project_root)

    try:
        result = await asyncio.to_thread(_run)
        return _format_probe_result(result)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def build_subtitles(project_root: str, out_dir: str) -> str:
    """Generate SRT and VTT subtitle files from project transcript data.

    Typical use case: After probing durations, call this before rendering
    so subtitle timing is locked to the same chapter durations used in the video.

    Args:
        project_root: Absolute path to the Remotion project directory
                      (must contain transcript data in src/content/ or equivalent)
        out_dir:      Absolute path where SRT and VTT files will be written

    Returns:
        Markdown report with srt_path, vtt_path, and cue_count.
    """
    if not _SDK_AVAILABLE:
        return _sdk_unavailable_msg("build_subtitles")

    def _run():
        with _client() as c:
            return c.build_subtitles(project_root, out_dir)

    try:
        result = await asyncio.to_thread(_run)
        return _format_subtitles_result(result)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def compose_final(frames_dir: str, audio_dir: str, out_dir: str) -> str:
    """Combine a PNG frame sequence with audio tracks to produce the final MP4.

    Typical use case: After `render_url_to_frames` and `build_subtitles`, call this
    to merge the frames with narration/background audio. Uses FFmpeg under the hood.

    Args:
        frames_dir: Absolute path to directory containing PNG frames
                    (must include manifest.json for timing metadata)
        audio_dir:  Absolute path to directory containing audio tracks
                    (narration.mp3 / bg.mp3 or as described by manifest.json)
        out_dir:    Absolute path where final.mp4 will be written

    Returns:
        Markdown report with mp4_path, duration_seconds, and frame_count.
    """
    if not _SDK_AVAILABLE:
        return _sdk_unavailable_msg("compose_final")

    def _run():
        with _client() as c:
            return c.compose(frames_dir, audio_dir, out_dir)

    try:
        result = await asyncio.to_thread(_run)
        return _format_compose_result(result)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def healthz() -> str:
    """Check browser-render station liveness and headless browser status.

    Typical use case: Before starting a long render job, verify the station
    is up and the headless browser (Playwright/Chromium) is ready.

    Returns:
        Markdown report with station status, browser_alive flag, and station URL.
    """
    if not _SDK_AVAILABLE:
        return _sdk_unavailable_msg("healthz")

    def _run():
        with _client() as c:
            return c.healthz()

    try:
        result = await asyncio.to_thread(_run)
        return _format_healthz(result)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
