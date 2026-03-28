"""Transcript merge operator — combine diarization with transcription segments.

Standalone functions + MergeOp class conforming to AudioOp Protocol.

Usage:
    from audio_ops.merge import MergeOp, find_speaker, consolidate_segments

    # As operator in pipeline
    op = MergeOp(gap_threshold=2.0)
    ctx = op({"diarization_segments": [...], "transcription_segments": [...]})

    # As standalone functions
    speaker = find_speaker(1.0, 3.0, diarization_segments)
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


def find_speaker(seg_start: float, seg_end: float, diarization: list[dict]) -> str:
    """Find speaker with maximum time overlap for a transcript segment.

    Assumes diarization is sorted by start time (early-exit optimized).
    """
    best_speaker = "UNKNOWN"
    best_overlap = 0.0

    for d in diarization:
        if d["start"] > seg_end:
            break
        if d["end"] < seg_start:
            continue

        overlap = max(0, min(seg_end, d["end"]) - max(seg_start, d["start"]))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = d["speaker"]

    return best_speaker


def consolidate_segments(
    segments: list[dict], gap_threshold: float = 2.0
) -> list[dict]:
    """Merge consecutive segments from same speaker with gap < threshold."""
    if not segments:
        return []

    consolidated = []
    for seg in segments:
        if (
            consolidated
            and consolidated[-1]["speaker"] == seg["speaker"]
            and seg["start"] - consolidated[-1]["end"] < gap_threshold
        ):
            consolidated[-1]["end"] = seg["end"]
            consolidated[-1]["text"] += seg["text"]
        else:
            consolidated.append(dict(seg))
    return consolidated


def format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def to_markdown(segments: list[dict]) -> str:
    """Render attributed segments as readable markdown."""
    lines = ["# Diarized Transcript\n"]

    # Speaker summary
    speaker_durations: dict[str, float] = {}
    for seg in segments:
        dur = seg["end"] - seg["start"]
        speaker_durations[seg["speaker"]] = (
            speaker_durations.get(seg["speaker"], 0) + dur
        )
    total_dur = sum(speaker_durations.values())

    lines.append("## Speakers\n")
    for spk, dur in sorted(speaker_durations.items(), key=lambda x: -x[1]):
        pct = dur / total_dur * 100 if total_dur > 0 else 0
        lines.append(f"- **{spk}**: {format_time(dur)} ({pct:.1f}%)")
    lines.append("\n---\n")

    # Transcript body
    lines.append("## Transcript\n")
    current_speaker = None
    for seg in segments:
        if seg["speaker"] != current_speaker:
            current_speaker = seg["speaker"]
            lines.append(f"\n### {current_speaker} [{format_time(seg['start'])}]\n")
        lines.append(f"{seg['text']}\n")

    return "\n".join(lines)


@register("merge")
class MergeOp:
    """Merge diarization segments with transcription segments.

    Input:
        ctx["diarization_segments"] — [{start, end, speaker, duration}] (sorted by start)
        ctx["transcription_segments"] — [{start, end, text}]
    Output:
        ctx["attributed_segments"] — [{start, end, speaker, text}] (consolidated)
        ctx["attributed_markdown"] — readable markdown string
    """

    name = "merge"
    input_keys = ("diarization_segments", "transcription_segments")
    output_keys = ("attributed_segments", "attributed_markdown")

    def __init__(self, gap_threshold: float = 2.0):
        self._gap_threshold = gap_threshold

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        diarization = sorted(ctx["diarization_segments"], key=lambda s: s["start"])
        transcription = sorted(
            ctx["transcription_segments"], key=lambda s: s["start"]
        )

        # Assign speakers to each transcription segment
        attributed = []
        for seg in transcription:
            text = seg.get("text", "").strip()
            if not text:
                continue
            speaker = find_speaker(seg["start"], seg["end"], diarization)
            attributed.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "speaker": speaker,
                    "text": text,
                }
            )

        consolidated = consolidate_segments(attributed, self._gap_threshold)

        ctx["attributed_segments"] = consolidated
        ctx["attributed_markdown"] = to_markdown(consolidated)

        logger.info(
            "Merge: %d transcription + %d diarization -> %d attributed (%d consolidated)",
            len(transcription),
            len(diarization),
            len(attributed),
            len(consolidated),
        )
        return ctx
