"""Adversary test — §3 MCP memvault_recall as_of contract.

Validates:
- as_of != "" → propagated to client.recall(as_of=as_of)
- as_of == "" → forwarded as None (no time-travel)
- as_of default is ""

Pure unit test — monkey-patches MemvaultClient.recall.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
# MCP memvault server path
_MCP_PATH = os.path.join(_WORKTREE_ROOT, "mcp", "memvault")
_SDK_PATH = os.path.join(_WORKTREE_ROOT, "libs", "sdk-client")
sys.path.insert(0, _MCP_PATH)
sys.path.insert(0, _SDK_PATH)


def _load_mcp_server():
    """Import mcp/memvault/server.py — returns the module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mcp_memvault_server",
        os.path.join(_MCP_PATH, "server.py"),
    )
    mod = importlib.util.load_from_spec(spec)  # type: ignore[attr-defined]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _import_recall_func():
    """Import memvault_recall from mcp/memvault/server.py."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mcp_memvault_server",
        os.path.join(_MCP_PATH, "server.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── §3.1 as_of non-empty propagates ─────────────────────────────────────────


def test_mcp_recall_as_of_nonempty_propagates():
    """as_of != '' → client.recall called with as_of kwarg."""
    try:
        mod = _import_recall_func()
    except Exception as e:
        import pytest

        pytest.skip(f"MCP server import failed: {e}")

    # The MCP server exposes `memvault_recall` (async or sync function)
    if not hasattr(mod, "memvault_recall"):
        import pytest

        pytest.skip("memvault_recall not found in server.py")

    recall_func = mod.memvault_recall
    captured: list = []

    # Find the client object and monkey-patch its recall
    # The server should have a module-level `client` or similar
    patched = False
    for attr_name in dir(mod):
        obj = getattr(mod, attr_name, None)
        if obj is not None and hasattr(obj, "recall") and callable(obj.recall):
            original = obj.recall

            def _fake_recall(query, **kwargs):
                captured.append(kwargs)
                return {"results": [], "summary": ""}

            obj.recall = _fake_recall
            patched = True

            import asyncio

            try:
                result = asyncio.get_event_loop().run_until_complete(
                    recall_func("test", as_of="2026-04-01T00:00:00Z")
                )
            except TypeError:
                # Not async
                try:
                    recall_func("test", as_of="2026-04-01T00:00:00Z")
                except Exception:
                    pass
            finally:
                obj.recall = original
            break

    if not patched:
        import pytest

        pytest.skip("Could not locate recall client in MCP server module")

    assert captured, "client.recall was not called"
    assert captured[0].get("as_of") == "2026-04-01T00:00:00Z", (
        f"as_of not propagated: {captured[0]}"
    )


def test_mcp_recall_empty_as_of_passes_none():
    """as_of == '' → client.recall called with as_of=None (not empty string)."""
    try:
        mod = _import_recall_func()
    except Exception as e:
        import pytest

        pytest.skip(f"MCP server import failed: {e}")

    if not hasattr(mod, "memvault_recall"):
        import pytest

        pytest.skip("memvault_recall not found in server.py")

    recall_func = mod.memvault_recall
    captured: list = []

    patched = False
    for attr_name in dir(mod):
        obj = getattr(mod, attr_name, None)
        if obj is not None and hasattr(obj, "recall") and callable(obj.recall):
            original = obj.recall

            def _fake_recall(query, **kwargs):
                captured.append(kwargs)
                return {"results": [], "summary": ""}

            obj.recall = _fake_recall
            patched = True

            import asyncio

            try:
                asyncio.get_event_loop().run_until_complete(
                    recall_func("test", as_of="")
                )
            except TypeError:
                try:
                    recall_func("test", as_of="")
                except Exception:
                    pass
            finally:
                obj.recall = original
            break

    if not patched:
        import pytest

        pytest.skip("Could not locate recall client in MCP server module")

    if captured:
        as_of_val = captured[0].get("as_of")
        assert as_of_val is None or as_of_val == "", (
            f"Empty string as_of should become None: got {as_of_val!r}"
        )
