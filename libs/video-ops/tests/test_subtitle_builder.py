"""Invariant tests for video_ops.subtitle_builder.

Mirrors the contract spec in CONTRACTS.md §2, translated from the Node.js
build-subtitles.test.mjs to Python/pytest.

All tests are pure-function (zero IO) — no ffmpeg, no filesystem.
"""

from __future__ import annotations

import re

import pytest

from video_ops.subtitle_builder import SubtitleResult, build_subtitles

# ── Fixtures & helpers ─────────────────────────────────────────────────────

KNOWN_NARRATIONS = {"example": ["Hello world", "Second step", "Third step"]}
KNOWN_DURATIONS = {"example": [6750, 10250, 10250]}


def _parse_srt(content: str) -> list[dict]:
    """Parse SRT text → list of {index, start_ms, end_ms, text}."""
    blocks = [b.strip() for b in re.split(r"\n\n+", content.strip()) if b.strip()]
    cues = []
    for block in blocks:
        lines = block.split("\n")
        index = int(lines[0])
        timing = lines[1]
        start_str, end_str = timing.split(" --> ")
        cues.append(
            {
                "index": index,
                "start_ms": _srt_to_ms(start_str.strip()),
                "end_ms": _srt_to_ms(end_str.strip()),
                "text": "\n".join(lines[2:]),
            }
        )
    return cues


def _parse_vtt(content: str) -> list[dict]:
    """Parse VTT text → list of {start_ms, end_ms, text}."""
    lines = content.split("\n")
    cues = []
    i = 0
    while i < len(lines):
        if "-->" in lines[i]:
            start_str, end_str = lines[i].split(" --> ")
            texts = []
            i += 1
            while i < len(lines) and lines[i].strip():
                texts.append(lines[i])
                i += 1
            cues.append(
                {
                    "start_ms": _vtt_to_ms(start_str.strip()),
                    "end_ms": _vtt_to_ms(end_str.strip()),
                    "text": "\n".join(texts),
                }
            )
        else:
            i += 1
    return cues


def _srt_to_ms(ts: str) -> int:
    """'HH:MM:SS,mmm' → ms."""
    hms, millis = ts.split(",")
    h, m, s = hms.split(":")
    return int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1_000 + int(millis)


def _vtt_to_ms(ts: str) -> int:
    """'HH:MM:SS.mmm' → ms."""
    return _srt_to_ms(ts.replace(".", ","))


@pytest.fixture
def result_all_non_empty() -> SubtitleResult:
    return build_subtitles(KNOWN_NARRATIONS, KNOWN_DURATIONS)


# ── INV-1: cue start = cumulative duration sum ─────────────────────────────


def test_inv1_cue_start_equals_cumulative_sum(result_all_non_empty):
    """INV-1: cue[i].start_ms == sum of durations for steps 0..i-1."""
    cues = _parse_srt(result_all_non_empty.srt)
    dur = KNOWN_DURATIONS["example"]

    assert cues[0]["start_ms"] == 0
    assert cues[1]["start_ms"] == dur[0]  # 6750
    assert cues[2]["start_ms"] == dur[0] + dur[1]  # 17000


# ── INV-2: cue[i].end == cue[i+1].start (no gap, no overlap) ─────────────


def test_inv2_cue_end_equals_next_start(result_all_non_empty):
    """INV-2: cue[i].end_ms == cue[i+1].start_ms for all consecutive pairs."""
    cues = _parse_srt(result_all_non_empty.srt)
    for i in range(len(cues) - 1):
        assert cues[i]["end_ms"] == cues[i + 1]["start_ms"], (
            f"Gap/overlap between cue[{i}].end={cues[i]['end_ms']} "
            f"and cue[{i + 1}].start={cues[i + 1]['start_ms']}"
        )


