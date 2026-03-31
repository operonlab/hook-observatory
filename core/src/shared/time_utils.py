"""Timezone-aware date helpers."""

from datetime import UTC, date, datetime

# Default timezone — server-local for now, configurable later
_DEFAULT_TZ = UTC


def today(tz=_DEFAULT_TZ) -> date:
    """Return today's date in the given timezone."""
    return datetime.now(tz).date()
