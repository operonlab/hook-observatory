"""Subtitle builder operator — generate SRT / VTT from narrations + durations.

Pure function logic, zero IO (file reading/writing is the caller's concern).

Usage:
    from video_ops.subtitle_builder import build_subtitles, SubtitleResult

    result = build_subtitles(
        narrations={"intro": ["Hello", "", "World"]},
        durations={"intro": [2000, 1500, 3000]},
    )
    print(result.srt)        # full SRT content
    print(result.vtt)        # full VTT content (starts with "WEBVTT")
    print(result.cue_count)  # 2 (empty narration skipped)
    print(result.total_ms)   # 6500 (all durations accumulated)

CLI:
    python -m video_ops.subtitle_builder \\
        --narrations narrations.json \\
        --durations durations.json \\
        --out ./dist-video

Invariants (from CONTRACTS.md §2):
    INV-1  cue[i].start = sum of durations for steps 0..i-1
    INV-2  cue[i].end == cue[i+1].start (no gap, no overlap)
    INV-3  empty/whitespace narration skips cue BUT still advances timeline
    INV-4  SRT: comma between seconds and milliseconds ("HH:MM:SS,mmm")
    INV-5  VTT: first line "WEBVTT", dot between seconds and ms
    INV-6  SRT cue N starts from 1, strictly increasing
    INV-7  total_ms = sum of all step durations (including empty-narration steps)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Dataclass ─────────────────────────────────────────────────────────────


@dataclass
class SubtitleResult:
    """Result of :func:`build_subtitles`."""

    srt: str
    """Full SRT content (cues separated by blank lines)."""

    vtt: str
    """Full VTT content (starts with 'WEBVTT\\n')."""

    cue_count: int
    """Number of subtitle cues generated (empty narrations excluded)."""

    total_ms: int
    """Cumulative duration of ALL steps, including empty-narration ones (ms)."""

    chapter_order: list[str] = field(default_factory=list)
    """Chapter IDs in the order they were processed."""


# ── Time formatting ────────────────────────────────────────────────────────


def _pad(n: int, width: int) -> str:
    return str(n).zfill(width)


def _ms_to_srt(ms: int) -> str:
    """Format milliseconds as SRT timestamp ``HH:MM:SS,mmm``."""
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1_000
    millis = ms % 1_000
    return f"{_pad(h, 2)}:{_pad(m, 2)}:{_pad(s, 2)},{_pad(millis, 3)}"


def _ms_to_vtt(ms: int) -> str:
    """Format milliseconds as VTT timestamp ``HH:MM:SS.mmm``."""
    return _ms_to_srt(ms).replace(",", ".")


# ── Core pure function ─────────────────────────────────────────────────────


def build_subtitles(
    narrations: dict[str, list[str]],
    durations: dict[str, list[int]],
    *,
    chapter_order: list[str] | None = None,
) -> SubtitleResult:
    """Build SRT and VTT subtitle content from narrations and step durations.

    Parameters
    ----------
    narrations:
        Mapping from chapter_id to list of narration strings.
        Empty strings or whitespace-only strings are skipped as cues
        but their corresponding duration is still accumulated.
    durations:
        Mapping from chapter_id to list of step durations in milliseconds.
        If a chapter is missing, each step defaults to 1500 ms.
    chapter_order:
        Optional explicit ordering of chapter IDs.  When omitted, chapters
        are processed in the order they appear in ``narrations``.

    Returns
    -------
    SubtitleResult
        Immutable dataclass carrying the SRT text, VTT text, cue count,
        and total accumulated duration in ms.

    Invariants
    ----------
    * Empty narrations skip cue generation but still advance the cursor.
    * cue[i].end == cue[i+1].start (no gap, no overlap).
    * SRT cue indices start at 1 and increase strictly.
    * SRT uses comma (``HH:MM:SS,mmm``); VTT uses dot (``HH:MM:SS.mmm``).
    * VTT first line is ``WEBVTT``.
    * ``total_ms`` equals the sum of *all* step durations across all chapters.
    """
    order = chapter_order if chapter_order is not None else list(narrations.keys())

    srt_parts: list[str] = []
    vtt_parts: list[str] = ["WEBVTT", ""]

    cursor_ms = 0
    cue_num = 0

    for chapter_id in order:
        narr = narrations.get(chapter_id, [])
        dur = durations.get(chapter_id, [])

        for i, text in enumerate(narr):
            step_ms: int = dur[i] if i < len(dur) else 1500
            start_ms = cursor_ms
            end_ms = cursor_ms + step_ms
            cursor_ms = end_ms  # always advance (INV-3)

            if not text or not text.strip():
                continue  # skip cue, but cursor already advanced

            cue_num += 1  # INV-6: 1-indexed, strictly increasing

            srt_timing = f"{_ms_to_srt(start_ms)} --> {_ms_to_srt(end_ms)}"
            vtt_timing = f"{_ms_to_vtt(start_ms)} --> {_ms_to_vtt(end_ms)}"

            # SRT block: index \n timing \n text \n (blank-line separator added below)
            srt_parts.append(f"{cue_num}\n{srt_timing}\n{text}\n")

            # VTT block: timing \n text \n
            vtt_parts.append(f"{vtt_timing}\n{text}\n")

    srt_content = "\n".join(srt_parts)  # blank line between cues
    vtt_content = "\n".join(vtt_parts)  # blank line between cues

    logger.info(
        "build_subtitles: %d chapters, %d cues, total %.1fs",
        len(order),
        cue_num,
        cursor_ms / 1000,
    )

    return SubtitleResult(
        srt=srt_content,
        vtt=vtt_content,
        cue_count=cue_num,
        total_ms=cursor_ms,
        chapter_order=order,
    )


# ── CLI entry point ────────────────────────────────────────────────────────


def _cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m video_ops.subtitle_builder",
        description="Generate SRT + VTT from narrations JSON + durations JSON.",
    )
    parser.add_argument(
        "--narrations",
        required=True,
        metavar="PATH",
        help="JSON file: { chapter_id: [str, ...] }",
    )
    parser.add_argument(
        "--durations",
        required=True,
        metavar="PATH",
        help="JSON file: { chapter_id: [ms, ...] }",
    )
    parser.add_argument(
        "--out",
        default="./dist-video",
        metavar="DIR",
        help="Output directory (default: ./dist-video)",
    )
    parser.add_argument(
        "--chapter-order",
        default=None,
        metavar="COMMA_LIST",
        help="Explicit chapter order, comma-separated IDs",
    )
    args = parser.parse_args(argv)

    narrations_path = Path(args.narrations)
    durations_path = Path(args.durations)
    out_dir = Path(args.out)

    if not narrations_path.exists():
        print(f"✗ {narrations_path} not found", file=sys.stderr)
        return 2
    if not durations_path.exists():
        print(f"✗ {durations_path} not found", file=sys.stderr)
        return 2

    narrations: dict[str, list[str]] = json.loads(narrations_path.read_text())
    durations: dict[str, list[int]] = json.loads(durations_path.read_text())
    chapter_order = (
        [c.strip() for c in args.chapter_order.split(",")] if args.chapter_order else None
    )

    result = build_subtitles(narrations, durations, chapter_order=chapter_order)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "subtitles.srt").write_text(result.srt, encoding="utf-8")
    (out_dir / "subtitles.vtt").write_text(result.vtt, encoding="utf-8")

    print(
        f"✓ {result.cue_count} cues, total {result.total_ms / 1000:.1f}s "
        f"→ {out_dir / 'subtitles.srt'} + .vtt",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    sys.exit(_cli_main())
