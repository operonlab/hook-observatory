"""KWS operator — sherpa-onnx keyword spotter (zipformer zh-en)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import sherpa_onnx

logger = logging.getLogger(__name__)

# Pinyin mappings for common Chinese characters used in wake words
_PINYIN_MAP: dict[str, str] = {
    "你": "n ǐ", "好": "h ǎo", "助": "zh ù", "手": "sh ǒu",
    "嘿": "h ēi", "小": "x iǎo", "爱": "ài", "同": "t óng",
    "学": "x ué", "米": "m ǐ", "艺": "y ì", "问": "w èn",
    "管": "g uǎn", "家": "j iā", "维": "w éi", "恩": "ēn",
    "工": "g ōng", "作": "z uò", "坊": "f āng",
}


def _text_to_pinyin(text: str) -> str | None:
    """Convert Chinese text to pinyin token sequence for KWS.

    Returns None if any character can't be mapped.
    """
    parts = []
    for ch in text:
        if ch in _PINYIN_MAP:
            parts.append(_PINYIN_MAP[ch])
        elif ch.isascii() and ch.isalpha():
            parts.append(ch.upper())
        else:
            return None
    return " ".join(parts) if parts else None


def build_keywords_str(keywords: list[str]) -> str:
    """Build sherpa-onnx keywords string from display texts.

    Format: 'pinyin_tokens @display_text\\npinyin_tokens @display_text'
    Falls back to keywords_file for entries that can't be converted.
    """
    lines = []
    for kw in keywords:
        pinyin = _text_to_pinyin(kw)
        if pinyin:
            lines.append(f"{pinyin} @{kw}")
        else:
            logger.warning("kws_pinyin_failed: cannot convert %r, skipping", kw)
    return "\n".join(lines)


class KeywordSpotter:
    """sherpa-onnx keyword spotter — detects wake words in audio stream."""

    def __init__(
        self,
        model_dir: str | Path,
        keywords: list[str] | None = None,
        sample_rate: int = 16000,
        score_threshold: float = 1.0,
        provider: str = "cpu",
    ):
        model_dir = Path(model_dir).resolve()
        keywords_file = str(model_dir / "keywords.txt")

        # Use int8 models for efficiency
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
            decoder=str(model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
            joiner=str(model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
            keywords_file=keywords_file,
            num_threads=2,
            sample_rate=sample_rate,
            keywords_score=score_threshold,
            provider=provider,
        )
        self._sample_rate = sample_rate
        self._keywords = keywords or []
        self._stream = None
        self._reset_stream()
        logger.info(
            "kws_loaded: model_dir=%s keywords=%s provider=%s",
            model_dir.name, self._keywords, provider,
        )

    def _reset_stream(self) -> None:
        """Create a fresh stream with current keywords."""
        if self._keywords:
            kw_str = build_keywords_str(self._keywords)
            if kw_str:
                self._stream = self._spotter.create_stream(kw_str)
            else:
                self._stream = self._spotter.create_stream()
        else:
            self._stream = self._spotter.create_stream()

    def accept(self, samples: np.ndarray) -> str | None:
        """Feed audio chunk, return detected keyword or None."""
        self._stream.accept_waveform(self._sample_rate, samples)

        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)

        result = self._spotter.get_result(self._stream)
        if result:
            keyword = result.strip()
            logger.info("kws_detected: %r", keyword)
            self._reset_stream()
            return keyword
        return None

    def reset(self) -> None:
        """Reset stream state for fresh detection."""
        self._reset_stream()

    def update_keywords(self, keywords: list[str]) -> None:
        """Update keywords and reset stream."""
        self._keywords = keywords
        self._reset_stream()
        logger.info("kws_keywords_updated: %s", keywords)
