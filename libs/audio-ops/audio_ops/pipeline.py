"""Audio pipeline operator — concat per-segment audio + loudnorm + AAC encode.

Builds a single audio track from a list of (mp3_path | None, duration_ms) segments.
Missing files are replaced with silence of the correct length.
Output is EBU R128 loudness-normalised and encoded as AAC (.m4a).

Usage:
    from audio_ops.pipeline import build_audio_track, AudioSegment
    from pathlib import Path

    track = build_audio_track(
        segments=[
            AudioSegment(file=Path("ch1/1.mp3"), duration_ms=6750),
            AudioSegment(file=None, duration_ms=1500),   # silence
            AudioSegment(file=Path("ch1/2.mp3"), duration_ms=10250),
        ],
        out_path=Path("/tmp/audio.m4a"),
        loudnorm=True,
    )
    print(track)   # /tmp/audio.m4a

Algorithm (mirrors compose-final.mjs concatAudio()):
    1. For each segment:
       - Source = mp3 file (if exists) or generated silence
       - Trim / pad to exactly duration_ms via ffmpeg ``apad`` + ``-t``
       - Write to staging WAV
    2. Concat all staging WAVs via ffmpeg concat demuxer
    3. Optional EBU R128 loudnorm (I=-16, LRA=11, TP=-1.5)
    4. Encode to AAC 192k, output .m4a
    5. Clean up staging files

Invariants:
    - Output file exists and is readable after return
    - AAC codec in output
    - Total duration ≈ sum(segment.duration_ms) ± 50 ms (ffmpeg AAC frame boundary)
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Dataclass ─────────────────────────────────────────────────────────────


@dataclass
class AudioSegment:
    """A single timed audio segment in the pipeline."""

    file: Path | None
    """Path to an mp3/wav/m4a file, or ``None`` for pure silence."""

    duration_ms: int
    """Exact target duration for this segment in milliseconds."""


# ── ffmpeg helpers ─────────────────────────────────────────────────────────


def _ffmpeg(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-y", *args]
    logger.debug("ffmpeg: %s", " ".join(cmd[:12]) + (" ..." if len(cmd) > 12 else ""))
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        tail = exc.stderr[-800:] if exc.stderr else "(no stderr)"
        raise RuntimeError(f"ffmpeg failed: {tail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"ffmpeg timed out after {timeout}s") from exc


def _generate_silence(out_path: Path, duration_s: float, sample_rate: int, channels: int) -> None:
    """Generate a silent WAV of exactly ``duration_s`` seconds."""
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl={'stereo' if channels == 2 else 'mono'}",
        "-t",
        f"{duration_s:.6f}",
        str(out_path),
    )


def _stage_segment(
    src: Path | None,
    duration_ms: int,
    staged: Path,
    sample_rate: int,
    channels: int,
    silence_wav: Path,
) -> None:
    """Trim/pad a single segment to exactly ``duration_ms`` and write as WAV.

    Uses ``apad=pad_dur=N`` so short files are extended with silence,
    and ``-t N`` so long files are truncated — identical to compose-final.mjs.
    """
    duration_s = duration_ms / 1000.0
    ac_str = str(channels)
    source_path = str(src) if (src is not None and src.exists()) else str(silence_wav)

    _ffmpeg(
        "-i",
        source_path,
        "-t",
        f"{duration_s:.6f}",
        "-ar",
        str(sample_rate),
        "-ac",
        ac_str,
        "-af",
        f"apad=pad_dur={duration_s:.6f}",
        str(staged),
    )


# ── Core public API ────────────────────────────────────────────────────────


def build_audio_track(
    segments: list[AudioSegment],
    out_path: Path,
    *,
    loudnorm: bool = True,
    sample_rate: int = 44100,
    channels: int = 2,
    bitrate: str = "192k",
) -> Path:
    """Build a single AAC audio track from per-segment files + silence.

    Parameters
    ----------
    segments:
        Ordered list of :class:`AudioSegment`.  ``file=None`` generates silence.
    out_path:
        Destination path for the output ``.m4a`` file.
        Parent directory is created if needed.
    loudnorm:
        When True, apply EBU R128 loudness normalisation
        (target I=-16 LUFS, LRA=11, TP=-1.5 dBTP) before AAC encoding.
    sample_rate:
        Output sample rate in Hz (default 44100).
    channels:
        Output channel count (1=mono, 2=stereo; default 2).
    bitrate:
        AAC bitrate string (default ``'192k'``).

    Returns
    -------
    Path
        Absolute path to the written ``.m4a`` file (same as ``out_path``).

    Raises
    ------
    ValueError
        When ``segments`` is empty.
    RuntimeError
        On ffmpeg failure.
    """
    if not segments:
        raise ValueError("segments must not be empty")

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_ms = sum(seg.duration_ms for seg in segments)
    total_s = total_ms / 1000.0

    # Use a temporary directory for staging files so cleanup is guaranteed
    with tempfile.TemporaryDirectory(prefix="audio-pipeline-") as tmp_dir:
        tmp = Path(tmp_dir)

        # 1. Generate a reference silence WAV (reused for all missing segments)
        silence_wav = tmp / "_silence.wav"
        _generate_silence(silence_wav, duration_s=1.0, sample_rate=sample_rate, channels=channels)

        # 2. Per-segment: trim/pad to exact duration → staging WAV
        staged_files: list[Path] = []
        concat_lines: list[str] = []

        for i, seg in enumerate(segments):
            staged = tmp / f"_seg-{str(i).zfill(4)}.wav"
            _stage_segment(
                src=seg.file,
                duration_ms=seg.duration_ms,
                staged=staged,
                sample_rate=sample_rate,
                channels=channels,
                silence_wav=silence_wav,
            )
            staged_files.append(staged)
            # ffmpeg concat list — escape single quotes in paths
            safe_path = str(staged).replace("'", "'\\''")
            concat_lines.append(f"file '{safe_path}'")

        # 3. Write concat list file
        concat_list = tmp / "_concat.txt"
        concat_list.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        # 4. Concat + optional loudnorm + AAC encode
        audio_filter = "loudnorm=I=-16:LRA=11:TP=-1.5" if loudnorm else None
        encode_args: list[str] = [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
        ]
        if audio_filter:
            encode_args += ["-af", audio_filter]
        # Force output sample_rate. Without -ar, loudnorm filter (or
        # ffmpeg's internal AAC encoder upsampling) can leave the output
        # at 96 kHz even when all staging WAVs are 44.1 kHz, violating
        # the docstring contract.
        encode_args += [
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-c:a",
            "aac",
            "-b:a",
            bitrate,
            "-t",
            f"{total_s:.6f}",
            str(out_path),
        ]

        logger.info(
            "build_audio_track: %d segments, total %.1fs, loudnorm=%s → %s",
            len(segments),
            total_s,
            loudnorm,
            out_path,
        )
        _ffmpeg(*encode_args)
        # tmp directory and all staging files cleaned up on context exit

    logger.info("build_audio_track: done → %s (%.1f KB)", out_path, out_path.stat().st_size / 1024)
    return out_path
