"""Tests for memvault._resolve_temporal_range after adopting text_ops.normalize_temporal_range.

Regression fixes verified:
- 上個月 / 去年 / 去年三月 / 上半年 etc. now return full period (was 7-day only).
- 最近3天 / 最近一週 / 最近一個月 now resolve (was no-match).
- 去年一月到今年三月 cross-period chains collapse to single outer range.

Preserved behavior verified:
- Single-date anchors (上週一, 昨天, 3天前) still expand to Sun-Sat week.
- Explicit week queries (上週, 本週) still shift to Sun-Sat.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

# ── path bootstrap (same pattern as sibling memvault tests) ────────────────
_CORE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_ROOT = _REPO_ROOT / "libs" / "sdk-client"
_TEXT_OPS_ROOT = _REPO_ROOT / "libs" / "text-ops"

for _p in (_CORE_ROOT, _SDK_ROOT, _TEXT_OPS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from src.modules.memvault.query_expander import _resolve_temporal_range  # noqa: E402


# Wed 2026-04-08 — same reference as libs/text-ops tests for consistency
REF = datetime(2026, 4, 8, 14, 0, 0)


def _iso_day(d: str) -> int:
    """Return ISO weekday (1=Mon ... 7=Sun) for an ISO date string."""
    return datetime.strptime(d, "%Y-%m-%d").isoweekday()


class TestPeriodExpansion:
    """Period expressions now return full calendar range (not 7 days)."""

    def test_last_month_full_month(self):
        assert _resolve_temporal_range("上個月的手術", REF) == (
            "2026-03-01",
            "2026-03-31",
        )

    def test_this_month_full_month(self):
        assert _resolve_temporal_range("本月進度", REF) == (
            "2026-04-01",
            "2026-04-30",
        )

    def test_last_year_full_year(self):
        assert _resolve_temporal_range("去年寫了什麼", REF) == (
            "2025-01-01",
            "2025-12-31",
        )

    def test_last_year_march(self):
        assert _resolve_temporal_range("去年三月的筆記", REF) == (
            "2025-03-01",
            "2025-03-31",
        )

    def test_first_half(self):
        assert _resolve_temporal_range("上半年總結", REF) == (
            "2026-01-01",
            "2026-06-30",
        )


class TestRecentN:
    """Count-based ranges now resolve (was unsupported)."""

    def test_recent_3_days(self):
        # 最近3天 from Wed 4/8 = Mon 4/6 ~ Wed 4/8
        assert _resolve_temporal_range("最近3天做了什麼", REF) == (
            "2026-04-06",
            "2026-04-08",
        )

    def test_recent_3_days_zh_number(self):
        assert _resolve_temporal_range("最近三天進度", REF) == (
            "2026-04-06",
            "2026-04-08",
        )

    def test_recent_1_week_rolling_window(self):
        """最近一週 is a rolling 7-day window ending today, NOT a Sun-Sat calendar week.

        Sun-Sat shift only applies to period-type weeks (上週/本週) whose upstream
        output is exactly Mon-Sun (diff=6). Rolling windows (最近一週, from
        ``ref - 7 days`` to ``ref``) have diff=7 and must be preserved as-is.
        """
        # Wed 2026-04-08 minus 7 days = Wed 2026-04-01 → rolling 7-day window
        assert _resolve_temporal_range("最近一週的內容", REF) == (
            "2026-04-01",
            "2026-04-08",
        )


class TestCrossPeriodChain:
    """Cross-period X到Y expressions collapse to outer range."""

    def test_last_year_jan_to_this_year_mar(self):
        assert _resolve_temporal_range("去年一月到今年三月之間", REF) == (
            "2025-01-01",
            "2026-03-31",
        )

    def test_last_month_to_this_month(self):
        assert _resolve_temporal_range("上個月到本月", REF) == (
            "2026-03-01",
            "2026-04-30",
        )

    def test_last_year_to_this_year(self):
        assert _resolve_temporal_range("去年到今年", REF) == (
            "2025-01-01",
            "2026-12-31",
        )


class TestSingleDateAnchor:
    """Legacy single-date → Sun-Sat week preserved."""

    def test_yesterday_expands_to_sun_sat_week(self):
        # Yesterday = Tue 2026-04-07 → Sun-Sat = Apr 5 ~ Apr 11
        date_from, date_to = _resolve_temporal_range("昨天做了什麼", REF)
        assert _iso_day(date_from) == 7  # Sun
        assert _iso_day(date_to) == 6  # Sat
        d_from = datetime.strptime(date_from, "%Y-%m-%d")
        d_to = datetime.strptime(date_to, "%Y-%m-%d")
        assert (d_to - d_from).days == 6

    def test_last_monday_expands_to_sun_sat_week(self):
        # 上週一 = Mon 2026-03-30 → Sun-Sat week = Mar 29 ~ Apr 4
        assert _resolve_temporal_range("上週一去了哪裡", REF) == (
            "2026-03-29",
            "2026-04-04",
        )

    def test_3_days_ago_expands_to_sun_sat_week(self):
        # 3天前 = Sun 2026-04-05 → Sun-Sat week = Apr 5 ~ Apr 11
        assert _resolve_temporal_range("3天前寫的", REF) == (
            "2026-04-05",
            "2026-04-11",
        )


class TestWeekShiftPreserved:
    """Explicit 週 queries with 7-day range still get Sun-Sat shift."""

    def test_last_week_shifted_sun_sat(self):
        # 上週 upstream → Mon 3/30 ~ Sun 4/5 → shift → Sun 3/29 ~ Sat 4/4
        date_from, date_to = _resolve_temporal_range("上週的內容", REF)
        assert _iso_day(date_from) == 7  # Sun
        assert _iso_day(date_to) == 6  # Sat

    def test_this_week_shifted_sun_sat(self):
        date_from, _ = _resolve_temporal_range("本週的進度", REF)
        assert _iso_day(date_from) == 7  # Sun


class TestNoMatch:
    def test_no_temporal_expression(self):
        assert _resolve_temporal_range("手術報告內容", REF) == (None, None)

    def test_empty_query(self):
        assert _resolve_temporal_range("", REF) == (None, None)
