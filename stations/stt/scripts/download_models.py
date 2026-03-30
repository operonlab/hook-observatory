#!/usr/bin/env python3
"""Download sherpa-onnx models for STT operators."""

from __future__ import annotations

import tarfile
from pathlib import Path
from urllib.request import urlretrieve

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

MODELS = {
    "silero_vad": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
        "type": "file",
        "target": "silero_vad.onnx",
    },
    "gtcrn_denoise": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx",
        "type": "file",
        "target": "gtcrn_simple.onnx",
    },
}


def _progress(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb = downloaded / 1024 / 1024
        print(f"\r  {pct}% ({mb:.1f} MB)", end="", flush=True)


def download_all() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for name, info in MODELS.items():
        target = MODELS_DIR / info["target"]
        if target.exists():
            print(f"[skip] {name}: {target} already exists")
            continue

        print(f"[download] {name}: {info['url']}")
        if info["type"] == "file":
            urlretrieve(info["url"], str(target), _progress)
            print()
        elif info["type"] == "tar":
            archive = MODELS_DIR / f"{name}.tar.bz2"
            urlretrieve(info["url"], str(archive), _progress)
            print()
            print(f"  Extracting {archive.name}...")
            with tarfile.open(str(archive), "r:bz2") as tf:
                tf.extractall(path=str(MODELS_DIR))
            archive.unlink()

        print(f"  -> {target}")

    print("\nAll models ready.")


if __name__ == "__main__":
    download_all()
