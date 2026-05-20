"""Microsoft Edge TTS engine — free cloud neural voices via edge-tts CLI.

Uses the `edge-tts` command-line tool (Python package, install with
`uv pip install edge-tts` or similar) which streams from Microsoft's
public Azure endpoint. Excellent quality, zero local compute, no API key.

This engine is the default for the hook voice_notify pipeline: it's what
the legacy Python `voice_notify.py` actually used in practice (its
`/api/tts/speak` URL was broken and silently fell through to edge-tts).
Encapsulating it here moves edge-tts behind the single `stations/tts`
entry point, so the Go hook dispatcher only has to call `/synthesize`.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import register

DEFAULT_VOICE = "zh-CN-YunjianNeural"  # matches voice_notify.py

# Polyphone fixes — zh-CN neural voices pick the high-frequency reading and
# stumble on context-specific ones. Substitute a same-sound character so the
# acoustic model has no ambiguity. Keys are Traditional and applied BEFORE
# t2s, so one dict covers both Traditional and Simplified inputs.
_PHONETIC_FIXES = {
    "少爺": "紹爺",  # 少 ㄕㄠˋ vs ㄕㄠˇ — 紹/shao4 同音
}


def _apply_phonetic_fixes(text: str) -> str:
    for src, dst in _PHONETIC_FIXES.items():
        if src in text:
            text = text.replace(src, dst)
    return text


def _speed_to_rate(speed: float) -> str:
    """Convert float speed multiplier (1.0 = normal) to edge-tts rate string.

    edge-tts expects strings like ``+20%`` / ``-10%`` / ``+0%``.
    """
    try:
        pct = int(round((float(speed) - 1.0) * 100))
    except (TypeError, ValueError):
        pct = 0
    sign = "+" if pct >= 0 else "-"
    return f"{sign}{abs(pct)}%"


@register("edge")
class EdgeTTSEngine:
    """Microsoft Edge Neural TTS — subprocess bridge to the edge-tts CLI."""

    name = "edge"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        binary = shutil.which("edge-tts")
        if not binary:
            return {
                "error": "edge-tts CLI not found on PATH (install via `uv pip install edge-tts`)",
                "engine": "edge",
            }

        if not text or not text.strip():
            return {"error": "empty text", "engine": "edge"}

        if voice in (None, "", "default"):
            voice = DEFAULT_VOICE

        # Mainland zh-CN voices pronounce Traditional Chinese characters with
        # PRC readings but stumble on Taiwan-specific vocabulary (e.g. 資訊 →
        # 信息). Convert to Simplified so the pronunciation model and the
        # written form agree. zh-TW voices are trained on Traditional and
        # stay as-is.
        if voice.startswith("zh-CN-"):
            from . import to_simplified

            text = _apply_phonetic_fixes(text)
            text = to_simplified(text)

        if output_path is None:
            output_path = tempfile.mktemp(prefix="tts_edge_", suffix=".mp3")

        rate = _speed_to_rate(speed)

        cmd = [
            binary,
            "--voice",
            voice,
            "--rate",
            rate,
            "--text",
            text,
            "--write-media",
            output_path,
        ]

        t0 = time.monotonic()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"error": f"edge-tts failed: {e}", "engine": "edge"}
        elapsed = time.monotonic() - t0

        if result.returncode != 0:
            stderr = result.stderr.strip() or f"exit {result.returncode}"
            return {"error": f"edge-tts failed: {stderr}", "engine": "edge"}

        out = Path(output_path)
        if not out.exists() or out.stat().st_size == 0:
            return {"error": "edge-tts produced empty file", "engine": "edge"}

        # Best-effort duration — use mutagen if available, otherwise 0.0.
        duration = 0.0
        try:
            import mutagen  # type: ignore

            f = mutagen.File(str(out))
            if f is not None and getattr(f, "info", None) is not None:
                duration = float(getattr(f.info, "length", 0.0) or 0.0)
        except Exception:
            pass

        return {
            "audio_path": str(out),
            "duration": round(duration, 4),
            "sample_rate": 24000,  # edge-tts defaults to 24 kHz mono MP3
            "engine": "edge",
            "synthesis_ms": int(elapsed * 1000),
            "voice": voice,
            "rate": rate,
        }

    def list_voices(self) -> list[dict]:
        """Return a curated subset of Chinese voices.

        edge-tts exposes 1400+ voices via `edge-tts --list-voices`; surfacing
        them all here would be noisy. For full discovery, run the CLI
        directly. The list below covers the voices voice_notify has used
        historically plus a few common zh-TW / zh-CN alternatives.
        """
        return [
            {"id": "zh-CN-YunjianNeural", "name": "Yunjian", "language": "zh-CN"},
            {"id": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao", "language": "zh-CN"},
            {"id": "zh-CN-YunyangNeural", "name": "Yunyang", "language": "zh-CN"},
            {"id": "zh-CN-YunxiNeural", "name": "Yunxi", "language": "zh-CN"},
            {"id": "zh-CN-XiaoyiNeural", "name": "Xiaoyi", "language": "zh-CN"},
            {"id": "zh-TW-HsiaoChenNeural", "name": "HsiaoChen", "language": "zh-TW"},
            {"id": "zh-TW-YunJheNeural", "name": "YunJhe", "language": "zh-TW"},
            {"id": "zh-TW-HsiaoYuNeural", "name": "HsiaoYu", "language": "zh-TW"},
        ]
