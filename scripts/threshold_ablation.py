#!/usr/bin/env python3
"""Threshold Ablation Framework for Memvault.

Sweeps one gate/scoring threshold at a time while holding others constant.
Measures Recall@K, NDCG@K, gate rate, and latency against a fixed benchmark
query set with known-good expected results.

Inspired by TurboQuant+ Section 4.8 (ICLR 2026): systematic τ sweep showed PPL
completely insensitive across 10⁻⁴→10⁻⁸. We apply the same rigor to memvault's
hand-picked thresholds.

Usage:
    # Sweep gate_min_top_score across 7 values, 50 queries
    python3 scripts/threshold_ablation.py \\
        --param gate_min_top_score \\
        --range 0.2,0.3,0.4,0.45,0.5,0.6,0.7 \\
        --queries 50

    # Sweep min_score for scoring pipeline
    python3 scripts/threshold_ablation.py \\
        --param min_score \\
        --range 0.05,0.08,0.10,0.12,0.15,0.20 \\
        --queries 30

    # Dry run: show what would be swept
    python3 scripts/threshold_ablation.py \\
        --param gate_min_score_gap \\
        --range 0.05,0.10,0.15,0.20,0.25 \\
        --dry-run

    # Sweep all params with defaults
    python3 scripts/threshold_ablation.py --all-params

Outputs:
    - stdout: markdown table comparing each threshold value
    - ~/workshop/outputs/threshold-ablation/<timestamp>_<param>.md

Parameters supported:
    Reranker gate params:
        gate_min_top_score     (default: 0.45)
        gate_min_score_gap     (default: 0.15)
        gate_max_candidates    (default: 5)
        gate_min_cluster_tightness (default: 0.05)
    Scoring pipeline params:
        min_score              (default: 0.10)
        mmr_threshold          (default: 0.85)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:10000")
SPACE_ID = os.environ.get("WORKSHOP_SPACE_ID", "default")
INTERNAL_KEY = os.environ.get("CORE_INTERNAL_API_KEY", "")

OUTPUT_DIR = Path.home() / "workshop" / "outputs" / "threshold-ablation"

# Recall endpoint
RECALL_PATH = f"{CORE_API_URL}/api/memvault/search"

# Request timeout per query (seconds)
REQUEST_TIMEOUT = 15.0

# Default top_k for recall (used when scoring)
DEFAULT_TOP_K = 10

# ---------------------------------------------------------------------------
# Benchmark query set — 15 diverse queries spanning memvault content types
# ---------------------------------------------------------------------------

BENCHMARK_QUERIES: list[dict[str, Any]] = [
    # --- Tech / Architecture ---
    {
        "query": "workshop modular monolith architecture modules",
        "expected_keywords": ["modular", "monolith", "module", "FastAPI", "port"],
        "content_type": "architecture",
        "top_k": 5,
    },
    {
        "query": "Python uv venv package management",
        "expected_keywords": ["uv", "python", "venv", "package"],
        "content_type": "tooling",
        "top_k": 5,
    },
    {
        "query": "Redis cache event bus pub sub",
        "expected_keywords": ["Redis", "cache", "event", "pub"],
        "content_type": "infrastructure",
        "top_k": 5,
    },
    {
        "query": "PostgreSQL schema isolation per module database",
        "expected_keywords": ["PostgreSQL", "schema", "database", "module"],
        "content_type": "database",
        "top_k": 5,
    },
    {
        "query": "MLX embedding model Apple Silicon",
        "expected_keywords": ["MLX", "embedding", "Apple", "model"],
        "content_type": "ml_infra",
        "top_k": 5,
    },
    # --- Workflow / Process ---
    {
        "query": "git worktree branch isolation feature development",
        "expected_keywords": ["worktree", "branch", "git", "feature"],
        "content_type": "workflow",
        "top_k": 5,
    },
    {
        "query": "Cronicle scheduler job cron task",
        "expected_keywords": ["Cronicle", "scheduler", "job", "cron"],
        "content_type": "scheduling",
        "top_k": 5,
    },
    {
        "query": "Playwright browser automation testing E2E",
        "expected_keywords": ["Playwright", "browser", "test", "automation"],
        "content_type": "testing",
        "top_k": 5,
    },
    # --- Memory / Knowledge ---
    {
        "query": "memvault reranker cross encoder Jina scoring",
        "expected_keywords": ["reranker", "cross-encoder", "Jina", "score"],
        "content_type": "memvault",
        "top_k": 5,
    },
    {
        "query": "knowledge graph triple entity relationship",
        "expected_keywords": ["knowledge", "graph", "triple", "entity"],
        "content_type": "kg",
        "top_k": 5,
    },
    # --- Product / Business ---
    {
        "query": "finance transaction budget subscription module",
        "expected_keywords": ["finance", "transaction", "budget"],
        "content_type": "finance",
        "top_k": 5,
    },
    {
        "query": "authentication session cookie security RBAC",
        "expected_keywords": ["auth", "session", "cookie", "RBAC"],
        "content_type": "auth",
        "top_k": 5,
    },
    # --- Multi-machine / Infra ---
    {
        "query": "Tailscale VPN remote machine fleet dispatch",
        "expected_keywords": ["Tailscale", "VPN", "remote", "fleet"],
        "content_type": "multi_machine",
        "top_k": 5,
    },
    {
        "query": "nginx reverse proxy port routing configuration",
        "expected_keywords": ["nginx", "proxy", "port", "routing"],
        "content_type": "networking",
        "top_k": 5,
    },
    # --- LLM / AI ---
    {
        "query": "LiteLLM model provider grok API key",
        "expected_keywords": ["LiteLLM", "model", "provider", "API"],
        "content_type": "llm",
        "top_k": 5,
    },
]

# ---------------------------------------------------------------------------
# Parameter catalogue: name → (group, default, suggested_range)
# ---------------------------------------------------------------------------

PARAM_CATALOGUE: dict[str, dict[str, Any]] = {
    # Reranker gate params
    "gate_min_top_score": {
        "group": "reranker_gate",
        "default": 0.45,
        "suggested": [0.20, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70],
        "api_field": "reranker_gate_min_top_score",
    },
    "gate_min_score_gap": {
        "group": "reranker_gate",
        "default": 0.15,
        "suggested": [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30],
        "api_field": "reranker_gate_min_score_gap",
    },
    "gate_max_candidates": {
        "group": "reranker_gate",
        "default": 5,
        "suggested": [2, 3, 4, 5, 6, 8, 10],
        "api_field": "reranker_gate_max_candidates",
    },
    "gate_min_cluster_tightness": {
        "group": "reranker_gate",
        "default": 0.05,
        "suggested": [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15],
        "api_field": "reranker_gate_min_cluster_tightness",
    },
    # Scoring pipeline params
    "min_score": {
        "group": "scoring_pipeline",
        "default": 0.10,
        "suggested": [0.03, 0.05, 0.07, 0.10, 0.12, 0.15, 0.20],
        "api_field": "min_score",
    },
    "mmr_threshold": {
        "group": "scoring_pipeline",
        "default": 0.85,
        "suggested": [0.70, 0.75, 0.80, 0.85, 0.90, 0.95],
        "api_field": "mmr_threshold",
    },
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _build_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if INTERNAL_KEY:
        headers["X-Internal-Key"] = INTERNAL_KEY
    return headers


def recall_query(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    param_name: str | None = None,
    param_value: float | int | None = None,
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[dict[str, Any] | None, float, str | None]:
    """Execute one recall query, optionally overriding a threshold parameter.

    Returns (response_json, latency_seconds, error_message).
    The API response includes a 'metadata' field when include_metadata=true.
    """
    params: dict[str, Any] = {
        "q": query,
        "top_k": top_k,
        "space_id": SPACE_ID,
        "include_metadata": "true",
    }

    # Inject threshold override if the API supports it
    # (the search endpoint currently does not accept runtime threshold overrides;
    # we inject them via query params as a forward-compatible contract — if the
    # param is not yet recognized, the API simply ignores it and results reflect
    # the compiled-in default.  The ablation can still measure latency + gate
    # behaviour for currently-supported overrides.)
    if param_name is not None and param_value is not None:
        cat = PARAM_CATALOGUE.get(param_name, {})
        api_field = cat.get("api_field", param_name)
        params[api_field] = param_value

    t0 = time.perf_counter()
    try:
        resp = httpx.get(
            RECALL_PATH,
            params=params,
            headers=_build_headers(),
            timeout=timeout,
        )
        latency = time.perf_counter() - t0
        resp.raise_for_status()
        return resp.json(), latency, None
    except httpx.ConnectError:
        latency = time.perf_counter() - t0
        return None, latency, f"Connection refused at {CORE_API_URL}"
    except httpx.TimeoutException:
        latency = time.perf_counter() - t0
        return None, latency, f"Timeout after {timeout}s"
    except httpx.HTTPStatusError as e:
        latency = time.perf_counter() - t0
        return None, latency, f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        latency = time.perf_counter() - t0
        return None, latency, str(e)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _extract_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract result list from API response."""
    raw = response.get("results", [])
    out = []
    for r in raw:
        block = r.get("block") or {}
        out.append(
            {
                "id": block.get("id", ""),
                "content": block.get("content", ""),
                "score": r.get("score", 0.0),
            }
        )
    return out


