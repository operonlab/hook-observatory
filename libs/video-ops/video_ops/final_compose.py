"""Final compose operator — mux frame sequence + audio + subtitles into mp4.

Wraps ffmpeg to produce a web-ready H.264 / AAC mp4 with optional
soft-subtitle (mov_text) or burn-in (libass) subtitle streams.

Usage:
    from video_ops.final_compose import compose_final, ComposeResult

    result = compose_final(
        frames_dir=Path("/tmp/frames"),
        audio_path=Path("/tmp/audio.m4a"),
        out_dir=Path("/tmp/out"),
        fps=30,
        format="png",
        pad_width=6,          # zero-pad width for frame filenames
        subtitles_srt=Path("/tmp/out/subtitles.srt"),
        crf=18,
        preset="slow",
    )
    print(result.mp4_path)         # /tmp/out/output.mp4
    print(result.has_subtitle_stream)  # True

Invariants (from CONTRACTS.md §4):
    INV-1  video codec = h264, pix_fmt = yuv420p
    INV-2  audio codec = aac
    INV-3  video fps matches ``fps`` argument
    INV-4  video duration ≈ totalFrames / fps (±300 ms)
    INV-5  if subtitles_srt provided → mp4 has mov_text subtitle stream
    INV-6  mp4 has faststart (moov atom near start)
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Custom exceptions ──────────────────────────────────────────────────────


class SkippableError(RuntimeError):
    """Raised for non-fatal failures that the caller may choose to ignore."""


# ── Dataclass ─────────────────────────────────────────────────────────────


@dataclass
class ComposeResult:
    """Result of :func:`compose_final`."""

    mp4_path: Path
    """Path to the output mp4 (soft-subtitle version)."""

    duration_seconds: float
    """Measured video duration in seconds (from ffprobe)."""

    codec_video: str
    """Video codec used (always ``'h264'``)."""

    codec_audio: str
    """Audio codec used (always ``'aac'``)."""

    has_subtitle_stream: bool
    """True when a mov_text subtitle stream was muxed in."""

    burnin_path: Path | None = None
    """Path to the burn-in mp4, or None when burn-in was skipped."""


# ── ffmpeg helpers ─────────────────────────────────────────────────────────


def _ffmpeg(*args: str, timeout: int = 600) -> None:
    """Run ffmpeg, raising RuntimeError on non-zero exit."""
    cmd = ["ffmpeg", "-y", *args]
    logger.debug("ffmpeg: %s", " ".join(cmd[:12]) + (" ..." if len(cmd) > 12 else ""))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        stderr_tail = exc.stderr[-800:] if exc.stderr else "(no stderr)"
        raise RuntimeError(f"ffmpeg failed: {stderr_tail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"ffmpeg timed out after {timeout}s") from exc
    return result


def _ffprobe_duration(path: Path) -> float:
    """Return video stream duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
    raw = result.stdout.strip()
    if not raw:
        # Fallback: try format-level duration
        cmd2 = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, check=True, timeout=30)
        raw = result2.stdout.strip()
    return float(raw)


