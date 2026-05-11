"""鐵律 1a — Unit tests for audio_parser.parse_audio.

Mocks audio_ops.transcribe so no STT station is required.
Covers:
- Markdown format (## Transcript header / Speaker label / timestamp)
- with_speaker=True / False
- Empty transcript
- Single speaker
- No diarization (speaker=None segments)
- language=zh-TW
- File-not-found → FileNotFoundError
- Empty file → ValueError
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to build fake TranscriptResult without importing audio_ops directly
# ---------------------------------------------------------------------------


def _make_segment(start: float, end: float, text: str, speaker: str | None = None):
    """Create a TranscriptSegment-like dataclass instance."""
    from audio_ops.transcribe import TranscriptSegment

    return TranscriptSegment(start=start, end=end, text=text, speaker=speaker)


def _make_result(
    full_text: str,
    language: str,
    duration: float,
    segments: list,
):
    from audio_ops.transcribe import TranscriptResult

    return TranscriptResult(
        full_text=full_text,
        language=language,
        duration=duration,
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_wav_file():
    """Create a tiny non-empty temp WAV file for existence checks."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(b"RIFF" + b"\x00" * 40)  # minimal valid-ish header
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture()
def empty_file():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# Markdown format tests
# ---------------------------------------------------------------------------


class TestAudioParserMarkdownFormat:
    @pytest.mark.asyncio
    async def test_header_present(self, real_wav_file):
        """## Transcript: <filename> must appear in output."""
        result = _make_result("Hello world", "en", 5.0, [])

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, metadata = await parse_audio(real_wav_file)

        filename = Path(real_wav_file).name
        assert f"## Transcript: {filename}" in content

    @pytest.mark.asyncio
    async def test_duration_line(self, real_wav_file):
        result = _make_result("text", "en", 12.5, [])

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, _ = await parse_audio(real_wav_file)

        assert "- Duration: 12.5s" in content

    @pytest.mark.asyncio
    async def test_language_line(self, real_wav_file):
        result = _make_result("text", "zh-TW", 3.0, [])

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, _ = await parse_audio(real_wav_file, language="zh-TW")

        assert "- Language: zh-TW" in content

    @pytest.mark.asyncio
    async def test_speaker_label_format(self, real_wav_file):
        """Segments with speaker should produce **[Speaker A] [00:00]**: text."""
        segs = [
            _make_segment(0.0, 3.0, "Hello", speaker="Speaker A"),
            _make_segment(15.0, 18.0, "World", speaker="Speaker B"),
        ]
        result = _make_result("Hello World", "en", 18.0, segs)

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, _ = await parse_audio(real_wav_file, with_speaker=True)

        assert "**[Speaker A] [00:00]**: Hello" in content
        assert "**[Speaker B] [00:15]**: World" in content

    @pytest.mark.asyncio
    async def test_timestamp_format_no_speaker(self, real_wav_file):
        """Segments without speaker label → **[MM:SS]**: text."""
        segs = [
            _make_segment(0.0, 2.0, "First", speaker=None),
            _make_segment(65.0, 67.0, "Second", speaker=None),
        ]
        result = _make_result("First Second", "en", 67.0, segs)

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, _ = await parse_audio(real_wav_file, with_speaker=False)

        assert "**[00:00]**: First" in content
        assert "**[01:05]**: Second" in content

    @pytest.mark.asyncio
    async def test_with_speaker_false_no_labels(self, real_wav_file):
        """with_speaker=False → speaker labels must not appear."""
        segs = [_make_segment(0.0, 2.0, "Hello", speaker="Speaker A")]
        result = _make_result("Hello", "en", 2.0, segs)

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, _ = await parse_audio(real_wav_file, with_speaker=False)

        # Speaker A should NOT appear; no speaker in segment so label omitted
        assert "Speaker A" not in content


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestAudioParserEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_transcript(self, real_wav_file):
        """No segments, no full_text → *(empty transcript)* marker."""
        result = _make_result("", "en", 0.0, [])

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, meta = await parse_audio(real_wav_file)

        assert "*(empty transcript)*" in content
        assert meta["segment_count"] == 0

    @pytest.mark.asyncio
    async def test_full_text_fallback_when_no_segments(self, real_wav_file):
        """full_text emitted as block when segments is empty."""
        result = _make_result("fallback text only", "en", 5.0, [])

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, _ = await parse_audio(real_wav_file)

        assert "fallback text only" in content

    @pytest.mark.asyncio
    async def test_single_speaker(self, real_wav_file):
        segs = [_make_segment(0.0, 5.0, "Single speaker text", speaker="Speaker A")]
        result = _make_result("Single speaker text", "en", 5.0, segs)

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            content, meta = await parse_audio(real_wav_file, with_speaker=True)

        assert "Speaker A" in content
        assert meta["has_speaker"] is True

    @pytest.mark.asyncio
    async def test_no_diarization_segments_have_no_speaker(self, real_wav_file):
        """Segments with speaker=None → has_speaker=False in metadata."""
        segs = [_make_segment(0.0, 3.0, "text", speaker=None)]
        result = _make_result("text", "en", 3.0, segs)

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            _, meta = await parse_audio(real_wav_file, with_speaker=True)

        assert meta["has_speaker"] is False

    @pytest.mark.asyncio
    async def test_language_zh_tw_passthrough(self, real_wav_file):
        """language=zh-TW must appear in returned metadata."""
        result = _make_result("text", "zh-TW", 2.0, [])

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            _, meta = await parse_audio(real_wav_file, language="zh-TW")

        assert meta["language"] == "zh-TW"

    @pytest.mark.asyncio
    async def test_metadata_source_type_is_audio(self, real_wav_file):
        result = _make_result("x", "en", 1.0, [])

        with patch(
            "core.src.modules.docvault.ingest.audio_parser.transcribe",
            new=AsyncMock(return_value=result),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            _, meta = await parse_audio(real_wav_file)

        assert meta["source_type"] == "audio"


# ---------------------------------------------------------------------------
# Exception tests
# ---------------------------------------------------------------------------


class TestAudioParserExceptions:
    @pytest.mark.asyncio
    async def test_file_not_found(self):
        from core.src.modules.docvault.ingest.audio_parser import parse_audio

        with pytest.raises(FileNotFoundError):
            await parse_audio("/nonexistent/path/audio.wav")

    @pytest.mark.asyncio
    async def test_empty_file_raises_value_error(self, empty_file):
        from core.src.modules.docvault.ingest.audio_parser import parse_audio

        with pytest.raises(ValueError, match="empty"):
            await parse_audio(empty_file)
