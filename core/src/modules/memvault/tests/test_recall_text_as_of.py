"""Unit test — recall_text builder accepts as_of and propagates to URL params.

Pure unit test: stubs urllib.request.urlopen so no Core API is needed.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from unittest.mock import patch

# Path fixup
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_WORKTREE_CORE_SRC = os.path.join(_WORKTREE_CORE, "src")
sys.path.insert(0, _WORKTREE_CORE_SRC)
sys.path.insert(0, _WORKTREE_CORE)
for libname in ("text-ops", "kg-ops", "sdk-client", "tmux-lib"):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.insert(0, p)


def test_build_recall_text_accepts_as_of_kwarg():
    from src.modules.memvault.recall_text.builder import build_recall_text

    # Should not raise — signature includes as_of as keyword.
    out = build_recall_text("hello", as_of=datetime(2026, 4, 1, tzinfo=UTC))
    assert isinstance(out, str)


def test_build_recall_text_passes_as_of_to_cascade_url():
    """When as_of is supplied, the cascade-recall HTTP URL must include &as_of=."""
    from src.modules.memvault.recall_text import builder

    captured: list[str] = []

    def _fake_get(url: str, timeout: int = 10):
        captured.append(url)
        return (404, "")

    with patch.object(builder, "_http_get", side_effect=_fake_get):
        builder.build_recall_text(
            "look up X",
            as_of=datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC),
        )

    cascade_calls = [u for u in captured if "/api/memvault/kg/recall" in u]
    assert cascade_calls, f"no cascade URL captured: {captured!r}"
    assert "as_of=" in cascade_calls[0], cascade_calls[0]
    # ISO-8601 with timezone
    assert "2026-04-01" in cascade_calls[0]


def test_build_recall_text_omits_as_of_when_none():
    """as_of=None ⇒ URL should NOT carry an as_of param (present-time view)."""
    from src.modules.memvault.recall_text import builder

    captured: list[str] = []

    def _fake_get(url: str, timeout: int = 10):
        captured.append(url)
        return (404, "")

    with patch.object(builder, "_http_get", side_effect=_fake_get):
        builder.build_recall_text("look up X")

    cascade_calls = [u for u in captured if "/api/memvault/kg/recall" in u]
    assert cascade_calls
    assert "as_of=" not in cascade_calls[0], cascade_calls[0]


if __name__ == "__main__":
    test_build_recall_text_accepts_as_of_kwarg()
    test_build_recall_text_passes_as_of_to_cascade_url()
    test_build_recall_text_omits_as_of_when_none()
    print("ok 3/3")