def _has_subtitles_filter() -> bool:
    """Return True when the installed ffmpeg has libass (subtitles filter)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "subtitles" in result.stdout
    except Exception:
        return False


def _escape_srt_path(path: Path) -> str:
    """Escape SRT path for use inside ffmpeg filter_graph string."""
    s = str(path)
    # Escape backslashes first, then colons (ffmpeg filter syntax)
    s = s.replace("\\", "\\\\")
    s = s.replace(":", "\\:")
    return s


# ── Core public API ────────────────────────────────────────────────────────


def compose_final(
    frames_dir: Path,
    audio_path: Path,
    out_dir: Path,
    *,
    fps: int = 30,
    format: str = "png",
    pad_width: int,
    subtitles_srt: Path | None = None,
    crf: int = 18,
    preset: str = "slow",
    burnin: bool = False,
    sub_font: str = "PingFang TC",
) -> ComposeResult:
    """Mux a frame sequence + audio track + optional subtitles into an mp4.

    Parameters
    ----------
    frames_dir:
        Directory containing the rendered frame image sequence.
    audio_path:
        Path to the pre-built audio track (m4a or any ffmpeg-readable format).
    out_dir:
        Destination directory.  Created if it does not exist.
    fps:
        Frame rate of the source sequence (must match how frames were rendered).
    format:
        Image format of the frames (``'png'`` or ``'jpeg'`` / ``'jpg'``).
    pad_width:
        Zero-padding width used in frame filenames, e.g. 6 means
        ``000001.png``.  Callers typically read this from the manifest.json.
    subtitles_srt:
        Optional path to an ``.srt`` file.  When provided the soft-subtitle
        mp4 gains a ``mov_text`` stream.
    crf:
        H.264 CRF quality (0=lossless, 51=worst; default 18).
    preset:
        ffmpeg encoding preset (default ``'slow'`` for better compression).
    burnin:
        When True, also produce ``output-burnin.mp4`` with libass hard-coded
        subtitles.  If ffmpeg lacks libass, raises :exc:`SkippableError`.
    sub_font:
        Font name for burn-in subtitles (default ``'PingFang TC'``).

    Returns
    -------
    ComposeResult

    Raises
    ------
    FileNotFoundError
        When ``frames_dir`` or ``audio_path`` do not exist.
    SkippableError
        When ``burnin=True`` but ffmpeg has no libass support.
    RuntimeError
        On ffmpeg encoding failure.
    """
    frames_dir = frames_dir.resolve()
    audio_path = audio_path.resolve()
    out_dir = out_dir.resolve()

    if not frames_dir.exists():
        raise FileNotFoundError(f"frames_dir not found: {frames_dir}")
    if not audio_path.exists():
        raise FileNotFoundError(f"audio_path not found: {audio_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    # Normalise frame extension (ffmpeg expects 'jpg' not 'jpeg')
    ext = "jpg" if format in ("jpeg", "jpg") else "png"
    frame_glob = str(frames_dir / f"%0{pad_width}d.{ext}")

    out_mp4 = out_dir / "output.mp4"
    has_subs = subtitles_srt is not None and subtitles_srt.exists()

    # ── Soft-subtitle mp4 ─────────────────────────────────────────────────
    soft_args: list[str] = [
        "-framerate",
        str(fps),
        "-i",
        frame_glob,
        "-i",
        str(audio_path),
    ]
    if has_subs:
        soft_args += ["-i", str(subtitles_srt)]

    soft_args += [
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
    ]
    if has_subs:
        soft_args += ["-c:s", "mov_text"]

    soft_args += ["-movflags", "+faststart", "-shortest", str(out_mp4)]

    logger.info("compose_final: encoding %s → %s", frame_glob, out_mp4)
    _ffmpeg(*soft_args)

    duration_s = _ffprobe_duration(out_mp4)
    logger.info("compose_final: done — duration=%.2fs, subs=%s", duration_s, has_subs)

    # ── Burn-in mp4 (optional) ────────────────────────────────────────────
    burnin_path: Path | None = None
    if burnin:
        if not has_subs:
            logger.warning("burnin=True but no subtitles_srt provided — skipping")
        elif not _has_subtitles_filter():
            raise SkippableError(
                "ffmpeg lacks libass (subtitles filter) — reinstall ffmpeg with "
                "libass support, or use the soft-subtitle output.mp4 instead."
            )
        else:
            out_burnin = out_dir / "output-burnin.mp4"
            esc_srt = _escape_srt_path(subtitles_srt)
            style_str = (
                f"FontName={sub_font},FontSize=24,"
                "PrimaryColour=&Hffffff&,OutlineColour=&H000000&,"
                "BorderStyle=1,Outline=2"
            )
            vf = f"subtitles={esc_srt}:force_style='{style_str}'"

            burnin_args: list[str] = [
                "-framerate",
                str(fps),
                "-i",
                frame_glob,
                "-i",
                str(audio_path),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                str(crf),
                "-preset",
                preset,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-shortest",
                str(out_burnin),
            ]
            logger.info("compose_final: burn-in → %s", out_burnin)
            _ffmpeg(*burnin_args)
            burnin_path = out_burnin

    return ComposeResult(
        mp4_path=out_mp4,
        duration_seconds=duration_s,
        codec_video="h264",
        codec_audio="aac",
        has_subtitle_stream=has_subs,
        burnin_path=burnin_path,
    )
