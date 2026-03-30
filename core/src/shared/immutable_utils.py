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


def update_in(map_obj: Map, path: list[str], updater_fn) -> Map:
    """Deep nested update on immutable Map, preserving structural sharing.

    Usage:
        state = to_immutable({"users": {"u1": {"name": "Bob"}}})
        new = update_in(state, ["users", "u1", "name"], lambda _: "Alice")
        # Only the path is copied, rest shares structure.
    """
    if not path:
        return map_obj

    key = path[0]

    if len(path) == 1:
        current = map_obj.get(key)
        new_value = updater_fn(current)
        if new_value is current:
            return map_obj
        return map_obj.set(key, to_immutable(new_value))

    # Recurse into nested Map
    current = map_obj.get(key, Map())
    if not isinstance(current, Map):
        current = to_immutable(current) if current is not None else Map()

    updated = update_in(current, path[1:], updater_fn)
    return map_obj.set(key, updated)


def batch_update(map_obj: Map, updates: dict) -> Map:
    """Batch-update multiple keys efficiently using Map evolver.

    Usage:
        new = batch_update(state, {"count": 5, "name": "Alice", "active": True})
    """
    e = map_obj.mutate()
    for k, v in updates.items():
        e[k] = to_immutable(v)
    return e.finish()
