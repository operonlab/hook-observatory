"""Bitemporal predicate helper — single source of truth for "active block" filtering.

Replaces the scattered hand-written `MemoryBlock.deleted_at == None` /
`MemoryBlock.invalid_at IS NULL` patterns across services / kg_services /
sleeptime / dream / dedup / curate. Use this so the bitemporal contract
stays consistent everywhere, especially when adding new read paths.

Two modes:
  as_of=None  → "current view"  : deleted_at IS NULL AND invalid_at IS NULL
  as_of=T     → "time travel"   : full bitemporal — both transaction-time
                                  AND valid-time guards are applied.

The transaction-time guard (`created_at <= T`) prevents leaking blocks
that were ingested AFTER T but with a backdated valid_at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_

from .models import MemoryBlock


def active_block_filters(*, as_of: datetime | None = None) -> list[Any]:
    """Return WHERE clauses for active blocks.

    Args:
        as_of: None → current view; datetime → time-travel projection.

    Returns:
        list of SQLAlchemy conditions, ready to splat into `.where(*conditions)`.
    """
    if as_of is None:
        return [
            MemoryBlock.deleted_at.is_(None),
            MemoryBlock.invalid_at.is_(None),
        ]
    return [
        MemoryBlock.deleted_at.is_(None),
        # Transaction-time: the row must have existed at as_of
        MemoryBlock.created_at <= as_of,
        # Valid-time start: fact had started being true by as_of
        # (COALESCE handles legacy rows where valid_at was never extracted)
        func.coalesce(MemoryBlock.valid_at, MemoryBlock.created_at) <= as_of,
        # Valid-time end: fact had not yet been superseded at as_of
        or_(MemoryBlock.invalid_at.is_(None), MemoryBlock.invalid_at > as_of),
    ]
