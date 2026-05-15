"""browser-render CLI — Click subcommand group for browser-render station.

Usage (via workshop CLI):
    workshop browser-render render  --url URL --out DIR [--fps N] [--chapter N] [--format png|jpeg]
    workshop browser-render pipeline --project DIR --dev-url URL --out DIR [--fps N] [--parallel N]
    workshop browser-render probe-durations --project DIR
    workshop browser-render build-subtitles --project DIR --out DIR
    workshop browser-render compose-final --frames DIR --audio-dir DIR --out DIR
    workshop browser-render healthz

All commands accept --json to emit machine-readable JSON instead of
human-readable summaries.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from sdk_client._base import APIError
from sdk_client.browser_render import BrowserRenderClient
from sdk_client.cli_utils import error_exit, json_out

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_client(url: str | None, timeout: float) -> BrowserRenderClient:
    return BrowserRenderClient(base_url=url, timeout=timeout)


def _durations_from_json(durations_str: str | None) -> dict[str, list[int]]:
    """Parse --durations JSON string into dict."""
    if not durations_str:
        return {}
    try:
        parsed = json.loads(durations_str)
        if not isinstance(parsed, dict):
            error_exit("--durations must be a JSON object, e.g. '{\"ch1\": [1000, 2000]}'")
        return parsed
    except json.JSONDecodeError as e:
        error_exit(f"Invalid --durations JSON: {e}")
    return {}  # unreachable


# ── Command group ─────────────────────────────────────────────────────────────


@click.group("browser-render")
@click.option(
    "--url",
    "station_url",
    envvar="BROWSER_RENDER_URL",
    default=None,
    help="Override station URL (default: auto from port_registry or env).",
)
@click.option("--timeout", default=60.0, show_default=True, help="Base HTTP timeout (seconds).")
@click.pass_context
def browser_render_group(ctx: click.Context, station_url: str | None, timeout: float) -> None:
    """Offline browser-render station — URL-to-mp4 via CDP virtual time."""
    ctx.ensure_object(dict)
    ctx.obj["station_url"] = station_url
    ctx.obj["timeout"] = timeout


# ── healthz ───────────────────────────────────────────────────────────────────


@browser_render_group.command("healthz")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cmd_healthz(ctx: click.Context, as_json: bool) -> None:
    """Check station liveness."""
    client = _make_client(ctx.obj["station_url"], ctx.obj["timeout"])
    try:
        result = client.healthz()
    except APIError as e:
        error_exit(str(e))
    finally:
        client.close()

    if as_json:
        json_out(result)
    else:
        status = result.get("status", "unknown")
        version = result.get("version", "?")
        click.echo(f"browser-render  status={status}  version={version}")


# ── render ────────────────────────────────────────────────────────────────────


@browser_render_group.command("render")
@click.option("--url", "web_url", required=True, help="Web app URL to render.")
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(),
    help="Output directory for frames.",
)
@click.option(
    "--durations",
    default=None,
    help="JSON: chapter_id→step_durations_ms, e.g. '{\"ch1\":[1000,2000]}'",
)
@click.option("--fps", default=30, show_default=True, help="Frames per second.")
@click.option(
    "--viewport",
    default="1920x1080",
    show_default=True,
    help="Viewport WxH, e.g. 1920x1080.",
)
@click.option("--chapter", default=None, type=int, help="Render only this chapter (0-based).")
@click.option("--frame-offset", default=None, type=int, help="Starting frame number.")
@click.option(
    "--format",
    "img_format",
    default="png",
    type=click.Choice(["png", "jpeg"]),
    show_default=True,
    help="Output image format.",
)
@click.option("--render-timeout", default=600.0, show_default=True, help="Render timeout (s).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cmd_render(
    ctx: click.Context,
    web_url: str,
    out_dir: str,
    durations: str | None,
    fps: int,
    viewport: str,
    chapter: int | None,
    frame_offset: int | None,
    img_format: str,
    render_timeout: float,
    as_json: bool,
) -> None:
    """Render a URL to frames using CDP virtual time.

    The target web app must expose window.__renderState and accept ?render=1.
    """
    # Parse viewport
    try:
        w_str, h_str = viewport.split("x", 1)
        vp = (int(w_str), int(h_str))
    except ValueError:
        error_exit(f"Invalid --viewport '{viewport}'. Use WxH format, e.g. 1920x1080.")
        return  # unreachable

    dur_dict = _durations_from_json(durations)

    client = _make_client(ctx.obj["station_url"], ctx.obj["timeout"])
    try:
        result = client.render(
            url=web_url,
            durations=dur_dict,
            out_dir=Path(out_dir),
            fps=fps,
            viewport=vp,
            chapter=chapter,
            frame_offset=frame_offset,
            format=img_format,
            timeout=render_timeout,
        )
    except APIError as e:
        error_exit(str(e))
    finally:
        client.close()

    if as_json:
        json_out(result.raw)
    else:
        click.echo(f"frames_dir    : {result.frames_dir}")
        click.echo(f"manifest_path : {result.manifest_path}")
        click.echo(f"total_frames  : {result.total_frames}")


# ── pipeline ──────────────────────────────────────────────────────────────────


@browser_render_group.command("pipeline")
@click.option(
    "--project",
    "project_root",
    required=True,
    type=click.Path(exists=True),
    help="Presentation project root directory.",
)
@click.option("--dev-url", required=True, help="Vite dev server URL, e.g. http://localhost:5174.")
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(),
    help="Output directory for mp4, srt, vtt, frames.",
)
@click.option("--fps", default=30, show_default=True, help="Frames per second.")
@click.option("--parallel", default=1, show_default=True, help="Chapters to render in parallel.")
@click.option(
    "--viewport",
    default="1920x1080",
    show_default=True,
    help="Viewport WxH.",
)
@click.option("--crf", default=None, type=int, help="ffmpeg CRF quality (lower=better).")
@click.option("--preset", default=None, help="ffmpeg preset (slow/medium/fast).")
@click.option("--sub-font", default=None, help="Subtitle font name for burn-in.")
@click.option(
    "--no-loudnorm",
    is_flag=True,
    default=False,
    help="Disable EBU R128 loudness normalization.",
)
@click.option("--pipeline-timeout", default=3600.0, show_default=True, help="Pipeline timeout (s).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cmd_pipeline(
    ctx: click.Context,
    project_root: str,
    dev_url: str,
    out_dir: str,
    fps: int,
    parallel: int,
    viewport: str,
    crf: int | None,
    preset: str | None,
    sub_font: str | None,
    no_loudnorm: bool,
    pipeline_timeout: float,
    as_json: bool,
) -> None:
    """Run the full offline render pipeline (probe → render → subtitles → compose).

    Example:
        workshop browser-render pipeline \\
            --project ./presentation \\
            --dev-url http://localhost:5174 \\
            --out ./dist-video

    The target web app must expose window.__renderState and accept ?render=1.
    """
    try:
        w_str, h_str = viewport.split("x", 1)
        vp = (int(w_str), int(h_str))
    except ValueError:
        error_exit(f"Invalid --viewport '{viewport}'. Use WxH format, e.g. 1920x1080.")
        return

    client = _make_client(ctx.obj["station_url"], ctx.obj["timeout"])
    try:
        result = client.pipeline(
            project_root=Path(project_root),
            dev_url=dev_url,
            out_dir=Path(out_dir),
            fps=fps,
            parallel=parallel,
            viewport=vp,
            crf=crf,
            preset=preset,
            sub_font=sub_font,
            loudnorm=not no_loudnorm,
            timeout=pipeline_timeout,
        )
    except APIError as e:
        error_exit(str(e))
    finally:
        client.close()

    if as_json:
        json_out(result.raw)
    else:
        click.echo(f"mp4_path          : {result.mp4_path}")
        if result.mp4_burnin_path:
            click.echo(f"mp4_burnin_path   : {result.mp4_burnin_path}")
        click.echo(f"srt_path          : {result.srt_path}")
        click.echo(f"vtt_path          : {result.vtt_path}")
        click.echo(f"total_frames      : {result.total_frames}")
        click.echo(f"wall_clock_seconds: {result.wall_clock_seconds:.1f}s")


# ── probe-durations ───────────────────────────────────────────────────────────


@browser_render_group.command("probe-durations")
@click.option(
    "--project",
    "project_root",
    required=True,
    type=click.Path(exists=True),
    help="Presentation project root directory.",
)
@click.option("--probe-timeout", default=60.0, show_default=True, help="Probe timeout (s).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cmd_probe_durations(
    ctx: click.Context,
    project_root: str,
    probe_timeout: float,
    as_json: bool,
) -> None:
    """Probe chapter durations from a project (reads chapters.ts + audio)."""
    client = _make_client(ctx.obj["station_url"], ctx.obj["timeout"])
    try:
        result = client.probe_durations(Path(project_root), timeout=probe_timeout)
    except APIError as e:
        error_exit(str(e))
    finally:
        client.close()

    if as_json:
        json_out(result.raw)
    else:
        click.echo(f"written_to: {result.written_to}")
        click.echo("durations:")
        for ch_id, durs in result.durations.items():
            total_ms = sum(durs)
            click.echo(f"  {ch_id}: {len(durs)} steps, {total_ms}ms total")


# ── build-subtitles ───────────────────────────────────────────────────────────


@browser_render_group.command("build-subtitles")
@click.option(
    "--project",
    "project_root",
    required=True,
    type=click.Path(exists=True),
    help="Presentation project root (for narrations).",
)
@click.option(
    "--durations",
    required=True,
    help="JSON: chapter_id→step_durations_ms. Use probe-durations first.",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(),
    help="Output directory for .srt / .vtt.",
)
@click.option("--sub-timeout", default=60.0, show_default=True, help="Timeout (s).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cmd_build_subtitles(
    ctx: click.Context,
    project_root: str,
    durations: str,
    out_dir: str,
    sub_timeout: float,
    as_json: bool,
) -> None:
    """Build .srt and .vtt subtitle files from project narrations + durations."""
    dur_dict = _durations_from_json(durations)
    if not dur_dict:
        error_exit("--durations is required and must be non-empty JSON.")

    client = _make_client(ctx.obj["station_url"], ctx.obj["timeout"])
    try:
        result = client.build_subtitles(
            project_root=Path(project_root),
            durations=dur_dict,
            out_dir=Path(out_dir),
            timeout=sub_timeout,
        )
    except APIError as e:
        error_exit(str(e))
    finally:
        client.close()

    if as_json:
        json_out(result.raw)
    else:
        click.echo(f"srt_path : {result.srt_path}")
        click.echo(f"vtt_path : {result.vtt_path}")
        click.echo(f"total_ms : {result.total_ms}")


# ── compose-final ─────────────────────────────────────────────────────────────


@browser_render_group.command("compose-final")
@click.option(
    "--frames",
    "frames_dir",
    required=True,
    type=click.Path(exists=True),
    help="Directory containing rendered frame images.",
)
@click.option(
    "--audio-dir",
    required=True,
    type=click.Path(exists=True),
    help="Directory containing per-step mp3 audio files.",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(),
    help="Output directory for mp4.",
)
@click.option("--crf", default=None, type=int, help="ffmpeg CRF quality.")
@click.option("--preset", default=None, help="ffmpeg preset.")
@click.option("--sub-font", default=None, help="Subtitle font for burn-in variant.")
@click.option(
    "--no-loudnorm",
    is_flag=True,
    default=False,
    help="Disable EBU R128 loudness normalization.",
)
@click.option("--compose-timeout", default=600.0, show_default=True, help="Compose timeout (s).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cmd_compose_final(
    ctx: click.Context,
    frames_dir: str,
    audio_dir: str,
    out_dir: str,
    crf: int | None,
    preset: str | None,
    sub_font: str | None,
    no_loudnorm: bool,
    compose_timeout: float,
    as_json: bool,
) -> None:
    """Compose rendered frames + audio into mp4 via ffmpeg."""
    client = _make_client(ctx.obj["station_url"], ctx.obj["timeout"])
    try:
        result = client.compose_final(
            frames_dir=Path(frames_dir),
            audio_dir=Path(audio_dir),
            out_dir=Path(out_dir),
            crf=crf,
            preset=preset,
            sub_font=sub_font,
            loudnorm=not no_loudnorm,
            timeout=compose_timeout,
        )
    except APIError as e:
        error_exit(str(e))
    finally:
        client.close()

    if as_json:
        json_out(result.raw)
    else:
        click.echo(f"mp4_path       : {result.mp4_path}")
        if result.mp4_burnin_path:
            click.echo(f"mp4_burnin_path: {result.mp4_burnin_path}")
