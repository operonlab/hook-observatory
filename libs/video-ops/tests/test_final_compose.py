"""Tests for video_ops.final_compose — invariant-based, ffmpeg fixture-driven.

Strategy:
  - Generate frame sequence via ffmpeg color source → assemble_frames not
    needed; we write raw PNGs sized 320x180 for speed (1920x1080 wastes
    test time)
  - Audio track is ffmpeg lavfi anullsrc
  - Subtitles is a hand-written 2-cue SRT
  - All invariants verified via ffprobe (independent of compose internals)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from video_ops.final_compose import ComposeResult, SkippableError, compose_final

WIDTH, HEIGHT = 320, 180
FPS = 10
NUM_FRAMES = 30  # 3 seconds at 10fps


# ── ffmpeg / ffprobe helpers ──────────────────────────────────────────────────


def make_frames(out_dir: Path, num: int = NUM_FRAMES, pad: int = 6, fmt: str = "png"):
    """Generate `num` frames numbered <NNNNNN>.<ext> in out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "jpg" if fmt in ("jpeg", "jpg") else "png"
    for i in range(num):
        name = out_dir / f"{str(i).zfill(pad)}.{ext}"
        # Solid color frame; alternate colors so frames aren't bit-identical
        color = "red" if i % 2 == 0 else "blue"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={WIDTH}x{HEIGHT}:d=0.1",
                "-frames:v",
                "1",
                str(name),
            ],
            check=True,
        )
    return pad


def make_audio(path: Path, duration_seconds: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            str(duration_seconds),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
        ],
        check=True,
    )


def make_srt(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nFirst cue\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\nSecond cue\n",
        encoding="utf-8",
    )


def ffprobe_streams(path: Path) -> list[dict]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-print_format", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)["streams"]


def ffprobe_duration_s(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def compose_inputs(tmp_path):
    frames_dir = tmp_path / "frames"
    pad = make_frames(frames_dir)
    audio_path = tmp_path / "audio.m4a"
    make_audio(audio_path, duration_seconds=NUM_FRAMES / FPS)
    return frames_dir, audio_path, pad


# ── INV-1: video codec h264, pix_fmt yuv420p ─────────────────────────────────
def test_inv1_video_codec_h264_yuv420p(compose_inputs, tmp_path):
    frames_dir, audio_path, pad = compose_inputs
    out_dir = tmp_path / "out"
    result = compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
    )
    assert isinstance(result, ComposeResult)
    streams = ffprobe_streams(result.mp4_path)
    v = next(s for s in streams if s["codec_type"] == "video")
    assert v["codec_name"] == "h264", f"codec={v['codec_name']}"
    assert v["pix_fmt"] == "yuv420p", f"pix_fmt={v['pix_fmt']}"


# ── INV-2: audio codec aac ───────────────────────────────────────────────────
def test_inv2_audio_codec_aac(compose_inputs, tmp_path):
    frames_dir, audio_path, pad = compose_inputs
    out_dir = tmp_path / "out"
    result = compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
    )
    streams = ffprobe_streams(result.mp4_path)
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert a["codec_name"] == "aac"


# ── INV-3: video fps matches argument ────────────────────────────────────────
def test_inv3_video_fps_matches_argument(compose_inputs, tmp_path):
    frames_dir, audio_path, pad = compose_inputs
    out_dir = tmp_path / "out"
    result = compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
    )
    streams = ffprobe_streams(result.mp4_path)
    v = next(s for s in streams if s["codec_type"] == "video")
    num, den = (int(x) for x in v["avg_frame_rate"].split("/"))
    actual_fps = num / den
    assert abs(actual_fps - FPS) < 0.5, f"fps={actual_fps}, expected {FPS}"


# ── INV-4: video duration ≈ totalFrames / fps (±300ms) ───────────────────────
def test_inv4_video_duration_within_300ms_of_expected(compose_inputs, tmp_path):
    frames_dir, audio_path, pad = compose_inputs
    out_dir = tmp_path / "out"
    result = compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
    )
    expected = NUM_FRAMES / FPS
    actual = ffprobe_duration_s(result.mp4_path)
    assert abs(actual - expected) <= 0.3, f"duration {actual}s vs expected {expected}s (±0.3s)"