def test_inv2b_each_cue_duration_matches_render_durations(result_all_non_empty):
    """INV-2b: cue[i].duration_ms == render-durations entry."""
    cues = _parse_srt(result_all_non_empty.srt)
    dur = KNOWN_DURATIONS["example"]
    for i, cue in enumerate(cues):
        actual = cue["end_ms"] - cue["start_ms"]
        assert actual == dur[i], f"cue[{i}] duration={actual}ms but expected {dur[i]}ms"


# ── INV-3: empty narration skips cue but advances timeline ────────────────


def test_inv3_empty_narration_skips_cue_but_advances_time():
    """INV-3: empty/whitespace narrations produce no cue but still consume time."""
    narrations = {"ch": ["First", "", "Third"]}
    durations = {"ch": [2000, 1500, 3000]}
    result = build_subtitles(narrations, durations)

    cues = _parse_srt(result.srt)
    # Only 2 cues (empty middle skipped)
    assert result.cue_count == 2
    assert len(cues) == 2

    # total_ms still covers ALL steps including the empty one
    assert result.total_ms == 2000 + 1500 + 3000

    # Third step's cue start = first + empty = 2000 + 1500 = 3500
    assert cues[1]["start_ms"] == 3500, (
        f"Second non-empty cue should start at 3500ms (after skipped step), "
        f"got {cues[1]['start_ms']}"
    )


def test_inv3_whitespace_only_also_skipped():
    """INV-3: whitespace-only narrations are treated as empty."""
    narrations = {"ch": ["Hello", "   ", "\t\n"]}
    durations = {"ch": [1000, 500, 500]}
    result = build_subtitles(narrations, durations)
    assert result.cue_count == 1
    assert result.total_ms == 2000


# ── INV-4: SRT timestamp uses comma, not dot ──────────────────────────────


def test_inv4_srt_timestamp_uses_comma(result_all_non_empty):
    """INV-4: SRT timing lines must use comma between seconds and milliseconds."""
    timing_lines = [line for line in result_all_non_empty.srt.split("\n") if "-->" in line]
    assert timing_lines, "No timing lines found in SRT"
    for line in timing_lines:
        assert "," in line, f"SRT timing line missing comma: {line}"
        # Verify the comma is in the correct place (before 3-digit ms)
        assert re.search(r"\d{2},\d{3}", line), f"Unexpected SRT format: {line}"


# ── INV-5: VTT starts with WEBVTT and uses dot separator ──────────────────


def test_inv5_vtt_starts_with_webvtt(result_all_non_empty):
    """INV-5: VTT first line is 'WEBVTT'."""
    first_line = result_all_non_empty.vtt.split("\n")[0].strip()
    assert first_line == "WEBVTT", f"VTT first line is '{first_line}', expected 'WEBVTT'"


def test_inv5_vtt_uses_dot_separator(result_all_non_empty):
    """INV-5: VTT timing lines must use dot (not comma) for sub-second separator."""
    timing_lines = [line for line in result_all_non_empty.vtt.split("\n") if "-->" in line]
    assert timing_lines, "No timing lines found in VTT"
    for line in timing_lines:
        assert "." in line, f"VTT timing line missing dot: {line}"
        assert "," not in line, f"VTT timing line has comma (SRT format): {line}"


# ── INV-6: SRT cue indices start from 1, strictly increasing ──────────────


def test_inv6_srt_cue_indices_start_from_1_strictly_increasing(result_all_non_empty):
    """INV-6: SRT cue N starts at 1 and increments by exactly 1."""
    cues = _parse_srt(result_all_non_empty.srt)
    assert cues[0]["index"] == 1, f"First cue index is {cues[0]['index']}, expected 1"
    for i in range(1, len(cues)):
        assert cues[i]["index"] == cues[i - 1]["index"] + 1, (
            f"cue[{i}].index={cues[i]['index']}, expected {cues[i - 1]['index'] + 1}"
        )


