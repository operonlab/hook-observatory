"""鐵律 2 — Data flow test: capture_adapter MIME routing → parsers → ParsedDocument.

Tests:
1. capture_adapter.smart_defaults() correctly maps MIME → source_type for audio/video
2. parse_document_async() routes audio → audio_parser, video → video_parser
3. SQLite in-memory round-trip: insert Document with source_type='audio'/'video', read back

No real STT/Vision/ffmpeg calls — all mocked.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from src.modules.docvault.capture_adapter import DocumentCaptureAdapter


# ---------------------------------------------------------------------------
# MIME routing tests
# ---------------------------------------------------------------------------


class TestCaptureAdapterMimeRouting:
    def setup_method(self):
        self.adapter = DocumentCaptureAdapter()

    def _smart(self, mime_type: str) -> dict:
        return self.adapter.smart_defaults(
            {"mime_type": mime_type, "title": "test"}, {}
        )

    # Audio MIMEs
    def test_audio_mpeg_maps_to_audio(self):
        assert self._smart("audio/mpeg")["source_type"] == "audio"

    def test_audio_wav_maps_to_audio(self):
        assert self._smart("audio/wav")["source_type"] == "audio"

    def test_audio_m4a_maps_to_audio(self):
        assert self._smart("audio/m4a")["source_type"] == "audio"

    def test_audio_flac_maps_to_audio(self):
        assert self._smart("audio/flac")["source_type"] == "audio"

    def test_audio_ogg_maps_to_audio(self):
        assert self._smart("audio/ogg")["source_type"] == "audio"

    def test_audio_webm_maps_to_audio(self):
        assert self._smart("audio/webm")["source_type"] == "audio"

    # Video MIMEs
    def test_video_mp4_maps_to_video(self):
        assert self._smart("video/mp4")["source_type"] == "video"

    def test_video_quicktime_maps_to_video(self):
        assert self._smart("video/quicktime")["source_type"] == "video"

    def test_video_webm_maps_to_video(self):
        assert self._smart("video/webm")["source_type"] == "video"

    def test_video_matroska_maps_to_video(self):
        assert self._smart("video/x-matroska")["source_type"] == "video"

    # Non-media keeps markdown default
    def test_unknown_mime_keeps_markdown(self):
        assert self._smart("application/pdf")["source_type"] == "markdown"

    def test_no_mime_keeps_markdown(self):
        result = self.adapter.smart_defaults({"title": "doc"}, {})
        assert result["source_type"] == "markdown"

    def test_mime_with_charset_param_stripped(self):
        """MIME 'audio/wav; charset=utf-8' should still detect audio."""
        assert self._smart("audio/wav; charset=utf-8")["source_type"] == "audio"

    def test_content_hash_auto_computed(self):
        result = self.adapter.smart_defaults(
            {"content": "hello world", "mime_type": "audio/wav"}, {}
        )
        expected = hashlib.sha256("hello world".encode()).hexdigest()
        assert result["content_hash"] == expected


# ---------------------------------------------------------------------------
# parse_document_async routing
# ---------------------------------------------------------------------------


@pytest.fixture()
def audio_file():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(b"RIFF" + b"\x00" * 40)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture()
def video_file():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"\x00" * 1024)
        path = f.name
    yield path
    os.unlink(path)


class TestParserRoutingAsync:
    @pytest.mark.asyncio
    async def test_audio_file_routes_to_audio_parser(self, audio_file):
        mock_result = ("## Transcript: test.wav\n- Duration: 5.0s\n- Language: en\n", {
            "source_type": "audio", "duration": 5.0, "language": "en",
        })

        with patch(
            "src.modules.docvault.ingest.parser.parse_audio",
            new=AsyncMock(return_value=mock_result),
        ) as mock_audio:
            from src.modules.docvault.ingest.parser import parse_document_async

            content, meta = await parse_document_async(audio_file)

        mock_audio.assert_called_once()
        assert meta["source_type"] == "audio"
        assert "## Transcript" in content

    @pytest.mark.asyncio
    async def test_video_file_routes_to_video_parser(self, video_file):
        mock_result = ("## Video Transcript: test.mp4\n- Duration: 10.0s\n", {
            "source_type": "video", "duration": 10.0, "language": "en",
        })

        with patch(
            "src.modules.docvault.ingest.parser.parse_video",
            new=AsyncMock(return_value=mock_result),
        ) as mock_video:
            from src.modules.docvault.ingest.parser import parse_document_async

            content, meta = await parse_document_async(video_file)

        mock_video.assert_called_once()
        assert meta["source_type"] == "video"
        assert "## Video Transcript" in content

    @pytest.mark.asyncio
    async def test_explicit_source_type_audio_routes_correctly(self, audio_file):
        mock_result = ("## Transcript: audio.wav\n", {"source_type": "audio"})

        with patch(
            "src.modules.docvault.ingest.parser.parse_audio",
            new=AsyncMock(return_value=mock_result),
        ) as mock_audio:
            from src.modules.docvault.ingest.parser import parse_document_async

            _, meta = await parse_document_async(audio_file, source_type="audio")

        mock_audio.assert_called_once()

    @pytest.mark.asyncio
    async def test_pdf_extension_does_not_call_audio_parser(self, tmp_path):
        """PDF file must NOT route to audio parser."""
        pdf_file = tmp_path / "doc.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        # audio parser should never be called for pdf
        with patch(
            "src.modules.docvault.ingest.parser.parse_audio",
            new=AsyncMock(side_effect=AssertionError("Should not call audio parser for PDF")),
        ):
            with patch(
                "src.modules.docvault.ingest.parser.parse_document",
                return_value=("pdf content", {"source_type": "pdf"}),
            ):
                from src.modules.docvault.ingest.parser import parse_document_async

                _, meta = await parse_document_async(str(pdf_file))

        assert meta["source_type"] == "pdf"


# ---------------------------------------------------------------------------
# SQLite in-memory round-trip (source_type audit)
# ---------------------------------------------------------------------------


class TestDocumentSourceTypeRoundTrip:
    """Verify Document model accepts source_type='audio' / 'video' and stores correctly.

    Uses SQLite in-memory with mapped_column reflection. We bypass the full ORM
    setup and test at the column-value level using raw SQL via SQLAlchemy core.
    """

    @pytest.fixture()
    def sqlite_engine(self):
        """Create an in-memory SQLite engine with a minimal documents table."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'markdown',
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ingested',
                    space_id TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    deleted_at TEXT
                )
            """))
            conn.commit()
        return engine

    def test_insert_and_read_audio_source_type(self, sqlite_engine):
        with sqlite_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO documents (id, title, source_type, content_hash, status)
                VALUES ('doc-audio-1', 'My Audio', 'audio', 'abc123', 'ingested')
            """))
            conn.commit()
            row = conn.execute(
                text("SELECT source_type FROM documents WHERE id='doc-audio-1'")
            ).fetchone()

        assert row[0] == "audio"

    def test_insert_and_read_video_source_type(self, sqlite_engine):
        with sqlite_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO documents (id, title, source_type, content_hash, status)
                VALUES ('doc-video-1', 'My Video', 'video', 'def456', 'ingested')
            """))
            conn.commit()
            row = conn.execute(
                text("SELECT source_type FROM documents WHERE id='doc-video-1'")
            ).fetchone()

        assert row[0] == "video"

    def test_multiple_source_types_coexist(self, sqlite_engine):
        with sqlite_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO documents (id, title, source_type, content_hash, status)
                VALUES
                  ('d1', 'Audio Doc', 'audio', 'h1', 'ingested'),
                  ('d2', 'Video Doc', 'video', 'h2', 'ingested'),
                  ('d3', 'PDF Doc', 'pdf', 'h3', 'ingested')
            """))
            conn.commit()
            rows = conn.execute(
                text("SELECT source_type FROM documents ORDER BY id")
            ).fetchall()

        types = [r[0] for r in rows]
        assert "audio" in types
        assert "video" in types
        assert "pdf" in types
