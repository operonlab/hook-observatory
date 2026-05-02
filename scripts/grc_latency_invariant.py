"""GRC reflect latency invariant.

Catches regressions where latency does not scale linearly with items
(e.g., missing index, N+1 query). Replaces the old absolute 8s upper bound.

Rules (from contract):
- Skip per-item check when items_analyzed < 100 (wall-clock noise dominates).
- Per-item upper bound: elapsed_ms / items * 1000 <= 500 microseconds.
- Floor: elapsed_ms <= max(2000ms, items * 0.5ms).
"""

from __future__ import annotations

PER_ITEM_US_LIMIT = 500.0
FLOOR_BASE_MS = 2000.0
FLOOR_PER_ITEM_MS = 0.5
SMALL_ITEMS_THRESHOLD = 100


def check_grc_latency(elapsed_ms: float, items_analyzed: int) -> tuple[bool, str]:
    """Pure function: returns (passed, reason).

    Args:
        elapsed_ms: wall-clock duration of reflect call.
        items_analyzed: count of items the reflect endpoint processed.

    Returns:
        (True, reason) when invariant holds (or when intentionally skipped).
        (False, reason) when invariant violated.
    """
    if items_analyzed <= 0:
        return (True, f"skip:zero_items items={items_analyzed} elapsed_ms={elapsed_ms}")

    if items_analyzed < SMALL_ITEMS_THRESHOLD:
        return (
            True,
            f"skip:too_small items={items_analyzed} < {SMALL_ITEMS_THRESHOLD} "
            f"(wall-clock noise dominates)",
        )

    per_item_us = elapsed_ms / items_analyzed * 1000.0
    floor_ms = max(FLOOR_BASE_MS, items_analyzed * FLOOR_PER_ITEM_MS)

    if per_item_us > PER_ITEM_US_LIMIT:
        return (
            False,
            f"per_item_exceeded per_item_us={per_item_us:.2f} > {PER_ITEM_US_LIMIT} "
            f"(items={items_analyzed} elapsed_ms={elapsed_ms})",
        )

    if elapsed_ms > floor_ms:
        return (
            False,
            f"floor_exceeded elapsed_ms={elapsed_ms} > floor_ms={floor_ms} "
            f"(items={items_analyzed})",
        )

    return (
        True,
        f"ok per_item_us={per_item_us:.2f} elapsed_ms={elapsed_ms} "
        f"floor_ms={floor_ms} items={items_analyzed}",
    )
