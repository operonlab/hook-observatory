"""Unit tests for Phase 1 of authority-aware retrieval.

Covers two helpers in contextual_chunk.py and the module-level
ROLE_FACTOR / DEFAULT_DOC_WEIGHT constants used by jina_rerank.py.
Tests load both files via importlib to bypass FastAPI import chain,
so they run in any environment with stdlib only.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTEXTUAL_CHUNK = REPO_ROOT / "core/src/modules/docvault/ops/contextual_chunk.py"
JINA_RERANK = REPO_ROOT / "core/src/modules/docvault/ops/jina_rerank.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cc():
    return _load_module("cc_under_test", CONTEXTUAL_CHUNK)


@pytest.fixture(scope="module")
def jr():
    # Stub out src.shared.rerank_utils so jina_rerank can import.
    src_pkg = types.ModuleType("src")
    src_pkg.__path__ = []  # type: ignore[attr-defined]
    shared_pkg = types.ModuleType("src.shared")
    shared_pkg.__path__ = []  # type: ignore[attr-defined]
    ru = types.ModuleType("src.shared.rerank_utils")

    async def _fake_rerank(*_args, **_kwargs):
        return []

    ru.rerank_generic = _fake_rerank
    sys.modules.setdefault("src", src_pkg)
    sys.modules.setdefault("src.shared", shared_pkg)
    sys.modules.setdefault("src.shared.rerank_utils", ru)
    return _load_module("jr_under_test", JINA_RERANK)


# ----------------- source_role extraction -----------------


@pytest.mark.parametrize(
    "heading,expected",
    [
        ("## Invariant", "invariant"),
        ("### I1", "invariant"),
        ("### I12b", "invariant"),
        ("### I12c", "invariant"),
        ("### I123abc", "invariant"),
        ("## Open Decision", "open-decision"),
        ("### Fallback", "fallback"),
        ("## Fallback", "fallback"),
        ("## 為什麼", "decision-rationale"),
        ("## 為什麼如此設計", "decision-rationale"),
        ("## 相關段落", "reference"),
        ("## 依據", "reference"),
        ("## 其他標題", "raw-note"),
        (None, "raw-note"),
        ("", "raw-note"),
    ],
)
def test_source_role_extraction(cc, heading, expected):
    assert cc._extract_source_role(heading) == expected


# ----------------- doc_weight extraction -----------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/repo/00-prd.md", 1.0),
        ("/repo/00-spec.md", 1.0),
        ("/repo/00-glossary.md", 1.0),
        ("/repo/changelog/blueprint-amendments/AMD-001.md", 1.0),
        ("/repo/02-organized/tech/02-direction-seeds.md", 0.95),
        ("/repo/02-organized/tech/03-poc-gates.md", 0.95),
        ("/repo/02-organized/tech/07-capability-deep-dive.md", 0.85),
        ("/repo/02-organized/tech/13-cross-cutting-open-decisions.md", 0.85),
        ("/repo/01-scattered/story-scattered.md", 0.4),
        ("/repo/00-source/KAS-說明.md", 0.1),
        ("/repo/random/path.md", 0.7),
        (None, 0.7),
        ("", 0.7),
    ],
)
def test_doc_weight_extraction(cc, path, expected):
    assert cc._extract_doc_weight(path) == pytest.approx(expected)


# ----------------- rerank reweighting arithmetic -----------------


def test_role_factor_table_complete(jr):
    """Every source_role value emitted by contextual_chunk must have a factor."""
    expected_roles = {
        "invariant",
        "open-decision",
        "decision-rationale",
        "reference",
        "fallback",
        "raw-note",
    }
    assert set(jr.ROLE_FACTOR.keys()) == expected_roles


def test_rerank_promotes_invariant_over_fallback(jr):
    """
    Core regression: invariant chunk at vector score 0.55 must outrank
    fallback chunk at vector score 0.85 after authority reweighting.
    """
    # invariant: 0.55 * 0.95 * 1.10 = 0.57475
    # fallback:  0.85 * 0.95 * 0.55 = 0.44413
    invariant_final = 0.55 * 0.95 * jr.ROLE_FACTOR["invariant"]
    fallback_final = 0.85 * 0.95 * jr.ROLE_FACTOR["fallback"]
    assert invariant_final > fallback_final


def test_default_factors_for_missing_metadata(jr):
    """Chunks without metadata fall back to defaults (back-compat)."""
    assert jr.DEFAULT_DOC_WEIGHT == 0.7
    assert jr.DEFAULT_ROLE_FACTOR == 1.0
    # Effective multiplier for no-metadata chunk == 0.7
    assert jr.DEFAULT_DOC_WEIGHT * jr.DEFAULT_ROLE_FACTOR == pytest.approx(0.7)


def test_fallback_demoted_below_neutral(jr):
    """
    fallback role_factor (0.55) × scattered doc_weight (0.4) = 0.22.
    Even a 1.0 vector score is suppressed below most non-fallback chunks.
    """
    fallback_at_scattered = 1.0 * 0.4 * jr.ROLE_FACTOR["fallback"]
    assert fallback_at_scattered < 0.25


def test_invariant_boost_does_not_explode(jr):
    """invariant max final = 1.0 * 1.0 * 1.10 = 1.10 (manageable upper bound)."""
    invariant_max = 1.0 * 1.0 * jr.ROLE_FACTOR["invariant"]
    assert invariant_max == pytest.approx(1.10)
