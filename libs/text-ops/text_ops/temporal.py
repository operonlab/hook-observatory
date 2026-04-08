"""Temporal Normalizer — replaces relative time expressions with absolute dates.

7-pass architecture (zero external dependencies, stdlib only):
  Pass 0: Simplified Chinese → Traditional Chinese (temporal keywords only)
  Pass 1: Special day keywords (今天, 昨天, 大後天, …)
  Pass 2: Prefix + weekday (上週一, 下週五, 這週三, …)
  Pass 3: N units ago/later (3天前, 2週後, 1個月前, 5 days ago, …)
  Pass 4: Relative period (上個月, 下週, 去年, …)
  Pass 5: Month + day combo (上個月3號, 下個月15日, …)
  Pass 6: Boundary keywords (月底, 年底, 月初, 年初)
  Pass 7: Double relative (上上週, 下下月, 前年, 後年)

IMPORTANT: Pass 7 and longer patterns run BEFORE shorter ones to avoid
partial matches ("上上週" must not be consumed by "上週").
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .normalize import NormChange, NormContext, NormalizerOp

# ======================== Simplified→Traditional mapping (temporal only) ========================

# str.maketrans for pass-0 conversion: maps simplified chars to traditional
_S2T = str.maketrans(
    {
        "周": "週",
        "个": "個",
        "后": "後",
        "点": "點",
        "时": "時",
        "钟": "鐘",
        "礼": "禮",
        "这": "這",
    }
)

# ======================== Core lookup tables ========================

WEEKDAY_MAP: dict[str, int] = {
    "週一": 1, "周一": 1, "星期一": 1, "禮拜一": 1, "礼拜一": 1,
    "週二": 2, "周二": 2, "星期二": 2, "禮拜二": 2, "礼拜二": 2,
    "週三": 3, "周三": 3, "星期三": 3, "禮拜三": 3, "礼拜三": 3,
    "週四": 4, "周四": 4, "星期四": 4, "禮拜四": 4, "礼拜四": 4,
    "週五": 5, "周五": 5, "星期五": 5, "禮拜五": 5, "礼拜五": 5,
    "週六": 6, "周六": 6, "星期六": 6, "禮拜六": 6, "礼拜六": 6,
    "週日": 7, "周日": 7, "星期日": 7, "星期天": 7, "週天": 7, "周天": 7,
    "禮拜日": 7, "禮拜天": 7, "礼拜日": 7, "礼拜天": 7,
}

# Ordered so longer keys appear before shorter keys (大後天 before 後天, etc.)
SPECIAL_DAY_SWIFT: dict[str, int] = {
    # English (longer first)
    "the day before yesterday": -2,
    "the day after tomorrow": 2,
    "yesterday": -1,
    "tomorrow": 1,
    "today": 0,
    # Chinese (longer first)
    "大後天": 3,
    "大前天": -3,
    "大后天": 3,
    "後天": 2,
    "前天": -2,
    "后天": 2,
    "明天": 1,
    "明日": 1,
    "今天": 0,
    "今日": 0,
    "昨天": -1,
    "昨日": -1,
}

# ======================== Weekday helpers ========================


def _this_weekday(ref: datetime, wd: int) -> datetime:
    """Same-week date for the given isoweekday (1=Mon … 7=Sun)."""
    return ref + timedelta(days=wd - ref.isoweekday())


def _next_weekday(ref: datetime, wd: int) -> datetime:
    return _this_weekday(ref, wd) + timedelta(weeks=1)


def _last_weekday(ref: datetime, wd: int) -> datetime:
    return _this_weekday(ref, wd) - timedelta(weeks=1)


# ======================== TemporalIntent (LLM interface schema) ========================


@dataclass
class TemporalIntent:
    """Structured representation of a temporal expression for LLM handoff."""

    type: str  # "relative", "absolute", "recurring", "vague"
    direction: str | None = None  # "past", "future"
    unit: str | None = None  # "day", "week", "month", "year", "hour", "minute", "second"
    quantity: int | None = None
    weekday: int | None = None  # 1-7 (isoweekday)
    day_of_month: int | None = None
    time_of_day: str | None = None  # e.g. "15:00"
    period: str | None = None  # "morning", "afternoon", "evening"
    confidence: float = 0.0


def resolve_temporal_intent(intent: TemporalIntent, ref: datetime) -> datetime | None:
    """Pure function: resolve a TemporalIntent to an absolute datetime.

    Returns None when the intent is too vague to produce a deterministic result.
    """
    if intent.type == "absolute":
        return None  # already absolute — caller should parse directly

    if intent.type == "vague":
        return None

    if intent.type == "relative":
        if intent.unit is None or intent.quantity is None:
            return None
        qty = intent.quantity
        sign = -1 if intent.direction == "past" else 1
        if intent.unit == "second":
            return ref + timedelta(seconds=sign * qty)
        if intent.unit == "minute":
            return ref + timedelta(minutes=sign * qty)
        if intent.unit == "hour":
            return ref + timedelta(hours=sign * qty)
        if intent.unit == "day":
            return ref + timedelta(days=sign * qty)
        if intent.unit == "week":
            return ref + timedelta(weeks=sign * qty)
        if intent.unit == "month":
            return ref + timedelta(days=sign * qty * 30)
        if intent.unit == "year":
            return ref + timedelta(days=sign * qty * 365)
        if intent.unit == "weekday" and intent.weekday is not None:
            if intent.direction == "past":
                return _last_weekday(ref, intent.weekday)
            return _next_weekday(ref, intent.weekday)
        return None

    if intent.type == "recurring":
        # Recurring: resolve to next occurrence
        if intent.weekday is not None:
            return _next_weekday(ref, intent.weekday)
        if intent.day_of_month is not None:
            candidate = ref.replace(day=intent.day_of_month)
            if candidate <= ref:
                # Push to next month
                year = ref.year + (ref.month // 12)
                month = (ref.month % 12) + 1
                max_day = calendar.monthrange(year, month)[1]
                day = min(intent.day_of_month, max_day)
                return ref.replace(year=year, month=month, day=day)
            return candidate
        return None

    return None


# ======================== TemporalNormalizer ========================

# Build weekday alternation for regex (longest keys first to avoid partial match)
_WD_ALTS = sorted(WEEKDAY_MAP.keys(), key=len, reverse=True)
_WD_PATTERN = "(?:" + "|".join(re.escape(k) for k in _WD_ALTS) + ")"


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _fmt_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


class TemporalNormalizer(NormalizerOp):
    """Replace relative temporal expressions with absolute dates (YYYY-MM-DD).

    All 7 passes are applied in order. Pass 0 normalises Simplified→Traditional
    in-memory only; the result is used for matching but the *original* fragments
    are tracked in NormChange so callers can correlate back to the source.
    """

    name = "temporal"

    # ---- compiled patterns (class-level, built once) ----

    # Pass 2: prefix + weekday
    _P2_LAST = re.compile(
        r"(上一?[個个]?|上)(的)?" + _WD_PATTERN
    )
    _P2_NEXT = re.compile(
        r"(下一?[個个]?|下)(的)?" + _WD_PATTERN
    )
    _P2_THIS = re.compile(
        r"(這一?[個个]?|這|本)(的)?" + _WD_PATTERN
    )

    # Pass 3: N units ago/later — Chinese
    _P3_DAYS_ZH = re.compile(r"(\d+)\s*天([前後后])")
    _P3_WEEKS_ZH = re.compile(r"(\d+)\s*[週周]([前後后])")
    _P3_MONTHS_ZH = re.compile(r"(\d+)\s*[個个]月([前後后])")
    _P3_YEARS_ZH = re.compile(r"(\d+)\s*年([前後后])")
    _P3_HOURS_ZH = re.compile(r"(\d+)\s*小[時时]([前後后])")
    _P3_MINUTES_ZH = re.compile(r"(\d+)\s*分[鐘钟]([前後后])")
    _P3_SECONDS_ZH = re.compile(r"(\d+)\s*秒([前後后])")
    # Pass 3: English
    _P3_DAYS_EN_AGO = re.compile(r"\b(\d+)\s*days?\s*ago\b", re.IGNORECASE)
    _P3_WEEKS_EN_AGO = re.compile(r"\b(\d+)\s*weeks?\s*ago\b", re.IGNORECASE)
    _P3_MONTHS_EN_AGO = re.compile(r"\b(\d+)\s*months?\s*ago\b", re.IGNORECASE)
    _P3_HOURS_EN_AGO = re.compile(r"\b(\d+)\s*hours?\s*ago\b", re.IGNORECASE)
    _P3_IN_DAYS_EN = re.compile(r"\bin\s+(\d+)\s*days?\b", re.IGNORECASE)

    # Pass 4: relative period (LONGER matches before shorter, handled by order)
    # Ordered dict ensures上上週/下下月 are caught in Pass 7 first
    _P4_PATTERNS: list[tuple[re.Pattern[str], int, str]] = [
        (re.compile(r"上[個个]?月"), -30, "date"),
        (re.compile(r"下[個个]?月"), 30, "date"),
        (re.compile(r"上[週周]"), -7, "date"),
        (re.compile(r"下[週周]"), 7, "date"),
        (re.compile(r"去年"), -365, "date"),
        (re.compile(r"明年"), 365, "date"),
        (re.compile(r"今年"), 0, "year_start"),
        (re.compile(r"本[月]"), 0, "month_start"),
        (re.compile(r"本[週周]"), 0, "date"),
        (re.compile(r"\blast\s+week\b", re.IGNORECASE), -7, "date"),
        (re.compile(r"\bnext\s+week\b", re.IGNORECASE), 7, "date"),
        (re.compile(r"\blast\s+month\b", re.IGNORECASE), -30, "date"),
        (re.compile(r"\bnext\s+month\b", re.IGNORECASE), 30, "date"),
        (re.compile(r"\blast\s+year\b", re.IGNORECASE), -365, "date"),
        (re.compile(r"\bnext\s+year\b", re.IGNORECASE), 365, "date"),
    ]

    # Pass 5: month + specific day combo
    _P5_PATTERN = re.compile(
        r"(上|下|這|本)[個个]?月(\d{1,2})[號号日]?"
    )

    # Pass 6: boundary keywords (optional 本/這/这 prefix consumed to avoid leftovers)
    _P6_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"(?:[本這这])?月底"), "month_end"),
        (re.compile(r"(?:[本這这今])?年底"), "year_end"),
        (re.compile(r"(?:[本這这])?月初"), "month_start"),
        (re.compile(r"(?:[本這这今])?年初"), "year_start"),
    ]

    # Pass 7: double relative (run BEFORE pass 4)
    _P7_PATTERNS: list[tuple[re.Pattern[str], int, str]] = [
        (re.compile(r"上上[個个]?[週周]"), -14, "date"),
        (re.compile(r"下下[個个]?[週周]"), 14, "date"),
        (re.compile(r"上上[個个]?月"), -60, "date"),
        (re.compile(r"下下[個个]?月"), 60, "date"),
        (re.compile(r"前年"), -730, "date"),
        (re.compile(r"[後后]年"), 730, "date"),
    ]

    def normalize(self, content: str, ctx: NormContext) -> tuple[str, list[NormChange]]:
        changes: list[NormChange] = []
        ref = ctx.created_at

        # ---- Pass 0: Simplified→Traditional (in-memory only) ----
        normalised = content.translate(_S2T)

        # ---- Pass 7: double relative (before pass 4 to prevent partial match) ----
        normalised = self._pass7(normalised, ref, changes, content)

        # ---- Pass 1: special day keywords ----
        normalised = self._pass1(normalised, ref, changes)

        # ---- Pass 2: prefix + weekday ----
        normalised = self._pass2(normalised, ref, changes)

        # ---- Pass 3: N units ago/later ----
        normalised = self._pass3(normalised, ref, changes)

        # ---- Pass 6: boundary keywords (before pass 4 to avoid 月底 partial) ----
        normalised = self._pass6(normalised, ref, changes)

        # ---- Pass 5: month + specific day (before pass 4, more specific) ----
        normalised = self._pass5(normalised, ref, changes)

        # ---- Pass 4: relative period ----
        normalised = self._pass4(normalised, ref, changes)

        return normalised, changes

    # ---- pass implementations ----

    def _pass1(self, text: str, ref: datetime, changes: list[NormChange]) -> str:
        # Longer keys first (大後天 before 後天, "the day before yesterday" before "yesterday")
        for key, swift in SPECIAL_DAY_SWIFT.items():
            if key not in text.lower() if key.isascii() else key not in text:
                continue
            target = _fmt_date(ref + timedelta(days=swift))

            def _repl(m: re.Match[str], t: str = target, k: str = key) -> str:
                changes.append(NormChange("temporal", k, t))
                return t

            # English keys need word boundaries + case-insensitive
            if key.isascii():
                pattern = r"\b" + re.escape(key) + r"\b"
                text = re.sub(pattern, _repl, text, flags=re.IGNORECASE)
            else:
                text = re.sub(re.escape(key), _repl, text)
        return text

    def _pass2(self, text: str, ref: datetime, changes: list[NormChange]) -> str:
        def _make_repl(calc_fn: object) -> object:
            def _repl(m: re.Match[str]) -> str:
                wd_str = _extract_weekday(m.group(0))
                if wd_str is None:
                    return m.group(0)
                wd = WEEKDAY_MAP[wd_str]
                # calc_fn is one of _last_weekday / _next_weekday / _this_weekday
                dt = calc_fn(ref, wd)  # type: ignore[call-arg]
                target = _fmt_date(dt)
                changes.append(NormChange("temporal", m.group(0), target))
                return target

            return _repl

        text = self._P2_LAST.sub(_make_repl(_last_weekday), text)
        text = self._P2_NEXT.sub(_make_repl(_next_weekday), text)
        text = self._P2_THIS.sub(_make_repl(_this_weekday), text)
        return text

    def _pass3(self, text: str, ref: datetime, changes: list[NormChange]) -> str:
        def _zh_dir(d: str) -> int:
            return -1 if d == "前" else 1

        def _repl_factory(unit: str, is_dt: bool = False):
            def _repl(m: re.Match[str]) -> str:
                n = int(m.group(1))
                sign = _zh_dir(m.group(2))
                if unit == "day":
                    dt = ref + timedelta(days=sign * n)
                elif unit == "week":
                    dt = ref + timedelta(weeks=sign * n)
                elif unit == "month":
                    dt = ref + timedelta(days=sign * n * 30)
                elif unit == "year":
                    dt = ref + timedelta(days=sign * n * 365)
                elif unit == "hour":
                    dt = ref + timedelta(hours=sign * n)
                    is_dt_ = True
                    target = _fmt_datetime(dt)
                    changes.append(NormChange("temporal", m.group(0), target))
                    return target
                elif unit == "minute":
                    dt = ref + timedelta(minutes=sign * n)
                    target = _fmt_datetime(dt)
                    changes.append(NormChange("temporal", m.group(0), target))
                    return target
                elif unit == "second":
                    dt = ref + timedelta(seconds=sign * n)
                    target = _fmt_datetime(dt)
                    changes.append(NormChange("temporal", m.group(0), target))
                    return target
                else:
                    return m.group(0)
                target = _fmt_datetime(dt) if is_dt else _fmt_date(dt)
                changes.append(NormChange("temporal", m.group(0), target))
                return target

            return _repl

        text = self._P3_DAYS_ZH.sub(_repl_factory("day"), text)
        text = self._P3_WEEKS_ZH.sub(_repl_factory("week"), text)
        text = self._P3_MONTHS_ZH.sub(_repl_factory("month"), text)
        text = self._P3_YEARS_ZH.sub(_repl_factory("year"), text)
        text = self._P3_HOURS_ZH.sub(_repl_factory("hour"), text)
        text = self._P3_MINUTES_ZH.sub(_repl_factory("minute"), text)
        text = self._P3_SECONDS_ZH.sub(_repl_factory("second"), text)

        # English
        def _en_ago_factory(unit: str):
            def _repl(m: re.Match[str]) -> str:
                n = int(m.group(1))
                if unit == "day":
                    dt = ref - timedelta(days=n)
                elif unit == "week":
                    dt = ref - timedelta(weeks=n)
                elif unit == "month":
                    dt = ref - timedelta(days=n * 30)
                elif unit == "hour":
                    dt = ref - timedelta(hours=n)
                    target = _fmt_datetime(dt)
                    changes.append(NormChange("temporal", m.group(0), target))
                    return target
                else:
                    return m.group(0)
                target = _fmt_date(dt)
                changes.append(NormChange("temporal", m.group(0), target))
                return target

            return _repl

        text = self._P3_DAYS_EN_AGO.sub(_en_ago_factory("day"), text)
        text = self._P3_WEEKS_EN_AGO.sub(_en_ago_factory("week"), text)
        text = self._P3_MONTHS_EN_AGO.sub(_en_ago_factory("month"), text)
        text = self._P3_HOURS_EN_AGO.sub(_en_ago_factory("hour"), text)

        def _in_days_repl(m: re.Match[str]) -> str:
            n = int(m.group(1))
            dt = ref + timedelta(days=n)
            target = _fmt_date(dt)
            changes.append(NormChange("temporal", m.group(0), target))
            return target

        text = self._P3_IN_DAYS_EN.sub(_in_days_repl, text)
        return text

    def _pass4(self, text: str, ref: datetime, changes: list[NormChange]) -> str:
        for pat, offset, kind in self._P4_PATTERNS:
            if kind == "year_start":
                target = ref.replace(month=1, day=1).strftime("%Y-%m-%d")
            elif kind == "month_start":
                target = ref.replace(day=1).strftime("%Y-%m-%d")
            else:
                target = _fmt_date(ref + timedelta(days=offset))

            def _repl(m: re.Match[str], t: str = target) -> str:
                changes.append(NormChange("temporal", m.group(0), t))
                return t

            text = pat.sub(_repl, text)
        return text

    def _pass5(self, text: str, ref: datetime, changes: list[NormChange]) -> str:
        def _repl(m: re.Match[str]) -> str:
            prefix = m.group(1)
            day = int(m.group(2))
            if prefix in ("上",):
                # last month
                month = ref.month - 1 if ref.month > 1 else 12
                year = ref.year if ref.month > 1 else ref.year - 1
            elif prefix in ("下",):
                month = ref.month + 1 if ref.month < 12 else 1
                year = ref.year if ref.month < 12 else ref.year + 1
            else:  # 這/本
                month = ref.month
                year = ref.year
            max_day = calendar.monthrange(year, month)[1]
            day = min(day, max_day)
            try:
                target = datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                return m.group(0)
            changes.append(NormChange("temporal", m.group(0), target))
            return target

        return self._P5_PATTERN.sub(_repl, text)

    def _pass6(self, text: str, ref: datetime, changes: list[NormChange]) -> str:
        for pat, kind in self._P6_PATTERNS:
            if kind == "month_end":
                last_day = calendar.monthrange(ref.year, ref.month)[1]
                target = ref.replace(day=last_day).strftime("%Y-%m-%d")
            elif kind == "year_end":
                target = ref.replace(month=12, day=31).strftime("%Y-%m-%d")
            elif kind == "month_start":
                target = ref.replace(day=1).strftime("%Y-%m-%d")
            elif kind == "year_start":
                target = ref.replace(month=1, day=1).strftime("%Y-%m-%d")
            else:
                target = _fmt_date(ref)

            def _repl(m: re.Match[str], t: str = target) -> str:
                changes.append(NormChange("temporal", m.group(0), t))
                return t

            text = pat.sub(_repl, text)
        return text

    def _pass7(
        self,
        text: str,
        ref: datetime,
        changes: list[NormChange],
        _original: str,
    ) -> str:
        for pat, offset, _kind in self._P7_PATTERNS:
            target = _fmt_date(ref + timedelta(days=offset))

            def _repl(m: re.Match[str], t: str = target) -> str:
                changes.append(NormChange("temporal", m.group(0), t))
                return t

            text = pat.sub(_repl, text)
        return text


# ======================== Helper ========================


def _extract_weekday(matched: str) -> str | None:
    """Extract the weekday key from a full prefix+weekday match string."""
    for key in sorted(WEEKDAY_MAP.keys(), key=len, reverse=True):
        if key in matched:
            return key
    return None
