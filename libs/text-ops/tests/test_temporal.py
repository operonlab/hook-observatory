"""Tests for TemporalNormalizer — cannibalized from dateparser + MS Recognizers."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from text_ops.temporal import TemporalNormalizer, TemporalIntent, resolve_temporal_intent
from text_ops.normalize import NormContext

UTC = timezone.utc
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
    def test_weekday_resolution(
        self, tn: TemporalNormalizer, expr: str, expected: str
    ) -> None:
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
    def test_relative_period(
        self, tn: TemporalNormalizer, expr: str, expected: str
    ) -> None:
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
    def test_double_relative(
        self, tn: TemporalNormalizer, expr: str, expected: str
    ) -> None:
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
        intent = TemporalIntent(
            type="relative", direction="past", unit="day", quantity=3
        )
        result = resolve_temporal_intent(intent, REF)
        assert result is not None
        assert result.day == 5  # April 5


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
