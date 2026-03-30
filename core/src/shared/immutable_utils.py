"""Immutable state utilities — structural sharing via immutables.Map.

Cannibalized from pystorex/immutable_utils.py. Provides zero-copy
snapshots and O(log32 n) updates for FeatureStore state.

Usage:
    from src.shared.immutable_utils import to_immutable, to_dict

    state = to_immutable({"count": 0, "items": [1, 2]})
    # → Map({"count": 0, "items": (1, 2)})

    new_state = state.set("count", 1)  # O(log32 n), shares structure

    plain = to_dict(new_state)
    # → {"count": 1, "items": [1, 2]}
"""

from __future__ import annotations

from immutables import Map


def to_immutable(obj):
    """Convert dict/list/value to immutable form.

    dict → Map, list → tuple, else passthrough.
    Already-immutable Map/tuple pass through without copy.
    """
    if isinstance(obj, Map):
        return obj
    if isinstance(obj, dict):
        return Map({k: to_immutable(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(to_immutable(v) for v in obj)
    return obj


def to_dict(obj):
    """Convert Map/tuple back to mutable dict/list.

    Inverse of to_immutable — for external consumers expecting plain dicts.
    """
    if isinstance(obj, Map):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [to_dict(v) for v in obj]
    return obj