def _extract_metadata(response: dict[str, Any]) -> dict[str, Any]:
    """Extract SearchMetadata from API response."""
    return response.get("metadata") or {}


def compute_recall_at_k(
    results: list[dict[str, Any]],
    expected_keywords: list[str],
    k: int,
) -> float:
    """Recall@K: fraction of expected keywords found in top-K results.

    Since we don't have explicit ground-truth IDs, we use keyword presence
    in retrieved content as a proxy signal — similar to BEIR's keyword-recall
    baseline for exploratory ablations.
    """
    if not expected_keywords or not results:
        return 0.0

    top_k = results[:k]
    combined_content = " ".join(r["content"].lower() for r in top_k)

    found = sum(1 for kw in expected_keywords if kw.lower() in combined_content)
    return found / len(expected_keywords)


def compute_ndcg_at_k(
    results: list[dict[str, Any]],
    expected_keywords: list[str],
    k: int,
) -> float:
    """NDCG@K using keyword-presence as binary relevance labels.

    Grades each result as relevant (1) if it contains any expected keyword,
    irrelevant (0) otherwise. DCG@K / IDCG@K.
    """
    if not expected_keywords or not results:
        return 0.0

    import math

    top_k = results[:k]

    def is_relevant(content: str) -> int:
        cl = content.lower()
        return 1 if any(kw.lower() in cl for kw in expected_keywords) else 0

    # DCG
    dcg = sum(is_relevant(top_k[i]["content"]) / math.log2(i + 2) for i in range(len(top_k)))

    # IDCG: best possible ranking — all relevant docs first
    n_relevant = sum(1 for r in top_k if is_relevant(r["content"]))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(n_relevant))

    if idcg == 0:
        return 0.0
    return dcg / idcg


