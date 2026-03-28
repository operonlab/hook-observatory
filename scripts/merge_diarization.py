#!/usr/bin/env python3
"""Merge speaker diarization with whisper transcription.

Thin wrapper around audio_ops.merge — core logic lives in
libs/audio-ops/audio_ops/merge.py for shared use across stations and skills.

Re-runs whisper on chunk WAVs to get timestamped segments, then assigns
each segment a speaker based on diarization time overlap.

Usage:
    ~/.local/bin/python3 scripts/merge_diarization.py <data_dir>

Expects:
    <data_dir>/diarization.json     — [{start, end, speaker, duration}]
    <data_dir>/chunks/chunk_NNNN.wav — audio chunks (NNNN = start second)

Produces:
    <data_dir>/transcript_diarized.json — [{start, end, speaker, text}]
    <data_dir>/transcript_diarized.md   — readable markdown
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from audio_ops.merge import MergeOp

WHISPER = os.path.expanduser("~/.local/bin/mlx_whisper")


def run_whisper_on_chunk(wav_path: Path, output_dir: Path) -> Path:
    """Run mlx_whisper on a chunk WAV, return path to JSON output."""
    json_out = output_dir / (wav_path.stem + ".json")
    if json_out.exists():
        print(f"  [cached] {json_out.name}")
        return json_out

    print(f"  [whisper] {wav_path.name} ...")
    subprocess.run(
        [
            WHISPER,
            "--model",
            "mlx-community/whisper-large-v3-turbo",
            "--language",
            "zh",
            "--output-dir",
            str(output_dir),
            "--output-format",
            "json",
            "--condition-on-previous-text",
            "False",
            "--hallucination-silence-threshold",
            "1",
            str(wav_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json_out


def parse_chunk_offset(wav_path: Path) -> float:
    """Extract start-second offset from chunk filename like chunk_0600.wav."""
    m = re.search(r"chunk_(\d+)", wav_path.stem)
    if not m:
        raise ValueError(f"Cannot parse offset from {wav_path.name}")
    return float(m.group(1))


def main():
    parser = argparse.ArgumentParser(
        description="Merge speaker diarization with whisper transcription"
    )
    parser.add_argument("data_dir", help="Directory with diarization.json and chunks/")
    parser.add_argument(
        "--skip-whisper",
        action="store_true",
        help="Skip whisper re-run, use existing JSON files",
    )
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=2.0,
        help="Max gap (seconds) for consolidating same-speaker segments",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    chunks_dir = data_dir / "chunks"
    diarization_path = data_dir / "diarization.json"

    if not diarization_path.exists():
        print(f"Error: {diarization_path} not found", file=sys.stderr)
        sys.exit(1)
    if not chunks_dir.exists():
        print(f"Error: {chunks_dir} not found", file=sys.stderr)
        sys.exit(1)

    # Find chunk WAVs
    wav_files = sorted(chunks_dir.glob("chunk_*.wav"))
    if not wav_files:
        print("Error: No chunk_*.wav files found", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(wav_files)} chunks, loading diarization...")
    with open(diarization_path) as f:
        diarization = json.load(f)
    diarization = sorted(diarization, key=lambda s: s["start"])
    print(f"Loaded {len(diarization)} diarization segments")

    # Step 1: Run whisper on each chunk to get timestamped JSON
    print("\n== Step 1: Whisper transcription ==")
    all_segments = []

    for wav_path in wav_files:
        offset = parse_chunk_offset(wav_path)

        if not args.skip_whisper:
            json_path = run_whisper_on_chunk(wav_path, chunks_dir)
        else:
            json_path = chunks_dir / (wav_path.stem + ".json")
            if not json_path.exists():
                print(f"  [skip] {json_path.name} not found, skipping")
                continue

        with open(json_path) as f:
            whisper_out = json.load(f)

        segments = whisper_out.get("segments", [])
        for seg in segments:
            text = seg["text"].strip()
            if not text:
                continue
            all_segments.append(
                {
                    "start": round(seg["start"] + offset, 3),
                    "end": round(seg["end"] + offset, 3),
                    "text": text,
                }
            )

    all_segments.sort(key=lambda s: s["start"])
    print(f"\nTotal whisper segments: {len(all_segments)}")

    # Step 2-3: Merge using audio_ops.merge
    print("\n== Step 2-3: Speaker assignment + consolidation ==")
    merge_op = MergeOp(gap_threshold=args.gap_threshold)
    ctx = {
        "diarization_segments": diarization,
        "transcription_segments": all_segments,
    }
    ctx = merge_op(ctx)

    consolidated = ctx["attributed_segments"]
    print(f"Result: {len(all_segments)} → {len(consolidated)} segments")

    # Step 4: Output
    json_out = data_dir / "transcript_diarized.json"
    md_out = data_dir / "transcript_diarized.md"

    with open(json_out, "w") as f:
        json.dump(consolidated, f, indent=2, ensure_ascii=False)
    print(f"\nJSON: {json_out}")

    with open(md_out, "w") as f:
        f.write(ctx["attributed_markdown"])
    print(f"Markdown: {md_out}")
    print("\nDone!")


if __name__ == "__main__":
    main()
