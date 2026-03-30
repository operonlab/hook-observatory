#!/usr/bin/env python3
"""Speaker diarization using pyannote.audio on Apple Silicon (MPS).

This script is the subprocess target for audio_ops.diarize.DiarizeOp.
It must be runnable standalone via ~/.venvs/diarize/bin/python3.

Usage:
    ~/.venvs/diarize/bin/python3 scripts/diarize_audio.py <audio_path> [--output <json_path>]

Requires:
    - ~/.venvs/diarize/ venv with pyannote-audio, torch, torchaudio
    - HF token at ~/.cache/huggingface/token
    - Accepted licenses: pyannote/speaker-diarization-3.1, pyannote/segmentation-3.0,
      pyannote/speaker-diarization-community-1
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Speaker diarization with pyannote.audio")
    parser.add_argument("audio", help="Path to audio file (WAV, 16kHz mono recommended)")
    parser.add_argument(
        "--output", "-o", help="Output JSON path (default: <audio_dir>/diarization.json)"
    )
    parser.add_argument(
        "--device", default="auto", choices=["auto", "mps", "cpu"], help="Compute device"
    )
    args = parser.parse_args()

    audio_path = Path(args.audio).resolve()
    if not audio_path.exists():
        print(f"Error: {audio_path} not found", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else audio_path.parent / "diarization.json"

    # Load HF token
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if token_path.exists():
        os.environ["HF_TOKEN"] = token_path.read_text().strip()
    else:
        print("Error: No HuggingFace token at ~/.cache/huggingface/token", file=sys.stderr)
        sys.exit(1)

    import torch
    import torchaudio
    from pyannote.audio import Pipeline

    # Device selection
    if args.device == "auto":
        device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    else:
        device = torch.device(args.device)

    print("Loading pyannote pipeline...")
    t0 = time.time()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    pipeline.to(device)
    print(f"Loaded on {device} in {time.time() - t0:.1f}s")

    # Pre-load audio with torchaudio (bypasses torchcodec issues)
    print(f"Loading audio: {audio_path}")
    waveform, sr = torchaudio.load(str(audio_path))
    duration_min = waveform.shape[1] / sr / 60
    print(f"Audio: {duration_min:.1f}min, {sr}Hz, {waveform.shape[0]}ch")

    print("Diarizing...")
    t1 = time.time()
    result = pipeline({"waveform": waveform, "sample_rate": sr})
    elapsed = time.time() - t1
    print(f"Done in {elapsed:.1f}s ({elapsed / 60:.1f}min)")

    # Extract segments from result
    ann = result.speaker_diarization

    output = []
    for turn, _, speaker in ann.itertracks(yield_label=True):
        output.append(
            {
                "start": round(turn.start, 3),
                "end": round(turn.end, 3),
                "speaker": speaker,
                "duration": round(turn.end - turn.start, 3),
            }
        )

    # Save JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Print stats
    speakers = {}
    for seg in output:
        speakers[seg["speaker"]] = speakers.get(seg["speaker"], 0) + seg["duration"]

    total = sum(speakers.values())
    print(f"\nSegments: {len(output)} | Speakers: {len(speakers)}")
    print(f"Output: {output_path}")
    for spk, dur in sorted(speakers.items(), key=lambda x: -x[1]):
        print(f"  {spk}: {dur / 60:.1f}min ({dur / total * 100:.1f}%)")


if __name__ == "__main__":
    main()