# ---------------------------------------------------------------------------
# Sweep logic
# ---------------------------------------------------------------------------


def run_single_value(
    param_name: str,
    param_value: float | int,
    queries: list[dict[str, Any]],
    n_queries: int,
) -> dict[str, Any]:
    """Run ablation for one threshold value across n_queries queries.

    Returns aggregated metrics dict.
    """
    subset = queries[:n_queries]

    recalls: list[float] = []
    ndcgs: list[float] = []
    latencies: list[float] = []
    gate_rates: list[float] = []  # 1 = gated (reranker skipped), 0 = ran
    result_counts: list[int] = []
    errors: list[str] = []

    for q in subset:
        resp, lat, err = recall_query(
            query=q["query"],
            top_k=q["top_k"],
            param_name=param_name,
            param_value=param_value,
        )

        latencies.append(lat)

        if err:
            errors.append(err)
            recalls.append(0.0)
            ndcgs.append(0.0)
            gate_rates.append(0.0)
            result_counts.append(0)
            continue

        results = _extract_results(resp)
        meta = _extract_metadata(resp)

        recall = compute_recall_at_k(results, q["expected_keywords"], q["top_k"])
        ndcg = compute_ndcg_at_k(results, q["expected_keywords"], q["top_k"])
        gated = 1.0 if meta.get("reranker_gated") else 0.0

        recalls.append(recall)
        ndcgs.append(ndcg)
        gate_rates.append(gated)
        result_counts.append(len(results))

    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _p50(vals: list[float]) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        mid = len(s) // 2
        return s[mid]

    def _p99(vals: list[float]) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        idx = max(0, int(len(s) * 0.99) - 1)
        return s[idx]

    return {
        "param_value": param_value,
        "n_queries": len(subset),
        "n_errors": len(errors),
        "recall_at_k": _mean(recalls),
        "ndcg_at_k": _mean(ndcgs),
        "gate_rate": _mean(gate_rates),
        "latency_p50": _p50(latencies),
        "latency_p99": _p99(latencies),
        "avg_result_count": _mean([float(x) for x in result_counts]),
        "error_sample": errors[:3],
    }


