"""Parse audio files (mp3/wav/m4a/flac/ogg) into Markdown via STT station.

Calls audio_ops.transcribe which wraps sdk_client.stt.STTClient.
Returns content as Markdown with timestamps and speaker labels.

Output format:
    ## Transcript: <filename>
    - Duration: <duration>s
    - Language: <lang>

    **[Speaker A] [00:00]**: <text>
    **[Speaker A] [00:15]**: <text>

If no segments are returned, raw full_text is emitted as a single block.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audio_ops.transcribe import transcribe

logger = logging.getLogger(__name__)

# Supported MIME types routed to this parser
AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus", ".wma"}
)


def _format_time(seconds: float) -> str:
    """Format seconds → MM:SS string."""
    s = int(seconds)
    m, sec = divmod(s, 60)
    return f"{m:02d}:{sec:02d}"


async def parse_audio(
    file_path: str | Path,
    *,
    language: str | None = None,
    with_speaker: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Parse audio file → (markdown_content, metadata).

    Args:
        file_path: Absolute path to audio file.
        language: BCP-47 language hint (None = auto-detect).
        with_speaker: Enable speaker diarization labels.

    Returns:
        Tuple of (markdown string, metadata dict).

    Raises:
        FileNotFoundError: File does not exist.
        ValueError: File is empty or too large (>500 MB).
        RuntimeError: STT station unreachable or returned unexpected format.
    """

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Audio file is empty (0 bytes): {file_path}")

    logger.info("audio_parser: transcribing %s (%.1f MB)", path.name, file_size / (1024**2))

    result = await transcribe(path, language=language, with_speaker=with_speaker)

    # ── Build Markdown ──────────────────────────────────────────────────────
    lines: list[str] = []
    lines.append(f"## Transcript: {path.name}")
    lines.append(f"- Duration: {result.duration:.1f}s")
    lines.append(f"- Language: {result.language}")
    lines.append("")

    if result.segments:
        for seg in result.segments:
            ts = _format_time(seg.start)
            if with_speaker and seg.speaker:
                lines.append(f"**[{seg.speaker}] [{ts}]**: {seg.text}")
            else:
                lines.append(f"**[{ts}]**: {seg.text}")
    elif result.full_text:
        # No segment data — emit full text as a block
        lines.append(result.full_text)
    else:
        lines.append("*(empty transcript)*")

    content = "\n".join(lines)

    metadata: dict[str, Any] = {
        "source_type": "audio",
        "title": path.stem,
        "file_path": str(path),
        "file_size": file_size,
        "duration": result.duration,
        "language": result.language,
        "segment_count": len(result.segments),
        "has_speaker": with_speaker and any(s.speaker for s in result.segments),
    }

    logger.info(
        "audio_parser: %s → %d chars, %d segments",
        path.name,
        len(content),
        len(result.segments),
    )

    return content, metadata
