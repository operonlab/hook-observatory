"""Auto-routing: lang → engine, with fallback chain.

對應 INTEGRATION-PLAN.md §2「Auto-Routing 策略」：
- IndexTTS-2 base 中英；jmica 只接日語（fine-tune 後中英已 catastrophic forgetting）
- cosyvoice_v3_vllm RTF 0.43 為英文快速首選
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

_MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"

DEFAULTS = {
    "zh": "indextts2_base",     # 少爺偏好（中文勝 CosyVoice）
    "en": "indextts2_base",     # 少爺指令 2026-05-19：中英都用 indextts-2
    "ja": "indextts2_jmica",    # 少爺偏好（日語 fine-tune）
    "multi_speaker": "vibevoice",
    "fast_batch": "cosyvoice_v3_vllm",  # 仍保留快速批次入口
}

# CosyVoice / Qwen3TTS 全部降為 fallback，前面只有 indextts2 + vibevoice
FALLBACK_CHAIN = {
    "zh": ["indextts2_base", "cosyvoice_v3_vllm", "cosyvoice_v3_native", "qwen3tts_gpu"],
    "en": ["indextts2_base", "cosyvoice_v3_vllm", "cosyvoice_v3_native", "qwen3tts_gpu"],
    "ja": ["indextts2_jmica", "cosyvoice_v3_vllm", "cosyvoice_v3_native", "qwen3tts_gpu"],
    "ko": ["qwen3tts_gpu"],  # 唯一支援 ko
}


def _load_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        return {}
    with _MANIFEST_PATH.open() as f:
        return yaml.safe_load(f) or {}


def pick_engine(
    lang: str,
    available: Iterable[str] | None = None,
    multi_speaker: bool = False,
    prefer_fast: bool = False,
) -> str:
    """Pick best engine for (lang, requirements). Falls through chain.

    Args:
        lang: ISO code "zh"|"en"|"ja"|"ko"
        available: registered engine names (None → use all known)
        multi_speaker: True → force vibevoice
        prefer_fast: True → prefer cosyvoice_v3_vllm regardless of lang

    Returns:
        engine name (str)
    """
    if multi_speaker:
        return DEFAULTS["multi_speaker"]
    if prefer_fast:
        return DEFAULTS["fast_batch"]

    chain = FALLBACK_CHAIN.get(lang, [])
    if not chain:
        # Unknown lang → fallback to en chain
        chain = FALLBACK_CHAIN["en"]

    if available is None:
        return chain[0]

    avail = set(available)
    for candidate in chain:
        if candidate in avail:
            return candidate

    # Last resort: anything available
    if avail:
        return next(iter(avail))
    raise RuntimeError(f"No engine available for lang={lang}")


def explain_route(lang: str, multi_speaker: bool = False, prefer_fast: bool = False) -> dict:
    """For /v2/route debug endpoint."""
    return {
        "lang": lang,
        "primary": pick_engine(lang, multi_speaker=multi_speaker, prefer_fast=prefer_fast),
        "fallback_chain": FALLBACK_CHAIN.get(lang, []),
        "multi_speaker_requested": multi_speaker,
        "prefer_fast": prefer_fast,
    }
