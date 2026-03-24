#!/usr/bin/env python3
"""Download sherpa-onnx models for voice-gateway."""

from __future__ import annotations

import subprocess
import sys
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
    "kws_zipformer_zh_en": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2",
        "type": "tar",
        "target": "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01",
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
            print(f"✓ {name}: already exists at {target}")
            continue

        print(f"↓ {name}: downloading from {info['url']}")

        if info["type"] == "file":
            urlretrieve(info["url"], target, reporthook=_progress)
            print()
        elif info["type"] == "tar":
            archive_path = MODELS_DIR / f"{name}.tar.bz2"
            urlretrieve(info["url"], archive_path, reporthook=_progress)
            print("\n  extracting...")
            with tarfile.open(archive_path, "r:bz2") as tf:
                tf.extractall(MODELS_DIR)
            archive_path.unlink()

        print(f"  ✓ {name}: ready")

    print("\nAll models downloaded.")


if __name__ == "__main__":
    download_all()