# ── INV-5: soft subtitles produce mov_text stream ────────────────────────────
def test_inv5_soft_subtitles_produce_mov_text_stream(compose_inputs, tmp_path):
    frames_dir, audio_path, pad = compose_inputs
    srt = tmp_path / "subs.srt"
    make_srt(srt)
    out_dir = tmp_path / "out"
    result = compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
        subtitles_srt=srt,
    )
    streams = ffprobe_streams(result.mp4_path)
    subs = [s for s in streams if s["codec_type"] == "subtitle"]
    assert len(subs) == 1, f"expected 1 subtitle stream, got {len(subs)}"
    assert subs[0]["codec_name"] == "mov_text"
    assert result.has_subtitle_stream is True


# ── INV-6: faststart layout — moov atom in first 512KB ───────────────────────
def test_inv6_faststart_moov_atom_at_front(compose_inputs, tmp_path):
    """Mutation kill: forgot +faststart → moov at end, web streaming breaks."""
    frames_dir, audio_path, pad = compose_inputs
    out_dir = tmp_path / "out"
    result = compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
    )
    head = result.mp4_path.read_bytes()[: 512 * 1024]
    assert b"moov" in head, "moov atom not in first 512KB — +faststart missing?"


# ── INV-7: missing frames_dir → FileNotFoundError ────────────────────────────
def test_inv7_missing_frames_dir_raises_fnf(compose_inputs, tmp_path):
    _, audio_path, pad = compose_inputs
    out_dir = tmp_path / "out"
    with pytest.raises(FileNotFoundError):
        compose_final(
            frames_dir=tmp_path / "nonexistent",
            audio_path=audio_path,
            out_dir=out_dir,
            fps=FPS,
            pad_width=pad,
        )


# ── INV-8: missing audio_path → FileNotFoundError ────────────────────────────
def test_inv8_missing_audio_path_raises_fnf(compose_inputs, tmp_path):
    frames_dir, _, pad = compose_inputs
    out_dir = tmp_path / "out"
    with pytest.raises(FileNotFoundError):
        compose_final(
            frames_dir=frames_dir,
            audio_path=tmp_path / "nope.m4a",
            out_dir=out_dir,
            fps=FPS,
            pad_width=pad,
        )


# ── INV-9: does not modify input files ───────────────────────────────────────
def test_inv9_does_not_modify_inputs(compose_inputs, tmp_path):
    """Mutation kill: composer shouldn't write to frames dir or audio path."""
    frames_dir, audio_path, pad = compose_inputs
    frames_before = {p.name: p.stat().st_size for p in frames_dir.iterdir()}
    audio_before = audio_path.stat().st_size

    out_dir = tmp_path / "out"
    compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
    )

    frames_after = {p.name: p.stat().st_size for p in frames_dir.iterdir()}
    assert frames_after == frames_before, "frames dir was modified"
    assert audio_path.stat().st_size == audio_before, "audio_path was modified"


# ── INV-10: result.duration_seconds matches ffprobe duration ─────────────────
def test_inv10_result_duration_matches_ffprobe(compose_inputs, tmp_path):
    frames_dir, audio_path, pad = compose_inputs
    out_dir = tmp_path / "out"
    result = compose_final(
        frames_dir=frames_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        fps=FPS,
        pad_width=pad,
    )
    measured = ffprobe_duration_s(result.mp4_path)
    assert abs(result.duration_seconds - measured) <= 0.05, (
        f"result.duration_seconds={result.duration_seconds} != ffprobe {measured}"
    )


# ── INV-11: burn-in raises SkippableError if libass missing ──────────────────
def test_inv11_burnin_skippable_when_libass_missing(compose_inputs, tmp_path):
    """Conditional: if local ffmpeg has libass, this test verifies success;
    if missing, it verifies SkippableError. Either is acceptable per contract."""
    frames_dir, audio_path, pad = compose_inputs
    srt = tmp_path / "subs.srt"
    make_srt(srt)
    out_dir = tmp_path / "out"

    has_libass = False
    try:
        probe = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True,
            text=True,
            check=True,
        )
        has_libass = "subtitles" in probe.stdout
    except subprocess.CalledProcessError:
        pass

    if has_libass:
        # Should succeed with burnin
        result = compose_final(
            frames_dir=frames_dir,
            audio_path=audio_path,
            out_dir=out_dir,
            fps=FPS,
            pad_width=pad,
            subtitles_srt=srt,
            burnin=True,
        )
        assert isinstance(result, ComposeResult)
    else:
        # Should raise SkippableError
        with pytest.raises((SkippableError, RuntimeError)):
            compose_final(
                frames_dir=frames_dir,
                audio_path=audio_path,
                out_dir=out_dir,
                fps=FPS,
                pad_width=pad,
                subtitles_srt=srt,
                burnin=True,
            )