def test_inv6_indices_reset_across_chapters():
    """INV-6: cue indices are globally sequential, not per-chapter."""
    narrations = {"ch1": ["A", "B"], "ch2": ["C", "D"]}
    durations = {"ch1": [1000, 1000], "ch2": [1000, 1000]}
    result = build_subtitles(narrations, durations, chapter_order=["ch1", "ch2"])
    cues = _parse_srt(result.srt)
    assert [c["index"] for c in cues] == [1, 2, 3, 4]


# ── INV-7: total duration correctness ─────────────────────────────────────


def test_inv7_total_ms_equals_sum_of_all_durations(result_all_non_empty):
    """INV-7: total_ms == sum of ALL step durations (including empty steps)."""
    expected = sum(KNOWN_DURATIONS["example"])
    assert result_all_non_empty.total_ms == expected


def test_inv7_last_cue_end_le_total_sum(result_all_non_empty):
    """INV-7: last cue end_ms <= total duration sum."""
    cues = _parse_srt(result_all_non_empty.srt)
    total = sum(KNOWN_DURATIONS["example"])
    assert cues[-1]["end_ms"] <= total


def test_inv7_all_nonempty_last_cue_end_equals_total(result_all_non_empty):
    """INV-7: when all narrations non-empty, last cue end == total sum."""
    cues = _parse_srt(result_all_non_empty.srt)
    total = sum(KNOWN_DURATIONS["example"])
    assert cues[-1]["end_ms"] == total


# ── SRT / VTT consistency ─────────────────────────────────────────────────


def test_srt_vtt_timing_consistency(result_all_non_empty):
    """SRT and VTT must represent identical timing data."""
    srt_cues = _parse_srt(result_all_non_empty.srt)
    vtt_cues = _parse_vtt(result_all_non_empty.vtt)
    assert len(srt_cues) == len(vtt_cues), (
        f"SRT has {len(srt_cues)} cues but VTT has {len(vtt_cues)}"
    )
    for i, (s, v) in enumerate(zip(srt_cues, vtt_cues)):
        assert s["start_ms"] == v["start_ms"], (
            f"cue[{i}] start mismatch: SRT={s['start_ms']} VTT={v['start_ms']}"
        )
        assert s["end_ms"] == v["end_ms"], (
            f"cue[{i}] end mismatch: SRT={s['end_ms']} VTT={v['end_ms']}"
        )


# ── cue_count field ───────────────────────────────────────────────────────


def test_cue_count_matches_non_empty_narrations(result_all_non_empty):
    """SubtitleResult.cue_count equals the number of non-empty narrations."""
    assert result_all_non_empty.cue_count == 3


def test_cue_count_with_mixed_empty():
    """cue_count excludes empty/whitespace narrations."""
    narrations = {"ch": ["", "Hello", "", "World", ""]}
    durations = {"ch": [500, 1000, 500, 1000, 500]}
    result = build_subtitles(narrations, durations)
    assert result.cue_count == 2


# ── Multi-chapter ordering ────────────────────────────────────────────────


def test_multi_chapter_chapter_order_respected():
    """chapter_order kwarg controls iteration sequence."""
    narrations = {"b": ["B step"], "a": ["A step"]}
    durations = {"b": [1000], "a": [2000]}
    result = build_subtitles(narrations, durations, chapter_order=["a", "b"])
    cues = _parse_srt(result.srt)
    # 'a' processed first → cue[0].text = "A step", starts at 0
    assert cues[0]["text"] == "A step"
    assert cues[0]["start_ms"] == 0
    assert cues[1]["start_ms"] == 2000


# ── Fallback duration ─────────────────────────────────────────────────────


def test_missing_duration_entry_falls_back_to_1500():
    """When a step has no duration entry, 1500 ms is used as fallback."""
    narrations = {"ch": ["A", "B", "C"]}
    durations = {"ch": [1000]}  # only one entry for three steps
    result = build_subtitles(narrations, durations)
    assert result.total_ms == 1000 + 1500 + 1500
