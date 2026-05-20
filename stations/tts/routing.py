"""Auto-routing: lang → engine, with mode preset (quality / live).

2026-05-21 少爺 spec：兩條預設策略
  quality (default) — 最佳音質，indextts2 family
  live              — sub-realtime，cosyvoice_v3 family（RTF 0.5-0.8 hot）

實測 RTF 對比（hot, 2026-05-20 矩陣）：
  cosyvoice_v3_native ≈ 0.47-0.83   ← fastest
  vibevoice           ≈ 0.66-0.83
  qwen3tts_gpu        ≈ 1.08-1.21
  indextts2_base/jmica≈ 1.03（最終 ablation 後）
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

_MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"

PRESETS = {
    "quality": {
        "zh": "indextts2_base",
        "en": "indextts2_base",
        "ja": "indextts2_jmica",
        "ko": "qwen3tts_gpu",  # indextts 不支援 ko，退 qwen3
    },
    "live": {
        "zh": "cosyvoice_v3_native",
        "en": "cosyvoice_v3_native",
        "ja": "cosyvoice_v3_native",  # 用 pykakasi 片假名
        "ko": "qwen3tts_gpu",  # cosyvoice 不支援 ko
    },
}
DEFAULT_MODE = "quality"

# Legacy DEFAULTS kept for backward compat (some callers reference it)
DEFAULTS = {
    "zh": PRESETS["quality"]["zh"],
    "en": PRESETS["quality"]["en"],
    "ja": PRESETS["quality"]["ja"],
    "multi_speaker": "vibevoice",
    "fast_batch": "cosyvoice_v3_native",
}

# Fallback chain when primary not in available set.
FALLBACK_CHAIN = {
    "zh": ["indextts2_base", "cosyvoice_v3_native", "cosyvoice_v3_vllm", "qwen3tts_gpu"],
    "en": ["indextts2_base", "cosyvoice_v3_native", "cosyvoice_v3_vllm", "qwen3tts_gpu"],
    "ja": ["indextts2_jmica", "cosyvoice_v3_native", "cosyvoice_v3_vllm", "qwen3tts_gpu"],
    "ko": ["qwen3tts_gpu"],
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
    mode: str | None = None,
) -> str:
    """Pick best engine for (lang, requirements). Falls through chain.

    Args:
        lang: ISO code "zh"|"en"|"ja"|"ko"
        available: registered engine names (None → use all known)
        multi_speaker: True → force vibevoice
        prefer_fast: True → alias for mode="live" (kept for backward compat)
        mode: "quality" (default, indextts) or "live" (cosyvoice).
              None → DEFAULT_MODE; or "live" if prefer_fast=True.

    Returns:
        engine name (str)
    """
    if multi_speaker:
        primary = DEFAULTS["multi_speaker"]
    else:
        if mode is None:
            mode = "live" if prefer_fast else DEFAULT_MODE
        if mode not in PRESETS:
            raise ValueError(f"unknown mode={mode!r}; valid: {list(PRESETS)}")
        preset = PRESETS[mode]
        primary = preset.get(lang) or preset.get("en")  # unknown lang → en track

    avail = set(available) if available is not None else None

    if avail is None or primary in avail:
        return primary

    # Primary not in available → fall through chain
    chain = FALLBACK_CHAIN.get(lang) or FALLBACK_CHAIN["en"]
    for candidate in chain:
        if candidate in avail:
            return candidate

    if avail:
        return next(iter(avail))
    raise RuntimeError(f"No engine available for lang={lang}")


def explain_route(
    lang: str,
    multi_speaker: bool = False,
    prefer_fast: bool = False,
    mode: str | None = None,
) -> dict:
    """For /v2/route debug endpoint."""
    resolved_mode = mode or ("live" if prefer_fast else DEFAULT_MODE)
    return {
        "lang": lang,
        "mode": resolved_mode,
        "primary": pick_engine(
            lang, multi_speaker=multi_speaker, prefer_fast=prefer_fast, mode=mode
        ),
        "presets": PRESETS,
        "fallback_chain": FALLBACK_CHAIN.get(lang, []),
        "multi_speaker_requested": multi_speaker,
    }
