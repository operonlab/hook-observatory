"""Tests for TemporalNormalizer — cannibalized from dateparser + MS Recognizers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from text_ops.normalize import NormContext
from text_ops.temporal import (
    TemporalIntent,
    TemporalNormalizer,
    normalize_temporal,
    normalize_temporal_range,
    resolve_temporal_intent,
)

UTC = UTC
REF = datetime(2026, 4, 8, 14, 0, 0, tzinfo=UTC)  # Wednesday
CTX = NormContext(created_at=REF)


@pytest.fixture
def tn() -> TemporalNormalizer:
    return TemporalNormalizer()


# ======================== Pass 1: Special Day ========================


class TestSpecialDay:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("今天", "2026-04-08"),
            ("今日", "2026-04-08"),
            ("昨天", "2026-04-07"),
            ("昨日", "2026-04-07"),
            ("前天", "2026-04-06"),
            ("後天", "2026-04-10"),
            ("大後天", "2026-04-11"),
            ("大前天", "2026-04-05"),
            ("明天", "2026-04-09"),
            ("明日", "2026-04-09"),
            # English
            ("yesterday", "2026-04-07"),
            ("today", "2026-04-08"),
            ("tomorrow", "2026-04-09"),
            ("the day before yesterday", "2026-04-06"),
            ("the day after tomorrow", "2026-04-10"),
        ],
    )
    def test_special_day(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, changes = tn.normalize(expr, CTX)
        assert expected in result
        assert len(changes) >= 1

    def test_longer_match_first(self, tn: TemporalNormalizer) -> None:
        """大後天 must not be partially consumed as 後天."""
        result, _ = tn.normalize("大後天", CTX)
        assert result == "2026-04-11"

    def test_english_case_insensitive(self, tn: TemporalNormalizer) -> None:
        result, _ = tn.normalize("Yesterday was fun", CTX)
        assert "2026-04-07" in result


# ======================== Pass 2: Prefix + Weekday ========================


class TestPrefixWeekday:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("上週一", "2026-03-30"),
            ("上週二", "2026-03-31"),
            ("上週三", "2026-04-01"),
            ("上週四", "2026-04-02"),
            ("上週五", "2026-04-03"),
            ("上週六", "2026-04-04"),
            ("上週日", "2026-04-05"),
            ("下週一", "2026-04-13"),
            ("下週三", "2026-04-15"),
            ("下週五", "2026-04-17"),
            ("這週五", "2026-04-10"),
        ],
    )
    def test_weekday_resolution(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, changes = tn.normalize(expr, CTX)
        assert expected in result
        assert len(changes) >= 1

    def test_simplified_chinese_weekday(self, tn: TemporalNormalizer) -> None:
        """简体 '上周四' should be converted to 繁体 and resolved."""
        result, _ = tn.normalize("上周四", CTX)
        assert "2026-04-02" in result


# ======================== Pass 3: N Units Ago/Later ========================


class TestNUnitsAgoLater:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("3天前", "2026-04-05"),
            ("5天前", "2026-04-03"),
            ("2週前", "2026-03-25"),
            ("3個月前", "2026-01"),
            ("2小時前", "12:00"),
            # Future direction
            ("3天後", "2026-04-11"),
            ("2週後", "2026-04-22"),
            # Simplified
            ("3个月前", "2026-01"),
            # English
            ("3 days ago", "2026-04-05"),
            ("2 weeks ago", "2026-03-25"),
            ("in 3 days", "2026-04-11"),
        ],
    )
    def test_n_units(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, _ = tn.normalize(expr, CTX)
        assert expected in result


# ======================== Pass 4: Relative Period ========================


class TestRelativePeriod:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("上週", "2026-04-01"),
            ("上個月", "2026-03"),
            ("去年", "2025"),
            ("明年", "2027"),
            ("last week", "2026-04-01"),
        ],
    )
    def test_relative_period(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, _ = tn.normalize(expr, CTX)
        assert expected in result


# ======================== Pass 5: Month + Day Combo ========================


class TestMonthDayCombo:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("下個月5號", "2026-05-05"),
            ("上個月15號", "2026-03-15"),
            ("這個月1號", "2026-04-01"),
        ],
    )
    def test_month_day(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, _ = tn.normalize(expr, CTX)
        assert expected in result


# ======================== Pass 6: Boundary ========================


class TestBoundary:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("月底", "2026-04-30"),
            ("年底", "2026-12-31"),
            ("月初", "2026-04-01"),
            ("年初", "2026-01-01"),
        ],
    )
    def test_boundary(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, _ = tn.normalize(expr, CTX)
        assert expected in result


# ======================== Pass 7: Double Relative ========================


class TestDoubleRelative:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("上上週", "2026-03-25"),
            ("上上個月", "2026-02"),
            ("下下週", "2026-04-22"),
            ("前年", "2024"),
        ],
    )
    def test_double_relative(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, _ = tn.normalize(expr, CTX)
        assert expected in result


# ======================== Multi-expression Text ========================


class TestMultiExpression:
    def test_mixed_text(self, tn: TemporalNormalizer) -> None:
        text = "上週四我去了台北。3天前又去了一次。下個月5號還要去。月底前要完成。"
        result, changes = tn.normalize(text, CTX)
        assert "2026-04-02" in result  # 上週四
        assert "2026-04-05" in result  # 3天前
        assert "2026-05-05" in result  # 下個月5號
        assert "2026-04-30" in result  # 月底
        assert len(changes) == 4


# ======================== TemporalIntent (LLM Interface) ========================


class TestTemporalIntent:
    def test_serializable(self) -> None:
        import dataclasses
        import json

        intent = TemporalIntent(
            type="relative", direction="past", unit="day", quantity=3, confidence=0.9
        )
        d = dataclasses.asdict(intent)
        s = json.dumps(d, ensure_ascii=False)
        assert '"type": "relative"' in s

    def test_resolve_simple_past(self) -> None:
        intent = TemporalIntent(type="relative", direction="past", unit="day", quantity=3)
        result = resolve_temporal_intent(intent, REF)
        assert result is not None
        assert result.day == 5  # April 5


# ======================== Week Synonym (Pass 0.7) ========================


class TestWeekSynonym:
    """Standalone "上禮拜" / "下禮拜" must be treated as "上週" / "下週".

    (Was an upstream gap: Pass 4 regex only covered 上週/下週, missing 禮拜
    variant when not followed by a weekday character.)
    """

    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("上禮拜", "2026-04-01"),  # same as 上週 (ref - 7 days)
            ("下禮拜", "2026-04-15"),  # same as 下週 (ref + 7 days)
            ("本禮拜", "2026-04-08"),  # same as 本週 (ref)
            ("這禮拜", "2026-04-08"),
        ],
    )
    def test_standalone_礼拜(self, tn: TemporalNormalizer, expr: str, expected: str) -> None:
        result, _ = tn.normalize(expr, CTX)
        assert expected in result

    def test_礼拜_with_weekday_preserved(self, tn: TemporalNormalizer) -> None:
        """上禮拜三 should still resolve via Pass 2 (not mangled by Pass 0.7)."""
        result, _ = tn.normalize("上禮拜三", CTX)
        # Pass 2 last-weekday-Wednesday from ref=Wed 2026-04-08 → 2026-04-01
        assert "2026-04-01" in result


# ======================== normalize_temporal (pure function API) ========================


class TestNormalizeTemporalPure:
    """Pure-function wrapper accepting a plain datetime instead of NormContext."""

    def test_accepts_datetime(self) -> None:
        result = normalize_temporal("3天前", REF)
        assert "2026-04-05" in result

    def test_uses_now_when_ref_none(self) -> None:
        # Just verify no exception + output contains some date
        import re as _re

        result = normalize_temporal("今天")
        assert _re.search(r"\d{4}-\d{2}-\d{2}", result) is not None

    def test_fail_open_on_empty(self) -> None:
        assert normalize_temporal("", REF) == ""
        assert normalize_temporal("no temporal words", REF).strip() == "no temporal words"

    def test_iso_dates_space_padded(self) -> None:
        """Output YYYY-MM-DD must have space on both sides so \\b regex works."""
        result = normalize_temporal("查3天前的手術", REF)
        assert " 2026-04-05 " in result


# ======================== normalize_temporal_range (range API) ========================


class TestNormalizeTemporalRange:
    """Range-aware variant: period expressions → 'YYYY-MM-DD 到 YYYY-MM-DD'."""

    @pytest.mark.parametrize(
        "expr, expected",
        [
            # Week ranges (ref is Wed 2026-04-08; last week Mon-Sun = Mar 30 - Apr 5)
            ("上週", "2026-03-30 到 2026-04-05"),
            ("上禮拜", "2026-03-30 到 2026-04-05"),
            ("本週", "2026-04-06 到 2026-04-12"),
            ("下週", "2026-04-13 到 2026-04-19"),
            ("上上週", "2026-03-23 到 2026-03-29"),
            # Month ranges
            ("上個月", "2026-03-01 到 2026-03-31"),
            ("本月", "2026-04-01 到 2026-04-30"),
            ("下個月", "2026-05-01 到 2026-05-31"),
            ("上上個月", "2026-02-01 到 2026-02-28"),
            # Year ranges
            ("去年", "2025-01-01 到 2025-12-31"),
            ("今年", "2026-01-01 到 2026-12-31"),
            ("明年", "2027-01-01 到 2027-12-31"),
            ("前年", "2024-01-01 到 2024-12-31"),
            # Year + month (month range within year)
            ("去年三月", "2025-03-01 到 2025-03-31"),
            ("去年12月", "2025-12-01 到 2025-12-31"),
            ("今年一月", "2026-01-01 到 2026-01-31"),
            # Half year / quarter (ref is Q2 = Apr-Jun)
            ("上半年", "2026-01-01 到 2026-06-30"),
            ("下半年", "2026-07-01 到 2026-12-31"),
            ("上季", "2026-01-01 到 2026-03-31"),
            ("下季", "2026-07-01 到 2026-09-30"),
            ("本季", "2026-04-01 到 2026-06-30"),
            # 最近 N units
            ("最近3天", "2026-04-06 到 2026-04-08"),
            ("最近三天", "2026-04-06 到 2026-04-08"),
            ("最近一週", "2026-04-01 到 2026-04-08"),
            ("最近2週", "2026-03-25 到 2026-04-08"),
            ("最近一個月", "2026-03-09 到 2026-04-08"),
            ("最近3個月", "2026-01-08 到 2026-04-08"),
        ],
    )
    def test_range_expressions(self, expr: str, expected: str) -> None:
        result = normalize_temporal_range(expr, REF.replace(tzinfo=None))
        assert expected in result

    @pytest.mark.parametrize(
        "expr, expected",
        [
            # Pass 2 weekday must still resolve to a single date
            ("上週一", "2026-03-30"),
            ("下週五", "2026-04-17"),
            ("上禮拜三", "2026-04-01"),
            # Pass 5 month+day single date
            ("上個月3號", "2026-03-03"),
            ("下個月15日", "2026-05-15"),
            # Pass 3 N ago / later
            ("3天前", "2026-04-05"),
            ("5天後", "2026-04-13"),
            ("一週前", "2026-04-01"),
            # Pass 1 single day
            ("今天", "2026-04-08"),
            ("昨天", "2026-04-07"),
            ("大後天", "2026-04-11"),
        ],
    )
    def test_single_date_preserved(self, expr: str, expected: str) -> None:
        """Single-date expressions must not be mangled by the range pre-pass."""
        result = normalize_temporal_range(expr, REF.replace(tzinfo=None))
        assert expected in result

    def test_realistic_query_last_week(self) -> None:
        result = normalize_temporal_range("查上禮拜所有的手術", REF.replace(tzinfo=None))
        assert "2026-03-30 到 2026-04-05" in result

    def test_realistic_query_recent_3_days(self) -> None:
        result = normalize_temporal_range("最近三天有幾台手術", REF.replace(tzinfo=None))
        assert "2026-04-06 到 2026-04-08" in result

    @pytest.mark.parametrize(
        "expr, expected",
        [
            # Cross-period ranges: "X 到 Y" with both X and Y as period
            # expressions should collapse into a single outer range.
            # REF = Wed 2026-04-08
            ("去年一月到今年三月之間", "2025-01-01 到 2026-03-31"),
            ("上週到下週", "2026-03-30 到 2026-04-19"),
            ("上個月到本月", "2026-03-01 到 2026-04-30"),
            ("去年到今年", "2025-01-01 到 2026-12-31"),
        ],
    )
    def test_cross_period_collapse(self, expr: str, expected: str) -> None:
        """A 到 B 到 C 到 D chains must collapse to (earliest, latest)."""
        result = normalize_temporal_range(expr, REF.replace(tzinfo=None))
        assert expected in result

    def test_simple_range_not_collapsed(self) -> None:
        """Single period (2-date range) must not be touched by chain collapsing."""
        result = normalize_temporal_range("上週", REF.replace(tzinfo=None))
        assert "2026-03-30 到 2026-04-05" in result

    def test_iso_dates_space_padded(self) -> None:
        """Range output must also be space-padded so \\b regex works downstream."""
        result = normalize_temporal_range("查上週手術", REF.replace(tzinfo=None))
        # Leading and trailing spaces around ISO dates
        assert " 2026-03-30 " in result

    def test_fail_open_on_empty(self) -> None:
        assert normalize_temporal_range("", REF) == ""


# ======================== Deprecation ========================


class TestDeprecation:
    def test_date_normalizer_warns(self) -> None:
        with pytest.warns(DeprecationWarning, match="TemporalNormalizer"):
            from text_ops.normalize import DateNormalizer

            DateNormalizer()

    def test_date_normalizer_still_works(self) -> None:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from text_ops.normalize import DateNormalizer

            dn = DateNormalizer()
            result, changes = dn.normalize("昨天", CTX)
            assert "2026-04-07" in result


# ======================== Extended: Festival / Quarter / Cross-month ========================
# Ported from fast_mcp_client agent.py 2026-04-28


REF_2026_04_28 = datetime(2026, 4, 28, tzinfo=UTC)


class TestQuarter:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("Q1", "2026-01-01 到 2026-03-31"),
            ("Q2", "2026-04-01 到 2026-06-30"),
            ("Q3", "2026-07-01 到 2026-09-30"),
            ("Q4", "2026-10-01 到 2026-12-31"),
            ("q2", "2026-04-01 到 2026-06-30"),
            ("第一季", "2026-01-01 到 2026-03-31"),
            ("第二季", "2026-04-01 到 2026-06-30"),
            ("第三季", "2026-07-01 到 2026-09-30"),
            ("第四季", "2026-10-01 到 2026-12-31"),
            ("今年Q1", "2026-01-01 到 2026-03-31"),
            ("今年第一季", "2026-01-01 到 2026-03-31"),
            ("去年Q4", "2025-10-01 到 2025-12-31"),
            ("去年第三季", "2025-07-01 到 2025-09-30"),
            ("明年Q1", "2027-01-01 到 2027-03-31"),
            ("2025Q3", "2025-07-01 到 2025-09-30"),
        ],
    )
    def test_quarter(self, expr: str, expected: str) -> None:
        result = normalize_temporal_range(expr, REF_2026_04_28)
        assert expected in result


class TestCrossMonth:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            ("一月二月", "2026-01-01 到 2026-02-28"),
            ("一月到二月", "2026-01-01 到 2026-02-28"),
            ("一月至二月", "2026-01-01 到 2026-02-28"),
            ("1月到2月", "2026-01-01 到 2026-02-28"),
            ("1月-3月", "2026-01-01 到 2026-03-31"),
            ("1~3月", "2026-01-01 到 2026-03-31"),
            ("一月跟二月", "2026-01-01 到 2026-02-28"),
            ("一月與二月", "2026-01-01 到 2026-02-28"),
            ("一月、二月", "2026-01-01 到 2026-02-28"),
            ("一月及二月", "2026-01-01 到 2026-02-28"),
            ("今年一月二月", "2026-01-01 到 2026-02-28"),
            ("去年一月二月", "2025-01-01 到 2025-02-28"),
        ],
    )
    def test_cross_month(self, expr: str, expected: str) -> None:
        result = normalize_temporal_range(expr, REF_2026_04_28)
        assert expected in result


class TestFestival:
    @pytest.mark.parametrize(
        "expr, expected",
        [
            # 春節 = 除夕 ~ 大年初五 (6 days)
            ("過年", "2026-02-16 到 2026-02-21"),
            ("春節", "2026-02-16 到 2026-02-21"),
            ("春节", "2026-02-16 到 2026-02-21"),
            ("今年過年", "2026-02-16 到 2026-02-21"),
            ("明年春節", "2027-02-05 到 2027-02-10"),
            ("2025春節", "2025-01-28 到 2025-02-02"),
            # 除夕 (春節前一天)
            ("除夕", "2026-02-16 到 2026-02-16"),
            # 元宵 = 農曆 1/15
            ("元宵", "2026-03-03 到 2026-03-03"),
            ("元宵節", "2026-03-03 到 2026-03-03"),
            ("元宵节", "2026-03-03 到 2026-03-03"),
            # 清明 = 國曆 4/4-4/5
            ("清明", "2026-04-04 到 2026-04-05"),
            ("清明節", "2026-04-04 到 2026-04-05"),
            # 端午 = 農曆 5/5
            ("端午", "2026-06-19 到 2026-06-19"),
            ("端午節", "2026-06-19 到 2026-06-19"),
            # 中秋 = 農曆 8/15
            ("中秋", "2026-09-25 到 2026-09-25"),
            ("中秋節", "2026-09-25 到 2026-09-25"),
            ("去年中秋", "2025-10-06 到 2025-10-06"),
            # 重陽 = 農曆 9/9
            ("重陽", "2026-10-18 到 2026-10-18"),
            ("重陽節", "2026-10-18 到 2026-10-18"),
            ("重阳节", "2026-10-18 到 2026-10-18"),
        ],
    )
    def test_festival(self, expr: str, expected: str) -> None:
        result = normalize_temporal_range(expr, REF_2026_04_28)
        assert expected in result, f"{expr!r}: expected {expected!r} in {result!r}"
