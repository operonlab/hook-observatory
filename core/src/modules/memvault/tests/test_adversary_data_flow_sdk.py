"""Adversary test — §2 SDK MemvaultClient data-flow contract.

Validates:
- list_blocks(include_invalid=True) → include_invalid param present in query
- list_blocks(include_invalid=False/default) → include_invalid param ABSENT
- recall(as_of=<str>) → as_of param present in query
- recall(no as_of) → as_of param ABSENT
- invalidate_block(id, reason, superseded_by_id=None) → correct endpoint + body omits superseded_by_id
- restore_block(id) → correct endpoint, body is {}

All pure unit tests — no HTTP.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(_WORKTREE_ROOT, "libs", "sdk-client"))


# ── §2.1 list_blocks include_invalid ────────────────────────────────────────


def test_sdk_list_blocks_include_invalid_true_adds_param():
    """include_invalid=True MUST send include_invalid param to API."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params=None):
        captured.append((path, dict(params or {})))
        return {"items": [], "total": 0}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.list_blocks(include_invalid=True)
    assert captured, "No GET call was made"
    _, params = captured[0]
    assert "include_invalid" in params, f"include_invalid missing from params: {params}"
    # Value must be truthy-string or boolean True
    val = params["include_invalid"]
    assert val in (True, "true", "True", "1"), f"Unexpected include_invalid value: {val}"


def test_sdk_list_blocks_include_invalid_false_omits_param():
    """include_invalid=False (default) MUST NOT send include_invalid to API."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params=None):
        captured.append((path, dict(params or {})))
        return {"items": [], "total": 0}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.list_blocks(include_invalid=False)
    assert captured
    _, params = captured[0]
    assert "include_invalid" not in params, (
        f"include_invalid=False must omit param, got: {params}"
    )


def test_sdk_list_blocks_default_omits_include_invalid():
    """Default call (no include_invalid kwarg) must not send include_invalid param."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params=None):
        captured.append((path, dict(params or {})))
        return {"items": [], "total": 0}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.list_blocks()
    assert captured
    _, params = captured[0]
    assert "include_invalid" not in params, (
        f"Default list_blocks must not send include_invalid, got: {params}"
    )


# ── §2.2 recall as_of ────────────────────────────────────────────────────────


def test_sdk_recall_with_as_of_sends_param():
    """recall(q, as_of='2026-04-01T00:00:00Z') → as_of MUST appear in query params."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params=None):
        captured.append((path, dict(params or {})))
        return {"results": []}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.recall("test query", as_of="2026-04-01T00:00:00Z")
    assert captured
    _, params = captured[0]
    assert "as_of" in params, f"as_of missing from params: {params}"
    assert "2026-04-01" in str(params["as_of"])


def test_sdk_recall_without_as_of_omits_param():
    """recall(q) with no as_of → as_of MUST NOT appear in query params."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params=None):
        captured.append((path, dict(params or {})))
        return {"results": []}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.recall("test query")
    assert captured
    _, params = captured[0]
    assert "as_of" not in params, f"as_of must be absent when not supplied: {params}"


def test_sdk_recall_as_of_none_omits_param():
    """recall(q, as_of=None) → as_of MUST NOT appear (None ≡ no time-travel)."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params=None):
        captured.append((path, dict(params or {})))
        return {"results": []}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.recall("test query", as_of=None)
    assert captured
    _, params = captured[0]
    assert "as_of" not in params, f"as_of=None must not appear in params: {params}"


# ── §2.3 invalidate_block ────────────────────────────────────────────────────


def test_sdk_invalidate_block_no_superseded_by_omits_key():
    """invalidate_block(id, reason='manual') — superseded_by_id omitted from body."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_post(self, path, body=None):
        captured.append((path, dict(body or {})))
        return {}

    MemvaultClient._post = _fake_post  # type: ignore[method-assign]
    client.invalidate_block("blk-abc", reason="manual")
    assert captured
    path, body = captured[0]
    assert "/blocks/blk-abc/invalidate" in path
    assert "superseded_by_id" not in body, (
        f"superseded_by_id=None must not appear in body: {body}"
    )
    assert body.get("reason") == "manual"


def test_sdk_invalidate_block_with_superseded_by_sends_it():
    """invalidate_block(id, superseded_by_id='blk-new') → body includes key."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_post(self, path, body=None):
        captured.append((path, dict(body or {})))
        return {}

    MemvaultClient._post = _fake_post  # type: ignore[method-assign]
    client.invalidate_block("blk-old", reason="superseded", superseded_by_id="blk-new")
    _, body = captured[0]
    assert body.get("superseded_by_id") == "blk-new"
    assert body.get("reason") == "superseded"


# ── §2.4 restore_block ───────────────────────────────────────────────────────


def test_sdk_restore_block_sends_empty_body():
    """restore_block(id) → POST /blocks/{id}/restore with empty body {}."""
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_post(self, path, body=None):
        captured.append((path, body if body is not None else {}))
        return {}

    MemvaultClient._post = _fake_post  # type: ignore[method-assign]
    client.restore_block("blk-xyz")
    assert captured
    path, body = captured[0]
    assert "/blocks/blk-xyz/restore" in path
    assert body == {} or body is None, f"Expected empty body, got: {body}"


# ── §13 regression: SDK still has recall / list_blocks signatures ────────────


def test_sdk_recall_method_exists():
    from sdk_client.memvault import MemvaultClient

    assert hasattr(MemvaultClient, "recall"), "recall method must exist on MemvaultClient"


def test_sdk_list_blocks_method_exists():
    from sdk_client.memvault import MemvaultClient

    assert hasattr(MemvaultClient, "list_blocks"), "list_blocks must exist on MemvaultClient"


def test_sdk_invalidate_block_method_exists():
    from sdk_client.memvault import MemvaultClient

    assert hasattr(MemvaultClient, "invalidate_block"), (
        "invalidate_block must exist on MemvaultClient"
    )


def test_sdk_restore_block_method_exists():
    from sdk_client.memvault import MemvaultClient

    assert hasattr(MemvaultClient, "restore_block"), (
        "restore_block must exist on MemvaultClient"
    )
