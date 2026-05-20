"""Long-text TTS segmenter — three-tier fallback splitting.

少爺 2026-05-20 規格：TTS engines 對長文表現差（cosyvoice/qwen3/vibevoice
都對 200+ 字會 collapse 或退化），station 層先切段、逐段合成、再 concat。

切段三層 fallback：
  1. 硬邊界 (。！？.!?\\n) — 句末優先
  2. 軟邊界 (，、；,;:) — 句中分隔
  3. 強制字數切 — 仍超長就硬切到 max_chars

Per-lang defaults：CJK 80 字，西文 200 字（單字密度差異）。
"""

from __future__ import annotations

import re

DEFAULT_MAX_CHARS = {"zh": 80, "ja": 60, "ko": 80, "en": 200}
DEFAULT_FALLBACK = 80

_HARD_BOUNDARIES = re.compile(r"(?<=[。！？.!?\n])")
_SOFT_BOUNDARIES = re.compile(r"(?<=[，、；,;:])")


def _split_by(pattern: re.Pattern, text: str) -> list[str]:
    return [s for s in pattern.split(text) if s.strip()]


def _force_chunks(text: str, max_chars: int) -> list[str]:
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def split_for_tts(text: str, lang: str = "zh", max_chars: int | None = None) -> list[str]:
    """Split text into TTS-friendly chunks.

    Args:
        text: input string
        lang: language code (zh/ja/ko/en); picks default max_chars
        max_chars: override default

    Returns:
        list of non-empty stripped chunks; never returns empty list (returns [text] if input non-empty)
    """
    text = (text or "").strip()
    if not text:
        return []
    cap = max_chars or DEFAULT_MAX_CHARS.get(lang, DEFAULT_FALLBACK)

    chunks: list[str] = []
    cur = ""

    # Tier 1: hard sentence boundaries
    for sent in _split_by(_HARD_BOUNDARIES, text):
        if not sent.strip():
            continue
        if len(sent) > cap:
            # Flush current accumulator first
            if cur.strip():
                chunks.append(cur.strip())
                cur = ""
            # Tier 2 + 3 recursive
            chunks.extend(_split_oversized(sent, cap))
        elif len(cur) + len(sent) > cap and cur:
            chunks.append(cur.strip())
            cur = sent
        else:
            cur += sent

    if cur.strip():
        chunks.append(cur.strip())

    # Final pass: any chunk still > cap (e.g. no sentence punctuation at all) → force split
    out: list[str] = []
    for c in chunks:
        if len(c) > cap:
            out.extend(_force_chunks(c, cap))
        else:
            out.append(c)
    return out or [text]


_SPEAKER_PREFIX = re.compile(r"^Speaker\s+(\d+)\s*:\s*(.*)$", re.IGNORECASE)


def split_for_podcast(script: str, lang: str = "zh", max_chars: int | None = None) -> list[dict]:
    """Parse a "Speaker N: ..." script into per-speaker per-sentence segments.

    Input formats accepted:
        Speaker 1: hello.\\nSpeaker 2: hi there.
        Speaker 1: long paragraph with multiple sentences. another sentence.

    Output: [{"speaker": int, "text": str}, ...], each chunk respects the same
    max_chars cap as split_for_tts so long monologue lines still get sub-split.

    Lines without a "Speaker N:" prefix attach to the current speaker (default
    speaker=1 if the script never declares one — same default as VibeVoice's
    processor._convert_text_to_script fallback).
    """
    cap = max_chars or DEFAULT_MAX_CHARS.get(lang, DEFAULT_FALLBACK)
    out: list[dict] = []
    current_speaker = 1
    pending_text = ""

    def _flush(speaker: int, text: str) -> None:
        text = text.strip()
        if not text:
            return
        for chunk in split_for_tts(text, lang=lang, max_chars=cap):
            out.append({"speaker": speaker, "text": chunk})

    for raw in (script or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SPEAKER_PREFIX.match(line)
        if m:
            # Flush previous speaker's accumulated text first
            _flush(current_speaker, pending_text)
            pending_text = ""
            current_speaker = int(m.group(1))
            rest = m.group(2).strip()
            if rest:
                pending_text = rest
        else:
            pending_text = (pending_text + " " + line).strip() if pending_text else line

    _flush(current_speaker, pending_text)
    return out


def _split_oversized(sent: str, cap: int) -> list[str]:
    """Tier 2 → Tier 3: try soft boundaries first, then force chunks."""
    soft = _split_by(_SOFT_BOUNDARIES, sent)
    if len(soft) <= 1:
        return _force_chunks(sent, cap)

    out: list[str] = []
    cur = ""
    for piece in soft:
        if len(piece) > cap:
            if cur.strip():
                out.append(cur.strip())
                cur = ""
            out.extend(_force_chunks(piece, cap))
        elif len(cur) + len(piece) > cap and cur:
            out.append(cur.strip())
            cur = piece
        else:
            cur += piece
    if cur.strip():
        out.append(cur.strip())
    return out
