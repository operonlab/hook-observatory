"""P1b: extract a fact's valid_at from free-text content.

Pipeline:
  1. Pre-normalize CJK / slash / English month-name dates to ISO `YYYY-MM-DD`.
     Without this, text_ops.normalize_temporal_range only emits ISO from
     relative phrases ("上週", "X days ago"); literal `2025/01/15` or
     `2025年1月15日` would be silently lost.
  2. Run text_ops.normalize_temporal_range to expand relative phrases.
  3. Pick the FIRST ISO date as the fact's start time. (For ranges like
     "上週" → "YYYY-MM-DD 到 YYYY-MM-DD", first date = period start.)
  4. Return tz-aware UTC datetime, or None if no date is recoverable.

Caller MUST pass `ref=` set to the row's intended creation time
(e.g. body.created_at) so "上週" anchors on the session day, not now.

Used by routes.py POST /blocks.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from text_ops.temporal import normalize_temporal_range

# 1900-2099 is the only window we accept — narrows false positives from
# random 4-digit numbers (e.g. version strings, IDs).
_VALID_YEAR_RE = r"(?:19|20)\d{2}"

# Final form recognised by step 3.
_ISO_DATE_RE = re.compile(rf"\b({_VALID_YEAR_RE})-(\d{{2}})-(\d{{2}})\b")

# Step 1 normalisers — applied in order, all rewrite to `YYYY-MM-DD`.
_PRE_NORMALIZERS: list[tuple[re.Pattern[str], str]] = [
    # 2025/01/15 or 2025/1/15 → 2025-01-15
    (
        re.compile(rf"\b({_VALID_YEAR_RE})/(\d{{1,2}})/(\d{{1,2}})\b"),
        lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
    ),
    # 2025年1月15日 / 2025年01月15日 / 2025年1月15號
    (
        re.compile(rf"({_VALID_YEAR_RE})\s*年\s*(\d{{1,2}})\s*月\s*(\d{{1,2}})\s*[日號号]"),
        lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
    ),
    # English month name: "Jan 15, 2025" / "January 15 2025" / "15 Jan 2025"
    # Two flavours — month-first and day-first.
    (
        re.compile(
            r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
            r"(?:[a-z]+)?\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+"
            rf"({_VALID_YEAR_RE})\b",
            re.IGNORECASE,
        ),
        lambda m: _english_to_iso(m.group(1), m.group(2), m.group(3)),
    ),
    (
        re.compile(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
            rf"(?:[a-z]+)?\.?\s+({_VALID_YEAR_RE})\b",
            re.IGNORECASE,
        ),
        lambda m: _english_to_iso(m.group(2), m.group(1), m.group(3)),
    ),
]

_EN_MONTH_TO_NUM = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# English "X years/months/weeks/days ago" — text_ops/temporal does not currently
# resolve "years"/"months" suffixes from English, so we synthesise an ISO date
# directly. Resolution is approximate (year=365d, month=30d) — same fidelity as
# resolve_temporal_intent's relative branch.
_EN_AGO_RE = re.compile(
    r"\b(\d+)\s+(year|month|week|day)s?\s+ago\b",
    re.IGNORECASE,
)
_EN_AGO_DAYS = {"year": 365, "month": 30, "week": 7, "day": 1}


def _english_to_iso(month_name: str, day: str, year: str) -> str:
    m = _EN_MONTH_TO_NUM.get(month_name.lower()[:4]) or _EN_MONTH_TO_NUM.get(month_name.lower()[:3])
    if m is None:
        return f"{month_name} {day} {year}"  # leave alone — won't match _ISO_DATE_RE
    try:
        d = int(day)
    except ValueError:
        return f"{month_name} {day} {year}"
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return f"{month_name} {day} {year}"
    return f"{year}-{m:02d}-{d:02d}"


def _resolve_english_ago(content: str, ref: datetime) -> str:
    """Replace `X (years|months|weeks|days) ago` with ISO date relative to ref."""

    def repl(m: re.Match[str]) -> str:
        try:
            qty = int(m.group(1))
        except ValueError:
            return m.group(0)
        unit = m.group(2).lower()
        days = _EN_AGO_DAYS.get(unit)
        if days is None:
            return m.group(0)
        target = ref - timedelta(days=qty * days)
        return f"{target.year}-{target.month:02d}-{target.day:02d}"

    return _EN_AGO_RE.sub(repl, content)


def _pre_normalize(content: str) -> str:
    out = content
    for pattern, repl in _PRE_NORMALIZERS:
        out = pattern.sub(repl, out)  # type: ignore[arg-type]
    return out


def extract_valid_at(content: str, ref: datetime | None = None) -> datetime | None:
    """Return the first recovered ISO date as tz-aware UTC datetime, or None.

    Args:
        content: free-text block content.
        ref: reference datetime for resolving relative phrases. Defaults to
             utcnow(). For POST /blocks, callers should pass `body.created_at`
             so "上週" / "last week" anchor on the session day, not ingestion time.
    """
    if not content:
        return None

    if ref is None:
        ref = datetime.now(UTC)

    try:
        # Step 1: literal-form pre-normalisation (slash, CJK, English month).
        pre = _pre_normalize(content)
        # Step 1b: English "X years ago" — text_ops doesn't cover this.
        pre = _resolve_english_ago(pre, ref)
        # Step 2: relative phrases ("上週" / "X days ago" / etc).
        normalized = normalize_temporal_range(pre, ref=ref)
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
