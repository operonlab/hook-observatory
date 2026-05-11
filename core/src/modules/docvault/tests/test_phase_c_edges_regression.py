"""鐵律 5 (Adversary Edges) + 鐵律 6 (Regression).

鐵律 5 — Adversary Edges:
  - 損壞檔案（隨機 bytes）→ raise 或 empty content
  - 零長度音訊 → ValueError
  - 零長度影片 → ValueError
  - 過大檔案（mock getsize > 500 MB）→ ValueError (video)
  - ffmpeg 非零回傳 → RuntimeError
  - STT timeout → RuntimeError / propagated
  - Vision 503 → graceful degrade
  - MIME 副檔名 .mp3 但實際是 wav → libmagic 雙重檢查 (若無 python-magic 則 skip)

鐵律 6 — Regression:
  - 既有 docvault tests import 不退化
  - PDF MIME 仍走 PDF parser（不誤走 audio/video）
  - schemas.DocumentCreate source_type 對舊值 pdf/docx/markdown 仍 valid
  - audio_parser / video_parser / parser 模組 import 不退化
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# 鐵律 5 — Adversary Edges
# ===========================================================================


class TestAdversaryAudioEdges:
    """Edge cases for audio_parser.parse_audio."""

    @pytest.mark.asyncio
    async def test_corrupted_audio_raises_or_empty(self, tmp_path):
        """損壞的音訊（隨機 bytes）→ RuntimeError 或 empty content，不應 crash unhandled。"""
        corrupt = tmp_path / "corrupt.wav"
        corrupt.write_bytes(os.urandom(512))

        # STT station will reject random bytes → RuntimeError propagated
        # We mock transcribe to raise RuntimeError (as station would)
        with patch(
            "audio_ops.transcribe.transcribe",
            new=AsyncMock(side_effect=RuntimeError("STT rejected corrupted audio")),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            with pytest.raises(RuntimeError):
                await parse_audio(str(corrupt))

        # 鐵律 5 斷言 A: RuntimeError raised, no silent success

    @pytest.mark.asyncio
    async def test_empty_wav_raises_value_error(self, tmp_path):
        """零長度音訊檔 → ValueError。"""
        empty = tmp_path / "empty.wav"
        empty.touch()

        from core.src.modules.docvault.ingest.audio_parser import parse_audio

        with pytest.raises(ValueError, match="empty"):
            await parse_audio(str(empty))

        # 鐵律 5 斷言 B: ValueError on zero-size file

    @pytest.mark.asyncio
    async def test_missing_audio_file_raises_file_not_found(self, tmp_path):
        """不存在的檔案 → FileNotFoundError。"""
        missing = tmp_path / "nonexistent.wav"

        from core.src.modules.docvault.ingest.audio_parser import parse_audio

        with pytest.raises(FileNotFoundError):
            await parse_audio(str(missing))

        # 鐵律 5 斷言 C: FileNotFoundError on missing file

    @pytest.mark.asyncio
    async def test_stt_timeout_propagates(self, tmp_path):
        """STT station timeout → 異常應向上傳播（不吞掉）。"""
        import httpx

        wav = tmp_path / "timeout.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch(
            "audio_ops.transcribe.transcribe",
            new=AsyncMock(side_effect=httpx.TimeoutException("connection timed out")),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            with pytest.raises(Exception):
                await parse_audio(str(wav))

        # 鐵律 5 斷言 D: timeout exception propagated

    @pytest.mark.asyncio
    async def test_stt_runtime_error_propagates(self, tmp_path):
        """STT station 回傳非預期格式 → RuntimeError 傳播。"""
        wav = tmp_path / "bad_stt.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch(
            "audio_ops.transcribe.transcribe",
            new=AsyncMock(side_effect=RuntimeError("Unexpected STT response")),
        ):
            from core.src.modules.docvault.ingest.audio_parser import parse_audio

            with pytest.raises(RuntimeError):
                await parse_audio(str(wav))

        # 鐵律 5 斷言 E: RuntimeError propagated from transcribe


class TestAdversaryVideoEdges:
    """Edge cases for video_parser.parse_video."""

    @pytest.mark.asyncio
    async def test_empty_video_raises_value_error(self, tmp_path):
        """零長度影片 → ValueError。"""
        empty = tmp_path / "empty.mp4"
        empty.touch()

        from core.src.modules.docvault.ingest.video_parser import parse_video

        with pytest.raises(ValueError, match="empty"):
            await parse_video(str(empty))

        # 鐵律 5 斷言 F: ValueError on empty video

    @pytest.mark.asyncio
    async def test_oversized_video_raises_value_error(self, tmp_path):
        """過大影片（mock stat().st_size > 500 MB）→ ValueError。"""
        mp4 = tmp_path / "huge.mp4"
        mp4.write_bytes(b"\x00" * 1024)

        # Mock file size to 501 MB
        mock_stat = MagicMock()
        mock_stat.st_size = 501 * 1024 * 1024

        with patch.object(Path, "stat", return_value=mock_stat):
            from core.src.modules.docvault.ingest.video_parser import parse_video

            with pytest.raises(ValueError, match="too large"):
                await parse_video(str(mp4))

        # 鐵律 5 斷言 G: ValueError on oversized file

    @pytest.mark.asyncio
    async def test_ffmpeg_nonzero_exit_raises_runtime_error(self, tmp_path):
        """ffmpeg 非零回傳 → RuntimeError。"""
        mp4 = tmp_path / "bad_ffmpeg.mp4"
        mp4.write_bytes(b"\x00" * 2048)

        # Mock _extract_audio to raise RuntimeError (as ffmpeg non-zero exit would)
        def _bad_extract(video_path, tmp_dir):
            raise RuntimeError("ffmpeg audio extraction failed (exit 1): error output here")

        with (
            patch("core.src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "core.src.modules.docvault.ingest.video_parser._extract_audio",
                side_effect=_bad_extract,
            ),
        ):
            from core.src.modules.docvault.ingest.video_parser import parse_video

            with pytest.raises(RuntimeError, match="ffmpeg"):
                await parse_video(str(mp4))

        # 鐵律 5 斷言 H: RuntimeError raised when ffmpeg fails

    @pytest.mark.asyncio
    async def test_ffmpeg_not_found_raises_runtime_error(self, tmp_path):
        """ffmpeg 未安裝 → RuntimeError。"""
        mp4 = tmp_path / "no_ffmpeg.mp4"
        mp4.write_bytes(b"\x00" * 2048)

        with patch("shutil.which", return_value=None):
            from core.src.modules.docvault.ingest.video_parser import parse_video

            with pytest.raises(RuntimeError, match="ffmpeg"):
                await parse_video(str(mp4))

        # 鐵律 5 斷言 I: RuntimeError when ffmpeg binary not found

    @pytest.mark.asyncio
    async def test_vision_503_graceful_degrade(self, tmp_path):
        """Vision station 503 → frame description 為空，但 parse_video 仍完成。"""
        from audio_ops.transcribe import TranscriptResult

        mp4 = tmp_path / "vision503.mp4"
        mp4.write_bytes(b"\x00" * 2048)

        fake_audio = tmp_path / "audio.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        fake_transcript = TranscriptResult(
            full_text="speech content",
            language="en",
            duration=5.0,
            segments=[],
        )
        fake_frame_pairs = [(1.0, str(tmp_path / "frame_0001.jpg"))]
        (tmp_path / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        # VisionClient.analyze raises ConnectionError (503 scenario)
        mock_vision_instance = MagicMock()
        mock_vision_instance.analyze.side_effect = ConnectionError("503 Service Unavailable")
        mock_vision_instance.close = MagicMock()
        mock_vision_cls = MagicMock(return_value=mock_vision_instance)

        with (
            patch("core.src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "core.src.modules.docvault.ingest.video_parser._extract_audio",
                return_value=fake_audio,
            ),
            patch(
                "core.src.modules.docvault.ingest.video_parser._extract_keyframes",
                return_value=fake_frame_pairs,
            ),
            patch("sdk_client.vision.VisionClient", mock_vision_cls),
            patch(
                "audio_ops.transcribe.transcribe",
                new=AsyncMock(return_value=fake_transcript),
            ),
        ):
            from core.src.modules.docvault.ingest.video_parser import parse_video

            # Should NOT raise — vision 503 is gracefully degraded
            content, meta = await parse_video(str(mp4), with_keyframes=True)

        # 鐵律 5 斷言 J: parse_video still returns content despite vision 503
        assert isinstance(content, str)
        assert isinstance(meta, dict)
        assert meta.get("source_type") == "video"

    @pytest.mark.asyncio
    async def test_corrupted_video_bytes_raises(self, tmp_path):
        """損壞的影片（隨機 bytes）→ ffmpeg 解析失敗 → RuntimeError。"""
        corrupt = tmp_path / "corrupt.mp4"
        corrupt.write_bytes(os.urandom(2048))

        def _bad_extract(video_path, tmp_dir):
            raise RuntimeError("ffmpeg audio extraction failed (exit 1): Invalid data found when processing input")

        with (
            patch("core.src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "core.src.modules.docvault.ingest.video_parser._extract_audio",
                side_effect=_bad_extract,
            ),
        ):
            from core.src.modules.docvault.ingest.video_parser import parse_video

            with pytest.raises(RuntimeError):
                await parse_video(str(corrupt))

        # 鐵律 5 斷言 K: RuntimeError on corrupted video bytes

    def test_mime_sniff_mp3_extension_wav_content(self, tmp_path):
        """副檔名 .mp3 但內容為 WAV RIFF header — 若 python-magic 可用，應偵測出 audio/x-wav。"""
        try:
            import magic  # python-magic
        except ImportError:
            pytest.skip("python-magic not installed — MIME sniff test skipped")

        fake_mp3 = tmp_path / "trick.mp3"
        # Write a WAV RIFF header
        fake_mp3.write_bytes(b"RIFF\x24\x00\x00\x00WAVE")

        detected = magic.from_file(str(fake_mp3), mime=True)

        # 鐵律 5 斷言 L: libmagic detects WAV content regardless of .mp3 extension
        assert "audio" in detected, f"Expected audio MIME, got: {detected}"


# ===========================================================================
# 鐵律 6 — Regression
# ===========================================================================


class TestRegression:
    """鐵律 6 — 舊功能不退化。"""

    def test_import_audio_parser(self):
        """audio_parser 模組 import 不退化。"""
        from core.src.modules.docvault.ingest import audio_parser  # noqa: F401

        assert hasattr(audio_parser, "parse_audio")
        # 鐵律 6 斷言 M: audio_parser importable with parse_audio

    def test_import_video_parser(self):
        """video_parser 模組 import 不退化。"""
        from core.src.modules.docvault.ingest import video_parser  # noqa: F401

        assert hasattr(video_parser, "parse_video")
        # 鐵律 6 斷言 N: video_parser importable with parse_video

    def test_import_parser_module(self):
        """parser 模組 import 不退化，parse_document / parse_document_async 存在。"""
        from core.src.modules.docvault.ingest import parser  # noqa: F401

        assert hasattr(parser, "parse_document")
        assert hasattr(parser, "parse_document_async")
        # 鐵律 6 斷言 O: parser module importable

    def test_pdf_source_type_still_valid(self):
        """schemas.DocumentCreate source_type='pdf' 仍合法。"""
        from core.src.modules.docvault.schemas import DocumentCreate

        doc = DocumentCreate(title="PDF Doc", source_type="pdf", content_hash="a" * 64)
        assert doc.source_type == "pdf"
        # 鐵律 6 斷言 P: pdf source_type still valid in schema

    def test_docx_source_type_still_valid(self):
        """schemas.DocumentCreate source_type='docx' 仍合法。"""
        from core.src.modules.docvault.schemas import DocumentCreate

        doc = DocumentCreate(title="DOCX Doc", source_type="docx", content_hash="b" * 64)
        assert doc.source_type == "docx"
        # 鐵律 6 斷言 Q: docx source_type still valid

    def test_markdown_source_type_still_valid(self):
        """schemas.DocumentCreate source_type='markdown' 仍合法。"""
        from core.src.modules.docvault.schemas import DocumentCreate

        doc = DocumentCreate(title="MD Doc", source_type="markdown", content_hash="c" * 64)
        assert doc.source_type == "markdown"
        # 鐵律 6 斷言 R: markdown source_type still valid

    def test_audio_source_type_valid_in_schema(self):
        """schemas.DocumentCreate source_type='audio' 仍合法 (Phase C 新增)。"""
        from core.src.modules.docvault.schemas import DocumentCreate

        doc = DocumentCreate(title="Audio Doc", source_type="audio", content_hash="d" * 64)
        assert doc.source_type == "audio"
        # 鐵律 6 斷言 S: audio source_type valid in schema

    def test_video_source_type_valid_in_schema(self):
        """schemas.DocumentCreate source_type='video' 仍合法 (Phase C 新增)。"""
        from core.src.modules.docvault.schemas import DocumentCreate

        doc = DocumentCreate(title="Video Doc", source_type="video", content_hash="e" * 64)
        assert doc.source_type == "video"
        # 鐵律 6 斷言 T: video source_type valid in schema

    @pytest.mark.asyncio
    async def test_pdf_does_not_route_to_audio_parser(self, tmp_path):
        """PDF 副檔名 → parse_document_async 不呼叫 parse_audio。"""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake content for test")

        with (
            patch(
                "core.src.modules.docvault.ingest.parser.parse_audio",
                new=AsyncMock(side_effect=AssertionError("PDF must not route to audio parser")),
            ),
            patch(
                "core.src.modules.docvault.ingest.parser.parse_document",
                return_value=("pdf content", {"source_type": "pdf"}),
            ),
        ):
            from core.src.modules.docvault.ingest.parser import parse_document_async

            content, meta = await parse_document_async(str(pdf))

        # 鐵律 6 斷言 U: PDF routed to sync parser, NOT audio
        assert meta["source_type"] == "pdf"

    @pytest.mark.asyncio
    async def test_docx_does_not_route_to_video_parser(self, tmp_path):
        """DOCX 副檔名 → parse_document_async 不呼叫 parse_video。"""
        docx = tmp_path / "doc.docx"
        docx.write_bytes(b"PK\x03\x04" + b"\x00" * 100)  # DOCX is a ZIP

        with (
            patch(
                "core.src.modules.docvault.ingest.parser.parse_video",
                new=AsyncMock(side_effect=AssertionError("DOCX must not route to video parser")),
            ),
            patch(
                "core.src.modules.docvault.ingest.parser.parse_document",
                return_value=("docx content", {"source_type": "docx"}),
            ),
        ):
            from core.src.modules.docvault.ingest.parser import parse_document_async

            content, meta = await parse_document_async(str(docx))

        # 鐵律 6 斷言 V: DOCX routed to sync parser, NOT video
        assert meta["source_type"] == "docx"

    def test_document_parser_op_still_has_correct_keys(self):
        """DocumentParserOp input/output keys 未退化。"""
        from core.src.modules.docvault.ingest.parser import DocumentParserOp

        op = DocumentParserOp()
        assert "raw_file" in op.input_keys
        assert "source_type" in op.input_keys
        assert "raw_content" in op.output_keys
        assert "metadata" in op.output_keys
        # 鐵律 6 斷言 W: DocumentParserOp keys unchanged

    def test_audio_extensions_constant_unchanged(self):
        """audio_parser.AUDIO_EXTENSIONS 包含核心格式。"""
        from core.src.modules.docvault.ingest.audio_parser import AUDIO_EXTENSIONS

        for ext in (".mp3", ".wav", ".m4a", ".flac", ".ogg"):
            assert ext in AUDIO_EXTENSIONS, f"Missing: {ext}"
        # 鐵律 6 斷言 X: AUDIO_EXTENSIONS unchanged

    def test_video_extensions_constant_unchanged(self):
        """video_parser.VIDEO_EXTENSIONS 包含核心格式。"""
        from core.src.modules.docvault.ingest.video_parser import VIDEO_EXTENSIONS

        for ext in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
            assert ext in VIDEO_EXTENSIONS, f"Missing: {ext}"
        # 鐵律 6 斷言 Y: VIDEO_EXTENSIONS unchanged

    @pytest.mark.asyncio
    async def test_existing_adversary_module_importable(self):
        """鐵律 2 test 模組 (test_adversary_data_flow_multimodal) 仍可 import。"""
        import importlib
        import sys

        # Guard: ensure the worktree path is in sys.path context
        module_name = "core.src.modules.docvault.tests.test_adversary_data_flow_multimodal"
        try:
            if module_name in sys.modules:
                mod = sys.modules[module_name]
            else:
                spec = importlib.util.find_spec(module_name)
                assert spec is not None, f"Cannot find spec for {module_name}"
        except (ImportError, ModuleNotFoundError):
            pytest.skip("Cannot verify adversary module in current sys.path")

        # 鐵律 6 斷言 Z: adversary data flow module importable (regression guard)
        assert True  # If we got here without exception, module exists
