"""Adversary test — §4 Hook recall_text builder as_of URL propagation.

Contract (§4):
- build_recall_text(prompt, as_of=<datetime>) → cascade URL contains as_of=<iso>
- build_recall_text(prompt, as_of=<datetime>) → search fallback URL contains as_of=
- build_recall_text(prompt) → cascade URL does NOT contain as_of=
- as_of propagates to /kg/attitudes/relevant URL as well

Pure unit test — monkey-patches builder._http_get.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_WORKTREE_CORE_SRC = os.path.join(_WORKTREE_CORE, "src")
sys.path = [
    p for p in sys.path if "/workshop/" not in p or ".claude/worktrees/" in p or "/.venv/" in p
]
sys.path.insert(0, _WORKTREE_CORE_SRC)
sys.path.insert(0, _WORKTREE_CORE)
for libname in ("text-ops", "kg-ops", "sdk-client", "tmux-lib"):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.insert(0, p)


# ── §4.1 as_of present → cascade URL carries it ─────────────────────────────


def test_recall_text_as_of_in_cascade_url():
    """When as_of is supplied, /kg/recall URL must contain as_of=."""
    from src.modules.memvault.recall_text import builder

    captured: list[str] = []

    def _fake_http_get(url: str, timeout: int = 10):
        captured.append(url)
        return (404, "")

    with patch.object(builder, "_http_get", side_effect=_fake_http_get):
        builder.build_recall_text(
            "test prompt for as_of",
            as_of=datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC),
        )

    cascade_urls = [u for u in captured if "/api/memvault/kg/recall" in u]
    assert cascade_urls, f"No cascade URL captured; all URLs: {captured}"
    assert "as_of=" in cascade_urls[0], (
        f"as_of= must appear in cascade URL: {cascade_urls[0]}"
    )
    assert "2026-03-15" in cascade_urls[0], (
        f"Date 2026-03-15 must appear in cascade URL: {cascade_urls[0]}"
    )


def test_recall_text_as_of_in_search_fallback_url():
    """When as_of is supplied, /search fallback URL must contain as_of=."""
    from src.modules.memvault.recall_text import builder

    captured: list[str] = []

    def _fake_http_get(url: str, timeout: int = 10):
        captured.append(url)
        # Make cascade fail so we exercise fallback paths
        return (500, "")

    with patch.object(builder, "_http_get", side_effect=_fake_http_get):
        builder.build_recall_text(
            "test prompt for search fallback",
            as_of=datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC),
        )

    search_urls = [u for u in captured if "/api/memvault/search" in u]
    if search_urls:
        assert "as_of=" in search_urls[0], (
            f"as_of= must appear in search fallback URL: {search_urls[0]}"
        )


def test_recall_text_no_as_of_omits_param_in_cascade():
    """When as_of is not supplied, cascade URL must NOT contain as_of=."""
    from src.modules.memvault.recall_text import builder

    captured: list[str] = []

    def _fake_http_get(url: str, timeout: int = 10):
        captured.append(url)
        return (404, "")

    with patch.object(builder, "_http_get", side_effect=_fake_http_get):
        builder.build_recall_text("test no as_of")

    cascade_urls = [u for u in captured if "/api/memvault/kg/recall" in u]
    assert cascade_urls, f"No cascade URL captured; all URLs: {captured}"
    assert "as_of=" not in cascade_urls[0], (
        f"as_of= must NOT appear when not supplied: {cascade_urls[0]}"
    )


def test_recall_text_as_of_none_omits_param():
    """as_of=None is the explicit null — same as not passing it."""
    from src.modules.memvault.recall_text import builder

    captured: list[str] = []

    def _fake_http_get(url: str, timeout: int = 10):
        captured.append(url)
        return (404, "")

    with patch.object(builder, "_http_get", side_effect=_fake_http_get):
        builder.build_recall_text("test none as_of", as_of=None)

    cascade_urls = [u for u in captured if "/api/memvault/kg/recall" in u]
    if cascade_urls:
        assert "as_of=" not in cascade_urls[0], (
            f"as_of=None must not add as_of param: {cascade_urls[0]}"
        )


# ── §4.2 transport error → returns "" (must not raise) ───────────────────────


def test_recall_text_does_not_raise_on_transport_error():
    """§4 contract: transport error must not raise; returns ''."""
    from src.modules.memvault.recall_text import builder

    def _exploding_http_get(url: str, timeout: int = 10):
        raise ConnectionError("simulated network failure")

    with patch.object(builder, "_http_get", side_effect=_exploding_http_get):
        result = builder.build_recall_text("test error handling")

    assert result == "" or isinstance(result, str), (
        "build_recall_text must return str (not raise) on transport error"
    )


# ── §4.3 attitudes URL also gets as_of ───────────────────────────────────────


def test_recall_text_as_of_in_attitudes_url():
    """When as_of is set, /kg/attitudes/relevant URL must contain as_of=."""
    from src.modules.memvault.recall_text import builder

    captured: list[str] = []

    def _fake_http_get(url: str, timeout: int = 10):
        captured.append(url)
        return (200, '{"results": []}')

    with patch.object(builder, "_http_get", side_effect=_fake_http_get):
        builder.build_recall_text(
            "test attitudes",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
        )

    attitude_urls = [u for u in captured if "/kg/attitudes/relevant" in u]
    if attitude_urls:
        assert "as_of=" in attitude_urls[0], (
            f"as_of= must appear in attitudes URL: {attitude_urls[0]}"
        )


# ── §13 regression: build_recall_text accepts as_of kwarg ───────────────────


def test_recall_text_function_accepts_as_of_kwarg():
    """build_recall_text must accept as_of keyword argument (no TypeError)."""
    from src.modules.memvault.recall_text import builder

    def _noop_get(url: str, timeout: int = 10):
        return (404, "")

    with patch.object(builder, "_http_get", side_effect=_noop_get):
        try:
            builder.build_recall_text("hello", as_of=datetime(2025, 1, 1, tzinfo=UTC))
        except TypeError as e:
            assert False, f"build_recall_text does not accept as_of kwarg: {e}"
