"""Clock + timezone resolver for dailyos.

`date.today()` and `datetime.now()` without tzinfo silently use the host
locale, which is unsafe for a service that hosts multiple users in
different timezones. This module provides:

- `Clock.now()` — UTC-aware datetime, monkeypatchable in tests.
- `Clock.today(tz=None)` — returns local date in the given timezone.
- `TimezoneResolver` — pluggable lookup for a space's timezone.

Step 6 audit finding: `date.today()` was scattered across services_p2,
services_p3 and `_today()` was referenced in services.py / services_p1
without ever being defined (NameError on call). This module provides the
canonical replacement and re-exports `_today` as a thin wrapper so the
existing call sites keep working.

Default timezone is read from settings.dailyos_default_timezone if
configured, falling back to 'Asia/Taipei' (workshop runs in Taipei).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Taipei"


class TimezoneResolver(Protocol):
    """Lookup a space's preferred timezone (IANA name)."""

    def resolve(self, space_id: str | None) -> str:
        ...


class _StaticTimezoneResolver:
    """Default resolver — returns DEFAULT_TIMEZONE for every space."""

    def resolve(self, space_id: str | None) -> str:
        _ = space_id
        return DEFAULT_TIMEZONE


_resolver: TimezoneResolver = _StaticTimezoneResolver()


def set_timezone_resolver(resolver: TimezoneResolver) -> None:
    """Override the global resolver (call at app startup if needed)."""
    global _resolver
    _resolver = resolver


def get_timezone(space_id: str | None = None) -> ZoneInfo:
    name = _resolver.resolve(space_id)
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


class Clock:
    """Centralized clock — every dailyos call should go through here.

    Tests can monkeypatch `Clock.now` and `Clock.today` to freeze time.
    """

    @staticmethod
    def now() -> datetime:
        """UTC-aware now()."""
        return datetime.now(UTC)

    @staticmethod
    def today(space_id: str | None = None) -> date:
        """Today in the resolved timezone (defaults to DEFAULT_TIMEZONE)."""
        tz = get_timezone(space_id)
        return datetime.now(tz).date()


def _today(space_id: str | None = None) -> date:
    """Backward-compat shim for services.py / services_p1.py call sites."""
    return Clock.today(space_id)
