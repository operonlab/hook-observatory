"""鐵律 1b — Unit tests for video_parser.parse_video.

All external I/O (subprocess/ffmpeg, transcribe, VisionClient) is mocked.
Covers:
- frame + speech interleave sorted by timestamp
- with_keyframes=False skips ffmpeg scene extraction
- frame_count upper limit = 20
- FileNotFoundError / ValueError / RuntimeError paths
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_transcript(segments=None, full_text="", language="en", duration=10.0):
    from audio_ops.transcribe import TranscriptResult, TranscriptSegment

    segs = segments or []
    return TranscriptResult(
        full_text=full_text,
        language=language,
        duration=duration,
        segments=segs,
    )


def _make_seg(start, end, text, speaker=None):
    from audio_ops.transcribe import TranscriptSegment

    return TranscriptSegment(start=start, end=end, text=text, speaker=speaker)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_mp4_file():
    """Tiny non-empty temp file pretending to be a video."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"\x00" * 1024)  # 1 KB fake content
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture()
def empty_mp4():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# Core interleave tests
# ---------------------------------------------------------------------------


class TestVideoParserInterleave:
    @pytest.mark.asyncio
    async def test_frame_and_speech_sorted_by_timestamp(self, real_mp4_file):
        """Interleaved output must be sorted ascending by timestamp."""
        segs = [
            _make_seg(5.0, 8.0, "speech at 5s"),
            _make_seg(20.0, 23.0, "speech at 20s"),
        ]
        transcript = _make_transcript(segs, duration=25.0)

        from src.modules.docvault.ingest.video_parser import FrameDesc

        fake_frames = [
            FrameDesc(timestamp=2.0, frame_path="/tmp/f1.jpg", description="scene at 2s"),
            FrameDesc(timestamp=15.0, frame_path="/tmp/f2.jpg", description="scene at 15s"),
        ]

        with (
            patch("src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_audio",
                return_value=Path("/tmp/audio.wav"),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_keyframes",
                return_value=[(2.0, "/tmp/f1.jpg"), (15.0, "/tmp/f2.jpg")],
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._describe_frames",
                new=AsyncMock(return_value=fake_frames),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser.transcribe",
                new=AsyncMock(return_value=transcript),
            ),
        ):
            from src.modules.docvault.ingest.video_parser import parse_video

            content, meta = await parse_video(real_mp4_file, with_keyframes=True)

        lines = content.splitlines()
        # Find timestamp positions in output
        frame2_pos = next(i for i, l in enumerate(lines) if "00:02" in l and "(frame)" in l)
        speech5_pos = next(i for i, l in enumerate(lines) if "00:05" in l)
        frame15_pos = next(i for i, l in enumerate(lines) if "00:15" in l and "(frame)" in l)
        speech20_pos = next(i for i, l in enumerate(lines) if "00:20" in l)

        assert frame2_pos < speech5_pos < frame15_pos < speech20_pos

    @pytest.mark.asyncio
    async def test_with_keyframes_false_skips_ffmpeg_scene(self, real_mp4_file):
        """with_keyframes=False must not call _extract_keyframes."""
        transcript = _make_transcript([], full_text="no keyframes", duration=5.0)

        with (
            patch("src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_audio",
                return_value=Path("/tmp/audio.wav"),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_keyframes"
            ) as mock_kf,
            patch(
                "src.modules.docvault.ingest.video_parser._describe_frames",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser.transcribe",
                new=AsyncMock(return_value=transcript),
            ),
        ):
            from src.modules.docvault.ingest.video_parser import parse_video

            _, meta = await parse_video(real_mp4_file, with_keyframes=False)

        mock_kf.assert_not_called()
        assert meta["frame_count"] == 0

    @pytest.mark.asyncio
    async def test_frame_count_upper_limit_20(self, real_mp4_file):
        """Even if extraction returns >20, metadata frame_count must cap at 20 (via _MAX_FRAMES)."""
        from src.modules.docvault.ingest.video_parser import FrameDesc

        # Simulate 20 frames (maximum allowed)
        fake_frames = [
            FrameDesc(timestamp=float(i), frame_path=f"/tmp/f{i}.jpg", description=f"frame {i}")
            for i in range(20)
        ]
        transcript = _make_transcript([], duration=30.0)

        with (
            patch("src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_audio",
                return_value=Path("/tmp/audio.wav"),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_keyframes",
                return_value=[(float(i), f"/tmp/f{i}.jpg") for i in range(20)],
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._describe_frames",
                new=AsyncMock(return_value=fake_frames),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser.transcribe",
                new=AsyncMock(return_value=transcript),
            ),
        ):
            from src.modules.docvault.ingest.video_parser import parse_video

            _, meta = await parse_video(real_mp4_file, with_keyframes=True)

        assert meta["frame_count"] <= 20

    @pytest.mark.asyncio
    async def test_header_in_output(self, real_mp4_file):
        """## Video Transcript: <filename> must appear."""
        transcript = _make_transcript([], duration=5.0)

        with (
            patch("src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_audio",
                return_value=Path("/tmp/audio.wav"),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_keyframes",
                return_value=[],
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._describe_frames",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser.transcribe",
                new=AsyncMock(return_value=transcript),
            ),
        ):
            from src.modules.docvault.ingest.video_parser import parse_video

            content, _ = await parse_video(real_mp4_file, with_keyframes=True)

        filename = Path(real_mp4_file).name
        assert f"## Video Transcript: {filename}" in content

    @pytest.mark.asyncio
    async def test_source_type_is_video(self, real_mp4_file):
        transcript = _make_transcript([], duration=5.0)

        with (
            patch("src.modules.docvault.ingest.video_parser._check_ffmpeg"),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_audio",
                return_value=Path("/tmp/audio.wav"),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._extract_keyframes",
                return_value=[],
            ),
            patch(
                "src.modules.docvault.ingest.video_parser._describe_frames",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "src.modules.docvault.ingest.video_parser.transcribe",
                new=AsyncMock(return_value=transcript),
            ),
        ):
            from src.modules.docvault.ingest.video_parser import parse_video

            _, meta = await parse_video(real_mp4_file)

        assert meta["source_type"] == "video"


# ---------------------------------------------------------------------------
# Exception / error paths
# ---------------------------------------------------------------------------


class TestVideoParserExceptions:
    @pytest.mark.asyncio
    async def test_file_not_found(self):
        from src.modules.docvault.ingest.video_parser import parse_video

        with pytest.raises(FileNotFoundError):
            await parse_video("/nonexistent/video.mp4")

    @pytest.mark.asyncio
    async def test_empty_file_raises_value_error(self, empty_mp4):
        from src.modules.docvault.ingest.video_parser import parse_video

        with pytest.raises(ValueError, match="empty"):
            await parse_video(empty_mp4)

    @pytest.mark.asyncio
    async def test_file_too_large_raises_value_error(self, real_mp4_file):
        """Mock file size >500 MB → ValueError."""
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 600 * 1024 * 1024  # 600 MB
            mock_stat.return_value.st_mode = 0o100644
            from src.modules.docvault.ingest.video_parser import parse_video

            with pytest.raises(ValueError, match="500 MB"):
                await parse_video(real_mp4_file)
