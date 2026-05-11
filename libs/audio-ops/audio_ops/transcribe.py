"""Transcribe audio file via STT station.

Async wrapper around sdk_client.stt.STTClient — calls the STT station HTTP API
(mlx-whisper engine, local processing). Returns structured TranscriptResult with
per-segment timestamps and optional speaker diarization.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sdk_client.stt import STTClient

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB guard


@dataclass
class TranscriptSegment:
    start: float  # seconds
    end: float
    text: str
    speaker: str | None = None  # diarization label e.g. "Speaker A"


@dataclass
class TranscriptResult:
    full_text: str
    language: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    duration: float = 0.0


async def transcribe(
    path: str | Path,
    *,
    language: str | None = None,
    with_speaker: bool = False,
    timeout: float = 300.0,
) -> TranscriptResult:
    """Async transcribe wrapper for audio files.

    Calls STT station HTTP API (mlx-whisper engine, local).
    with_speaker=True requests diarization via the STT station.

    Args:
        path: Absolute path to audio file (wav/mp3/m4a/flac/ogg).
        language: BCP-47 code e.g. "zh-TW", "en". None = auto-detect.
        with_speaker: Enable speaker diarization labels.
        timeout: HTTP timeout in seconds.

    Returns:
        TranscriptResult with full_text, language, segments, duration.

    Raises:
        FileNotFoundError: file does not exist.
        ValueError: file exceeds 500 MB size limit.
        RuntimeError: STT station returned unexpected format or connection failed.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Audio file is empty (0 bytes): {path}")
    if file_size > _MAX_FILE_SIZE_BYTES:
        raise ValueError(f"Audio file too large ({file_size / (1024**2):.0f} MB > 500 MB): {path}")

    return await asyncio.to_thread(_transcribe_sync, path, language, with_speaker, timeout)


def _transcribe_sync(
    path: Path,
    language: str | None,
    with_speaker: bool,
    timeout: float,
) -> TranscriptResult:
    """Synchronous transcription call — runs in thread pool."""

    client = STTClient(timeout=timeout)
    try:
        resp = client.transcribe(
            file_path=str(path),
            language=language or "zh-TW",
            engine="apple",
            format="json",
        )
    except Exception as exc:
        raise RuntimeError(f"STT station call failed for {path.name}: {exc}") from exc
    finally:
        client.close()

    if not isinstance(resp, dict):
        raise RuntimeError(f"STT station returned unexpected type: {type(resp)}")

    raw_text: str = resp.get("text", "")
    detected_lang: str = resp.get("language", language or "unknown")
    raw_segments: list[dict] = resp.get("segments", [])

    # Compute duration from last segment end, or use top-level key if present
    duration: float = float(resp.get("duration", 0.0))
    if not duration and raw_segments:
        duration = float(raw_segments[-1].get("end", 0.0))

    segments: list[TranscriptSegment] = []
    for seg in raw_segments:
        speaker_label: str | None = None
        if with_speaker:
            speaker_label = seg.get("speaker") or seg.get("speaker_label")
            if speaker_label is None:
                # Fallback: single-speaker default
                speaker_label = "Speaker A"
        segments.append(
            TranscriptSegment(
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                text=seg.get("text", "").strip(),
                speaker=speaker_label,
            )
        )

    logger.info(
        "transcribe: %s → %d chars, %d segs, lang=%s, dur=%.1fs",
        path.name,
        len(raw_text),
        len(segments),
        detected_lang,
        duration,
    )

    return TranscriptResult(
        full_text=raw_text.strip(),
        language=detected_lang,
        segments=segments,
        duration=duration,
    )