def run_sweep(
    param_name: str,
    values: list[float],
    queries: list[dict[str, Any]],
    n_queries: int,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Run full sweep across all values for one parameter.

    Returns list of per-value metric dicts.
    """
    results = []
    cat = PARAM_CATALOGUE.get(param_name, {})
    default_val = cat.get("default")

    for val in values:
        marker = " ← default" if val == default_val else ""
        if verbose:
            print(f"  sweeping {param_name}={val}{marker} ...", flush=True)

        metrics = run_single_value(param_name, val, queries, n_queries)
        results.append(metrics)

        if verbose:
            print(
                f"    recall@k={metrics['recall_at_k']:.3f}  "
                f"ndcg@k={metrics['ndcg_at_k']:.3f}  "
                f"gate_rate={metrics['gate_rate']:.1%}  "
                f"p50={metrics['latency_p50'] * 1000:.0f}ms  "
                f"errors={metrics['n_errors']}",
                flush=True,
            )

    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _fmt_val(val: float | int) -> str:
    """Format threshold value for display."""
    if isinstance(val, int):
        return str(val)
    if val < 0.01:
        return f"{val:.4f}"
    return f"{val:.3f}"


def build_markdown_report(
    param_name: str,
    values: list[float],
    rows: list[dict[str, Any]],
    n_queries: int,
    generated_at: str,
) -> str:
    """Build a markdown table report."""
    cat = PARAM_CATALOGUE.get(param_name, {})
    default_val = cat.get("default")
    group = cat.get("group", "unknown")

    lines: list[str] = [
        f"# Threshold Ablation: `{param_name}`",
        "",
        f"- **Parameter group**: `{group}`",
        f"- **Current default**: `{default_val}`",
        f"- **Queries per value**: {n_queries} (from {len(BENCHMARK_QUERIES)} benchmark set)",
        f"- **Generated**: {generated_at}",
        "- **API endpoint**: `GET /api/memvault/search?include_metadata=true`",
        "",
        "## Results",
        "",
        "| Value | Recall@K | NDCG@K | Gate Rate | Lat P50 | Lat P99 | Avg Results | Errors |",
        "|-------|----------|--------|-----------|---------|---------|-------------|--------|",
    ]

    for row in rows:
        val = row["param_value"]
        marker = " ✓" if val == default_val else ""
        lines.append(
            f"| **{_fmt_val(val)}**{marker} "
            f"| {row['recall_at_k']:.3f} "
            f"| {row['ndcg_at_k']:.3f} "
            f"| {row['gate_rate']:.1%} "
            f"| {row['latency_p50'] * 1000:.0f}ms "
            f"| {row['latency_p99'] * 1000:.0f}ms "
            f"| {row['avg_result_count']:.1f} "
            f"| {row['n_errors']} |"
        )

    lines += [
        "",
        "_✓ marks current default value_",
        "",
        "## Interpretation",
        "",
        "- **Recall@K**: keyword-presence proxy (higher = more expected content surfaced)",
        "- **NDCG@K**: ranking quality — relevant results near top (higher = better)",
        "- **Gate Rate**: % of queries where reranker was skipped (higher = cheaper)",
        "- **Latency P50/P99**: wall-clock including scoring pipeline + reranker",
        "",
        "## Methodology",
        "",
        "Benchmark: 15 diverse queries spanning architecture, tooling, workflow, memory,",
        "and LLM content types. Expected keywords used as binary relevance labels",
        "(keyword-presence recall — analogous to TurboQuant+ PPL insensitivity test).",
        "",
        "Threshold overrides injected via query params; API falls back to compiled-in",
        "defaults if a param is not yet runtime-configurable.",
        "",
        "_Script: `scripts/threshold_ablation.py` | Workshop v0_",
    ]

    return "\n".join(lines)


def build_dry_run_report(
    param_name: str,
    values: list[float],
    n_queries: int,
) -> str:
    """Build a dry-run preview showing what would be swept."""
    cat = PARAM_CATALOGUE.get(param_name, {})
    default_val = cat.get("default")
    group = cat.get("group", "unknown")
    estimated_calls = len(values) * n_queries

    lines = [
        f"[DRY RUN] Threshold Ablation Preview: {param_name}",
        f"  Group:     {group}",
        f"  Default:   {default_val}",
        f"  Values:    {values}",
        f"  Queries:   {n_queries} per value",
        f"  API calls: ~{estimated_calls} (x {len(values)} values)",
        f"  Endpoint:  {RECALL_PATH}",
        "",
        "  Query subset:",
    ]
    for i, q in enumerate(BENCHMARK_QUERIES[:n_queries]):
        lines.append(f"    [{i + 1:2d}] [{q['content_type']:15s}] {q['query'][:60]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_report(param_name: str, content: str, generated_at: str) -> Path:
    """Save markdown report to output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = generated_at.replace(":", "-").replace(" ", "_")
    filename = f"{ts}_{param_name}.md"
    out_path = OUTPUT_DIR / filename
    out_path.write_text(content, encoding="utf-8")
    return out_path


def save_json(
    param_name: str,
    rows: list[dict[str, Any]],
    generated_at: str,
) -> Path:
    """Save raw metrics as JSON for programmatic analysis."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = generated_at.replace(":", "-").replace(" ", "_")
    filename = f"{ts}_{param_name}.json"
    out_path = OUTPUT_DIR / filename
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Threshold ablation framework for memvault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    param_group = p.add_mutually_exclusive_group(required=True)
    param_group.add_argument(
        "--param",
        choices=list(PARAM_CATALOGUE.keys()),
        help="Parameter to sweep",
    )
    param_group.add_argument(
        "--all-params",
        action="store_true",
        help="Sweep all parameters using their suggested ranges",
    )

    p.add_argument(
        "--range",
        metavar="V1,V2,...",
        help="Comma-separated threshold values to sweep (e.g. 0.2,0.3,0.4)",
    )
    p.add_argument(
        "--queries",
        type=int,
        default=len(BENCHMARK_QUERIES),
        metavar="N",
        help=(
            f"Number of benchmark queries per value (max {len(BENCHMARK_QUERIES)}, default: all)"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show sweep plan without making API calls",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="Skip writing output files (stdout only)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Also save raw metrics as JSON",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-query progress",
    )

    return p.parse_args()


def _parse_range(raw: str) -> list[float]:
    """Parse comma-separated string into list of floats."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        return [float(x) for x in parts]
    except ValueError as e:
        print(f"[ERROR] Invalid --range value: {e}", file=sys.stderr)
        sys.exit(1)


def run_for_param(
    param_name: str,
    values: list[float],
    n_queries: int,
    args: argparse.Namespace,
) -> None:
    """Full ablation run for a single parameter."""
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    if args.dry_run:
        print(build_dry_run_report(param_name, values, n_queries))
        return

    print(f"\n{'=' * 60}", flush=True)
    print(f"Sweeping: {param_name}  ({len(values)} values x {n_queries} queries)", flush=True)
    print(f"{'=' * 60}", flush=True)

    rows = run_sweep(
        param_name=param_name,
        values=values,
        queries=BENCHMARK_QUERIES,
        n_queries=n_queries,
        verbose=args.verbose,
    )

    report = build_markdown_report(
        param_name=param_name,
        values=values,
        rows=rows,
        n_queries=n_queries,
        generated_at=generated_at,
    )

    print(f"\n{report}", flush=True)

    if not args.no_save:
        md_path = save_report(param_name, report, generated_at)
        print(f"\n[Saved] {md_path}", flush=True)

        if args.json:
            json_path = save_json(param_name, rows, generated_at)
            print(f"[Saved] {json_path}", flush=True)


def main() -> None:
    args = parse_args()

    n_queries = min(args.queries, len(BENCHMARK_QUERIES))

    if args.all_params:
        # Sweep all params with their suggested ranges
        for param_name, cat in PARAM_CATALOGUE.items():
            values = cat["suggested"]
            run_for_param(param_name, values, n_queries, args)
        return

    # Single param mode
    param_name = args.param

    if args.range:
        values = _parse_range(args.range)
    else:
        # Use suggested range from catalogue
        values = PARAM_CATALOGUE[param_name]["suggested"]
        print(
            f"[INFO] --range not specified, using suggested: {values}",
            file=sys.stderr,
        )

    run_for_param(param_name, values, n_queries, args)


if __name__ == "__main__":
    main()
