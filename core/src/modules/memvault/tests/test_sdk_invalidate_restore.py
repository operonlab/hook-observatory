"""Unit test — SDK MemvaultClient invalidate_block / restore_block hit the right endpoints.

Pure unit test: stubs BaseClient._post so no Core API is needed.
"""

from __future__ import annotations

import os
import sys

# Path fixup — must point at THIS worktree's sdk-client, not main's, otherwise
# tests for new SDK methods would be evaluated against the unmodified copy.
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(_WORKTREE_ROOT, "libs", "sdk-client"))


def test_invalidate_block_calls_correct_endpoint():
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_post(self, path, body):
        captured.append((path, body))
        return {"status": "ok"}

    MemvaultClient._post = _fake_post  # type: ignore[method-assign]

    out = client.invalidate_block("blk-123", reason="manual")
    assert out == {"status": "ok"}
    path, body = captured[0]
    assert path == "/blocks/blk-123/invalidate"
    assert body == {"reason": "manual"}


def test_invalidate_block_passes_superseded_by():
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_post(self, path, body):
        captured.append((path, body))
        return {}

    MemvaultClient._post = _fake_post  # type: ignore[method-assign]
    client.invalidate_block("blk-1", reason="superseded", superseded_by_id="blk-2")
    _, body = captured[0]
    assert body == {"reason": "superseded", "superseded_by_id": "blk-2"}


def test_restore_block_calls_correct_endpoint():
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_post(self, path, body):
        captured.append((path, body))
        return {}

    MemvaultClient._post = _fake_post  # type: ignore[method-assign]
    client.restore_block("blk-x")
    path, body = captured[0]
    assert path == "/blocks/blk-x/restore"
    assert body == {}


def test_recall_passes_as_of_to_query_params():
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params):
        captured.append((path, params))
        return {"results": []}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.recall("foo", as_of="2026-04-01T00:00:00Z")
    _, params = captured[0]
    assert params.get("as_of") == "2026-04-01T00:00:00Z"


def test_list_blocks_passes_include_invalid_to_query_params():
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient.__new__(MemvaultClient)
    captured: list = []

    def _fake_get(self, path, params):
        captured.append((path, params))
        return {"items": []}

    MemvaultClient._get = _fake_get  # type: ignore[method-assign]
    client.list_blocks(include_invalid=True)
    _, params = captured[0]
    assert params.get("include_invalid") == "true"


if __name__ == "__main__":
    test_invalidate_block_calls_correct_endpoint()
    test_invalidate_block_passes_superseded_by()
    test_restore_block_calls_correct_endpoint()
    test_recall_passes_as_of_to_query_params()
    test_list_blocks_passes_include_invalid_to_query_params()
    print("ok 5/5")
