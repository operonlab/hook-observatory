"""Parse video files (mp4/mov/webm/mkv/avi) into Markdown via STT + Vision QA on keyframes.

Pipeline:
1. ffmpeg extract audio → /tmp/{slug}.wav
2. async parallel:
   - transcribe(audio) → TranscriptResult
   - if with_keyframes: ffmpeg scene-change detection (max 20 frames)
     → vision_station.qa(frame, "describe this scene") → list[FrameDesc]
3. Interleave by timestamp → time-aligned Markdown

Output format:
    ## Video Transcript: <filename>
    - Duration: <s>s
    - Frames captured: <n>

    **[00:00] (frame)**: <vision describe>
    **[Speaker A] [00:05]**: <speech text>
    **[00:30] (frame)**: <vision describe>
    ...
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_ops.transcribe import transcribe
from sdk_client.vision import VisionClient

logger = logging.getLogger(__name__)

# Guard: skip files larger than 500 MB
_MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024

# ffmpeg scene-change detection params
_SCENE_THRESHOLD = 0.4
_MAX_FRAMES = 20
_FRAME_SCALE = "640:-1"

# Supported video extensions
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".ts", ".flv"}
)


@dataclass
class FrameDesc:
    timestamp: float  # seconds
    frame_path: str  # absolute path to extracted frame image
    description: str  # vision QA result


def _format_time(seconds: float) -> str:
    """Format seconds → MM:SS string."""
    s = int(seconds)
    m, sec = divmod(s, 60)
    return f"{m:02d}:{sec:02d}"


def _check_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg is not available."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Install via: brew install ffmpeg")


def _extract_audio(video_path: Path, tmp_dir: str) -> Path:
    """Extract audio track from video using ffmpeg.

    Returns path to extracted WAV file.
    Raises RuntimeError if ffmpeg exits non-zero.
    """
    out_path = Path(tmp_dir) / f"{video_path.stem}_audio.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",  # no video
        "-acodec",
        "pcm_s16le",  # WAV PCM
        "-ar",
        "16000",  # 16kHz for STT
        "-ac",
        "1",  # mono
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio extraction failed (exit {result.returncode}): {result.stderr[-500:]}"
        )
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg produced empty audio file: {out_path}")
    return out_path


def _extract_keyframes(video_path: Path, tmp_dir: str) -> list[tuple[float, str]]:
    """Extract keyframes via scene-change detection (max 20 frames).

    Returns list of (timestamp_seconds, frame_path) tuples.
    Raises RuntimeError if ffmpeg exits non-zero.
    """
    frames_dir = Path(tmp_dir) / "frames"
    frames_dir.mkdir(exist_ok=True)

    out_pattern = str(frames_dir / "frame_%04d.jpg")
    timestamps_file = str(frames_dir / "timestamps.txt")

    # Two-pass: extract frames + write timestamps
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"select='gt(scene,{_SCENE_THRESHOLD})',scale={_FRAME_SCALE}",
        "-frames:v",
        str(_MAX_FRAMES),
        "-fps_mode",
        "vfr",
        "-frame_pts",
        "1",
        out_pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg keyframe extraction failed (exit {result.returncode}): {result.stderr[-500:]}"
        )

    # Parse timestamps from stderr (ffmpeg -vf select prints pts_time)
    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_files:
        logger.warning("video_parser: no keyframes extracted (no scene changes detected?)")
        return []

    # Extract timestamps from ffmpeg stderr output
    timestamps: list[float] = []
    for line in result.stderr.splitlines():
        # ffmpeg prints: "pts_time:X.XXX"
        if "pts_time:" in line:
            try:
                ts_str = line.split("pts_time:")[1].split()[0].strip()
                timestamps.append(float(ts_str))
            except (IndexError, ValueError):
                pass

    # Pad or trim timestamps to match extracted frames
    pairs: list[tuple[float, str]] = []
    for i, frame_file in enumerate(frame_files[:_MAX_FRAMES]):
        ts = timestamps[i] if i < len(timestamps) else float(i)
        pairs.append((ts, str(frame_file)))

    return pairs


async def _describe_frames(
    frame_pairs: list[tuple[float, str]],
) -> list[FrameDesc]:
    """Send each frame to Vision station for description in parallel."""

    async def _describe_one(ts: float, frame_path: str) -> FrameDesc:
        def _call() -> str:
            client = VisionClient()
            try:
                resp = client.analyze(
                    file_path=frame_path,
                    task="describe",
                    engine="apple",
                )
                return resp.get("result", "")
            except Exception as exc:
                logger.warning("video_parser: vision QA failed for frame %.1fs: %s", ts, exc)
                return ""
            finally:
                client.close()

        desc = await asyncio.to_thread(_call)
        return FrameDesc(timestamp=ts, frame_path=frame_path, description=desc)

    tasks = [_describe_one(ts, fp) for ts, fp in frame_pairs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    frames: list[FrameDesc] = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("video_parser: frame description raised: %s", r)
        else:
            frames.append(r)
    return frames


def _interleave_markdown(
    frames: list[FrameDesc],
    segments: list[Any],  # TranscriptSegment
    filename: str,
    duration: float,
    language: str,
) -> str:
    """Interleave frame descriptions and speech segments by timestamp."""

    # Build unified event list: (timestamp, type, content)
    events: list[tuple[float, str, str]] = []

    for frame in frames:
        if frame.description:
            events.append((frame.timestamp, "frame", frame.description))

    for seg in segments:
        label = f"{seg.speaker} " if seg.speaker else ""
        events.append((seg.start, "speech", f"[{label.strip()}] {seg.text}" if label else seg.text))

    # Sort by timestamp
    events.sort(key=lambda x: x[0])

    lines: list[str] = []
    lines.append(f"## Video Transcript: {filename}")
    lines.append(f"- Duration: {duration:.1f}s")
    lines.append(f"- Language: {language}")
    lines.append(f"- Frames captured: {len(frames)}")
    lines.append("")

    for ts, etype, content in events:
        ts_str = _format_time(ts)
        if etype == "frame":
            lines.append(f"**[{ts_str}] (frame)**: {content}")
        else:
            # speech — content already includes speaker label
            lines.append(f"**[{ts_str}]** {content}")

    if not events:
        lines.append("*(no content extracted)*")

    return "\n".join(lines)


async def parse_video(
    file_path: str | Path,
    *,
    language: str | None = None,
    with_keyframes: bool = True,
    with_speaker: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Parse video file → (markdown_content, metadata).

    Args:
        file_path: Absolute path to video file.
        language: BCP-47 language hint for STT (None = auto-detect).
        with_keyframes: Extract keyframes and describe with Vision station.
        with_speaker: Enable speaker diarization in STT.

    Returns:
        Tuple of (markdown string, metadata dict).

    Raises:
        FileNotFoundError: File does not exist.
        ValueError: File is empty or exceeds 500 MB.
        RuntimeError: ffmpeg, STT, or Vision station failure.
    """

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Video file is empty (0 bytes): {file_path}")
    if file_size > _MAX_FILE_SIZE_BYTES:
        raise ValueError(f"Video file too large ({file_size / (1024**2):.0f} MB > 500 MB): {path}")

    _check_ffmpeg()

    logger.info(
        "video_parser: processing %s (%.1f MB), keyframes=%s",
        path.name,
        file_size / (1024**2),
        with_keyframes,
    )

    with tempfile.TemporaryDirectory(prefix="docvault_video_") as tmp_dir:
        # 1. Extract audio
        audio_path = _extract_audio(path, tmp_dir)

        # 2. Parallel: transcribe + keyframe extraction
        transcript_task = asyncio.create_task(
            transcribe(audio_path, language=language, with_speaker=with_speaker)
        )

        if with_keyframes:
            # Extract frames synchronously in thread (subprocess)
            frame_pairs = await asyncio.to_thread(_extract_keyframes, path, tmp_dir)
            # Describe frames via Vision station (async parallel)
            frames = await _describe_frames(frame_pairs)
        else:
            frames = []

        transcript = await transcript_task

        # 3. Build markdown
        content = _interleave_markdown(
            frames=frames,
            segments=transcript.segments,
            filename=path.name,
            duration=transcript.duration,
            language=transcript.language,
        )

    metadata: dict[str, Any] = {
        "source_type": "video",
        "title": path.stem,
        "file_path": str(path),
        "file_size": file_size,
        "duration": transcript.duration,
        "language": transcript.language,
        "segment_count": len(transcript.segments),
        "frame_count": len(frames),
        "has_keyframes": with_keyframes and len(frames) > 0,
        "has_speaker": with_speaker and any(s.speaker for s in transcript.segments),
    }

    logger.info(
        "video_parser: %s → %d chars, %d segs, %d frames",
        path.name,
        len(content),
        len(transcript.segments),
        len(frames),
    )

    return content, metadata
