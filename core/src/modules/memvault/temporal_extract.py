"""P1b: extract a fact's valid_at from free-text content.

Pipeline:
  1. Run text_ops.normalize_temporal_range to rewrite relative phrases
     (e.g. "上週" → "2026-04-21 到 2026-04-27") to absolute ISO dates.
  2. Pick the FIRST ISO date encountered as the fact's start time.
  3. Return tz-aware UTC datetime, or None if no date found.

Used by routes.py POST /blocks to populate MemoryBlock.valid_at when
the caller did not specify it explicitly.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from text_ops.temporal import normalize_temporal_range

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def extract_valid_at(content: str, ref: datetime | None = None) -> datetime | None:
    """Return the first ISO date in normalized content, or None.

    Returns midnight UTC for the picked date — sub-day resolution is not
    extracted (consistent with how Triple.valid_at is treated in kg_services).
    """
    if not content:
        return None
    try:
        normalized = normalize_temporal_range(content, ref=ref)
    except Exception:
        return None
    m = _ISO_DATE_RE.search(normalized)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d, tzinfo=UTC)
    except (ValueError, TypeError):
        return None
