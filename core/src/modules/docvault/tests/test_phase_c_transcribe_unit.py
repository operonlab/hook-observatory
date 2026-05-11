"""鐵律 1c — Unit tests for audio_ops.transcribe.transcribe wrapper.

Mocks sdk_client.stt.STTClient so no real STT station is required.
Covers:
- TranscriptResult structure (full_text, language, segments, duration)
- with_speaker=True triggers speaker label in segments
- with_speaker=False → speaker=None in all segments
- language parameter is passed through
- File not found / empty file guard
- STT station exception → RuntimeError
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build a fake STTClient response
# ---------------------------------------------------------------------------


def _stt_response(text="hello", language="en", segments=None, duration=5.0):
    return {
        "text": text,
        "language": language,
        "duration": duration,
        "segments": segments or [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wav_file():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(b"RIFF" + b"\x00" * 40)
        path = f.name
    yield Path(path)
    os.unlink(path)


@pytest.fixture()
def empty_wav():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    yield Path(path)
    os.unlink(path)


# ---------------------------------------------------------------------------
# TranscriptResult structure
# ---------------------------------------------------------------------------


class TestTranscribeStructure:
    @pytest.mark.asyncio
    async def test_returns_transcript_result_type(self, wav_file):
        resp = _stt_response("hello world", language="en", duration=3.0)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch(
            "audio_ops.transcribe.STTClient", return_value=mock_client
        ):
            from audio_ops.transcribe import TranscriptResult, transcribe

            result = await transcribe(wav_file)

        assert isinstance(result, TranscriptResult)

    @pytest.mark.asyncio
    async def test_full_text_preserved(self, wav_file):
        resp = _stt_response("the quick brown fox", language="en", duration=4.0)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            result = await transcribe(wav_file)

        assert result.full_text == "the quick brown fox"

    @pytest.mark.asyncio
    async def test_language_returned(self, wav_file):
        resp = _stt_response("text", language="zh-TW", duration=2.0)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            result = await transcribe(wav_file, language="zh-TW")

        assert result.language == "zh-TW"

    @pytest.mark.asyncio
    async def test_duration_from_response(self, wav_file):
        resp = _stt_response("text", language="en", duration=12.3)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            result = await transcribe(wav_file)

        assert abs(result.duration - 12.3) < 0.01

    @pytest.mark.asyncio
    async def test_segments_parsed(self, wav_file):
        raw_segs = [
            {"start": 0.0, "end": 2.0, "text": "first"},
            {"start": 2.0, "end": 4.5, "text": "second"},
        ]
        resp = _stt_response("first second", language="en", segments=raw_segs, duration=4.5)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            result = await transcribe(wav_file)

        assert len(result.segments) == 2
        assert result.segments[0].text == "first"
        assert result.segments[1].start == 2.0


# ---------------------------------------------------------------------------
# Speaker diarization
# ---------------------------------------------------------------------------


class TestTranscribeSpeaker:
    @pytest.mark.asyncio
    async def test_with_speaker_true_assigns_label(self, wav_file):
        """with_speaker=True → speaker label in segments (fallback Speaker A if not in resp)."""
        raw_segs = [{"start": 0.0, "end": 2.0, "text": "hello"}]
        resp = _stt_response(segments=raw_segs, duration=2.0)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            result = await transcribe(wav_file, with_speaker=True)

        assert result.segments[0].speaker is not None
        assert "Speaker" in result.segments[0].speaker

    @pytest.mark.asyncio
    async def test_with_speaker_true_uses_response_label(self, wav_file):
        """If response provides speaker_label, it is used directly."""
        raw_segs = [{"start": 0.0, "end": 2.0, "text": "hi", "speaker_label": "SPEAKER_0"}]
        resp = _stt_response(segments=raw_segs, duration=2.0)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            result = await transcribe(wav_file, with_speaker=True)

        assert result.segments[0].speaker == "SPEAKER_0"

    @pytest.mark.asyncio
    async def test_with_speaker_false_yields_none(self, wav_file):
        """with_speaker=False → all segments have speaker=None."""
        raw_segs = [{"start": 0.0, "end": 2.0, "text": "hello", "speaker_label": "SPEAKER_0"}]
        resp = _stt_response(segments=raw_segs, duration=2.0)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            result = await transcribe(wav_file, with_speaker=False)

        assert result.segments[0].speaker is None

    @pytest.mark.asyncio
    async def test_language_passthrough_to_client(self, wav_file):
        """language param must be forwarded to STTClient.transcribe."""
        resp = _stt_response("text", language="ja", duration=1.0)
        mock_client = MagicMock()
        mock_client.transcribe.return_value = resp
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            await transcribe(wav_file, language="ja")

        call_kwargs = mock_client.transcribe.call_args
        # language should be "ja"
        assert call_kwargs.kwargs.get("language") == "ja" or "ja" in str(call_kwargs)


# ---------------------------------------------------------------------------
# File guard
# ---------------------------------------------------------------------------


class TestTranscribeFileGuard:
    @pytest.mark.asyncio
    async def test_file_not_found_raises(self):
        from audio_ops.transcribe import transcribe

        with pytest.raises(FileNotFoundError):
            await transcribe(Path("/nonexistent/audio.wav"))

    @pytest.mark.asyncio
    async def test_empty_file_raises_value_error(self, empty_wav):
        from audio_ops.transcribe import transcribe

        with pytest.raises(ValueError, match="empty"):
            await transcribe(empty_wav)

    @pytest.mark.asyncio
    async def test_stt_exception_wraps_to_runtime_error(self, wav_file):
        """If STTClient.transcribe raises, it must propagate as RuntimeError."""
        mock_client = MagicMock()
        mock_client.transcribe.side_effect = ConnectionRefusedError("port closed")
        mock_client.close.return_value = None

        with patch("audio_ops.transcribe.STTClient", return_value=mock_client):
            from audio_ops.transcribe import transcribe

            with pytest.raises(RuntimeError, match="STT station call failed"):
                await transcribe(wav_file)
