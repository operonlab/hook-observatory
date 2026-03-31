#!/usr/bin/env python3
"""Scoring Pipeline Ablation Script.

Systematically disables each scoring stage one-at-a-time and measures
impact on recall quality. Adapted from TurboQuant+ layer-adaptive
methodology: stage sensitivity is highly non-uniform — find the ones
that actually matter.

Usage:
    cd /Users/joneshong/workshop
    uv run --project core python3 scripts/scoring_ablation.py
    uv run --project core python3 scripts/scoring_ablation.py \\
        --top-k 10 --output outputs/scoring-ablation/

Methodology:
  1. Baseline: Run all 10 stages → record top-K results per query
  2. Ablation: For each stage, disable it → re-run same queries
  3. Metrics:
     - overlap%:       % of baseline top-K that still appear in ablated top-K
     - rank_corr:      Kendall tau between baseline and ablated rankings
     - avg_score_delta: mean score change for results in both sets
     - filter_delta:   results added (positive) or removed (negative)
  4. Verdict: CRITICAL / IMPORTANT / MINOR / NEGLIGIBLE
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import math
import random
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: load scoring pipeline without importing FastAPI/DB modules
# ---------------------------------------------------------------------------

WORKSHOP_ROOT = Path(__file__).parent.parent
CORE_SRC = WORKSHOP_ROOT / "core" / "src"

sys.path.insert(0, str(CORE_SRC))

# Stub out package __init__.py files that pull in FastAPI/DB
for _pkg in ["src", "src.modules", "src.modules.memvault"]:
    if _pkg not in sys.modules:
        _m = types.ModuleType(_pkg)
        _m.__path__ = [str(CORE_SRC / _pkg.replace(".", "/"))]
        sys.modules[_pkg] = _m

import importlib.util  # noqa: E402


def _load(module_name: str, rel_path: str) -> types.ModuleType:
    file_path = CORE_SRC / rel_path
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec and spec.loader, f"Cannot load {file_path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_load("src.shared.reactive", "shared/reactive.py")
_load("src.shared.scoring_stages", "shared/scoring_stages.py")
_load("src.shared.access_tracker", "shared/access_tracker.py")
_load("src.modules.memvault.noise_filter", "modules/memvault/noise_filter.py")
_load("src.modules.memvault.source_tracker", "modules/memvault/source_tracker.py")
_load("src.modules.memvault.scoring_pipeline", "modules/memvault/scoring_pipeline.py")

from src.modules.memvault.scoring_pipeline import (  # noqa: E402
    ScoringConfig,
    ScoringPipeline,
)

# ---------------------------------------------------------------------------
# Benchmark queries — diverse set covering different recall scenarios
# ---------------------------------------------------------------------------

BENCHMARK_QUERIES: list[str] = [
    # Factual / technical
    "Python asyncio event loop best practices",
    "PostgreSQL partial unique index soft delete",
    "Redis Streams consumer group offset management",
    # Personal / reflective
    "what did I decide about the frontend architecture",
    "notes on memvault scoring pipeline design",
    "lessons learned from the cannibalization experiments",
    # Action / task oriented
    "outstanding tasks for the intelflow module",
    "deploy checklist for Workshop production",
    "Nginx reverse proxy configuration for stations",
    # Research / conceptual
    "Weibull decay memory forgetting curve rationale",
    "MMR diversity deduplication threshold choice",
    "TurboQuant layer sensitivity findings",
    # Short / ambiguous
    "auth",
    "feedback",
    "embedding dimensions",
]

# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

SAMPLE_CONTENTS = [
    "Python asyncio: use asyncio.gather() for parallel coroutines. Avoid blocking calls inside async functions.",  # noqa: E501
    "PostgreSQL soft delete pattern: add partial unique index with WHERE deleted_at IS NULL.",
    "Redis Streams: XREADGROUP with COUNT + NOACK for at-most-once, XACK for at-least-once delivery.",  # noqa: E501
    "Frontend architecture decision: TanStack Query for server state, Zustand for local UI state.",
    "Memvault scoring pipeline uses Weibull decay for memory forgetting — β=1.0 for exponential, β>1 for slow-then-fast.",  # noqa: E501
    "Cannibalization lesson: validate the core algorithm first before building the full system around it.",  # noqa: E501
    "Intelflow outstanding tasks: RSS feed deduplication, sentiment analysis integration, briefing summarizer.",  # noqa: E501
    "Workshop deploy: run ruff check, pnpm build, alembic upgrade, restart services via launchctl.",
    "Nginx proxy: auth_request /_v2_auth_check on all station endpoints, 401 redirects to /login.",
    "Weibull decay rationale: biological memory research shows non-exponential forgetting — initial rapid, then slower.",  # noqa: E501
    "MMR threshold 0.85: empirically chosen to balance diversity vs. precision in semantic search.",
    "TurboQuant key finding: last 8 layers account for all quality loss — layer sensitivity is non-uniform.",  # noqa: E501
    "Auth module: itsdangerous signed cookies, Redis session store, 7-day expiry.",
    "Feedback boost: tanh(net/3) gives smooth saturation — avoids runaway amplification.",
    "Embedding: nomic-embed-text 768d deprecated, now using Qwen3-Embedding-0.6B 1024d via MLX worker.",  # noqa: E501
    "Recency boost: exponential decay half_life=14 days, weight=0.15 — subtle nudge toward newer memories.",  # noqa: E501
    "Noise filter: greetings, status-only ack, raw JSON dumps, pure error traces all filtered at retrieval.",  # noqa: E501
    "Trust score calculation: base 0.5 + known session +0.2 + agent_id +0.1 + auto_extract +0.1 + recent +0.1.",  # noqa: E501
    "Length normalization: penalize both very short (<50 chars) and very long (>2000 chars) equally.",  # noqa: E501
    "MinScore 0.10: hard floor removes garbage similarity matches from vector search.",
    "FastAPI route pattern: routes.py does HTTP only, business logic in services.py (public API).",
    "Cronicle scheduler: sole runtime scheduler at port 4105, launchd only for boot-start.",
    "EventBus naming: {module}.{entity}.{past_tense} — always past tense, always immutable.",
    "WorkshopError hierarchy: NotFoundError 404, ForbiddenError 403, ConflictError 409.",
    "UUID v7 everywhere: time-sortable, database-index friendly, collision-safe.",
]

NOW = datetime.now(UTC)


def _make_embedding(seed: int, dim: int = 64) -> list[float]:
    """Generate a reproducible unit-norm embedding."""
    rng = random.Random(seed)  # noqa: S311
    raw = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw] if norm > 0 else raw


def _make_query_embedding(query: str, dim: int = 64) -> list[float]:
    """Query embedding: biased toward content embeddings that are relevant."""
    return _make_embedding(hash(query) % 10000, dim)


def _make_scored_dicts(
    query: str,
    n_results: int = 20,
    seed_offset: int = 0,
) -> list[dict]:
    """Generate realistic scored_dicts for a single query.

    Simulates what services.py returns from LanceDB vector search:
    varying ages, confidence levels, access patterns, feedback signals.
    """
    rng = random.Random(hash(query) + seed_offset)  # noqa: S311
    results = []

    for i in range(n_results):
        content = SAMPLE_CONTENTS[i % len(SAMPLE_CONTENTS)]
        # Age spans from 0 to 90 days — mix of fresh and stale
        age_days = rng.expovariate(1 / 20)  # mean 20 days
        created_at = NOW - timedelta(days=age_days)

        # Confidence: mostly high with some low
        confidence = rng.betavariate(4, 2)  # skewed toward high

        # Base similarity score from "vector search" — 0.3 to 0.95
        base_score = 0.30 + rng.random() * 0.65

        # Some have access history (G6 reinforcement)
        access_count = rng.choices([0, 1, 3, 10], weights=[0.5, 0.25, 0.15, 0.10])[0]
        last_accessed_at = None
        if access_count > 0:
            days_ago = rng.uniform(0, 30)
            last_accessed_at = NOW - timedelta(days=days_ago)

        # Feedback: mostly neutral, some positive or negative
        feedback_net = rng.choices([0, 1, 2, -1, -2], weights=[0.6, 0.2, 0.1, 0.07, 0.03])[0]

        # Embedding: content index as seed for reproducibility
        emb_seed = i + seed_offset
        embedding = _make_embedding(emb_seed)

        # Introduce some noise candidates
        noise_contents = [
            "Hi",
            "OK",
            "done",
            "好的",
            "收到",
            "Hello there!",
            "ok",
        ]
        if rng.random() < 0.08:  # 8% noise
            content = rng.choice(noise_contents)

        results.append(
            {
                "id": f"mem-{i:04d}-{abs(hash(query)) % 9999:04d}",
                "content": content,
                "score": base_score,
                "created_at": created_at,
                "confidence": confidence,
                "embedding": embedding,
                "access_count": access_count,
                "last_accessed_at": last_accessed_at,
                "feedback_net": feedback_net,
                # TrustBoostOp looks for r["block"] — leave as None to trigger neutral path
                "block": None,
            }
        )

    # Shuffle so ordering isn't deterministic before pipeline
    rng.shuffle(results)
    return results


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


async def run_pipeline(
    results: list[dict],
    query_embedding: list[float],
    skip_stage: str | None = None,
) -> tuple[list[dict], ScoringMetadata]:  # noqa: F821
    """Run scoring pipeline, optionally disabling one stage."""
    config = ScoringConfig()
    if skip_stage:
        config.stages_enabled[skip_stage] = False

    pipeline = ScoringPipeline(config)
    return await pipeline.apply(copy.deepcopy(results), query_embedding)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def kendall_tau(ranking_a: list[str], ranking_b: list[str]) -> float:
    """Compute Kendall tau rank correlation between two ID rankings.

    Only considers IDs present in BOTH lists. Returns 1.0 if fewer than 2
    common elements (trivially concordant).
    """
    common = [x for x in ranking_a if x in set(ranking_b)]
    if len(common) < 2:
        return 1.0

    # Reorder ranking_b to only common elements
    b_order = {x: i for i, x in enumerate(ranking_b) if x in set(common)}
    b_ranks = [b_order[x] for x in common]

    concordant = 0
    discordant = 0
    n = len(b_ranks)
    for i in range(n):
        for j in range(i + 1, n):
            if b_ranks[i] < b_ranks[j]:
                concordant += 1
            elif b_ranks[i] > b_ranks[j]:
                discordant += 1

    total = concordant + discordant
    return (concordant - discordant) / total if total > 0 else 1.0


def compute_metrics(
    baseline: list[dict],
    ablated: list[dict],
    top_k: int = 5,
) -> dict[str, float]:
    """Compute ablation impact metrics."""
    base_ids = [r["id"] for r in baseline[:top_k]]
    ablated_ids = [r["id"] for r in ablated[:top_k]]

    # Overlap %
    base_set = set(base_ids)
    ablated_set = set(ablated_ids)
    overlap = len(base_set & ablated_set) / max(len(base_set), 1) * 100

    # Rank correlation (Kendall tau)
    tau = kendall_tau(base_ids, ablated_ids)

    # Score delta for results in both full sets (not just top-K)
    base_scores = {r["id"]: r["score"] for r in baseline}
    ablated_scores = {r["id"]: r["score"] for r in ablated}
    common_ids = set(base_scores) & set(ablated_scores)
    if common_ids:
        avg_delta = sum(ablated_scores[i] - base_scores[i] for i in common_ids) / len(common_ids)
    else:
        avg_delta = 0.0

    # Filter impact: positive = more results, negative = fewer
    filter_delta = len(ablated) - len(baseline)

    return {
        "overlap_pct": overlap,
        "rank_corr": tau,
        "avg_score_delta": avg_delta,
        "filter_delta": filter_delta,
    }


# ---------------------------------------------------------------------------
# Verdict classification
# ---------------------------------------------------------------------------

STAGE_DISPLAY_NAMES = {
    "recency": "RecencyBoostOp",
    "importance": "ImportanceWeightOp",
    "trust_boost": "TrustBoostOp",
    "feedback_boost": "FeedbackBoostOp",
    "length_norm": "LengthNormOp",
    "time_decay": "TimeDecayOp",
    "semantic_boost": "SemanticBoostOp",
    "min_score": "MinScoreOp",
    "noise_filter": "NoiseFilterOp",
    "mmr": "MMROp",
}

ALL_STAGES = list(STAGE_DISPLAY_NAMES.keys())


def classify_verdict(metrics: dict[str, float]) -> str:
    """Classify stage importance based on combined impact metrics."""
    overlap = metrics["overlap_pct"]
    tau = metrics["rank_corr"]
    delta = abs(metrics["avg_score_delta"])
    filter_d = abs(metrics["filter_delta"])

    # CRITICAL: dramatically changes which results appear
    if overlap < 80 or tau < 0.70:
        return "CRITICAL"

    # IMPORTANT: notable changes in ranking or scores
    if overlap < 92 or tau < 0.85 or delta > 0.05 or filter_d >= 2:
        return "IMPORTANT"

    # MINOR: small measurable effect
    if overlap < 97 or tau < 0.95 or delta > 0.02 or filter_d >= 1:
        return "MINOR"

    return "NEGLIGIBLE"


def impact_score(metrics: dict[str, float]) -> float:
    """Composite impact score for sorting (higher = more impact)."""
    return (
        (100 - metrics["overlap_pct"]) * 0.40
        + (1 - metrics["rank_corr"]) * 100 * 0.35
        + abs(metrics["avg_score_delta"]) * 50 * 0.15
        + abs(metrics["filter_delta"]) * 2 * 0.10
    )


# ---------------------------------------------------------------------------
# Main ablation loop
# ---------------------------------------------------------------------------


async def run_ablation(
    queries: list[str],
    top_k: int = 5,
    n_results_per_query: int = 20,
    verbose: bool = False,
) -> dict[str, dict[str, float]]:
    """Run full ablation study: baseline + one ablation per stage."""
    print(f"Running ablation: {len(queries)} queries x {len(ALL_STAGES)} stages + baseline")
    print(f"  Top-K: {top_k}, Results per query: {n_results_per_query}")
    print()

    # Aggregate metrics across queries
    stage_aggregates: dict[str, list[dict[str, float]]] = {s: [] for s in ALL_STAGES}

    for q_idx, query in enumerate(queries):
        if verbose:
            print(f"  [{q_idx + 1:2d}/{len(queries)}] {query[:60]}")

        raw_results = _make_scored_dicts(
            query, n_results=n_results_per_query, seed_offset=q_idx * 100
        )
        query_emb = _make_query_embedding(query)

        # Baseline
        baseline_results, _ = await run_pipeline(raw_results, query_emb, skip_stage=None)

        # One ablation per stage
        for stage in ALL_STAGES:
            ablated_results, _ = await run_pipeline(raw_results, query_emb, skip_stage=stage)
            m = compute_metrics(baseline_results, ablated_results, top_k=top_k)
            stage_aggregates[stage].append(m)

    # Average across queries
    stage_metrics: dict[str, dict[str, float]] = {}
    for stage, measurements in stage_aggregates.items():
        n = len(measurements)
        stage_metrics[stage] = {
            "overlap_pct": sum(m["overlap_pct"] for m in measurements) / n,
            "rank_corr": sum(m["rank_corr"] for m in measurements) / n,
            "avg_score_delta": sum(m["avg_score_delta"] for m in measurements) / n,
            "filter_delta": sum(m["filter_delta"] for m in measurements) / n,
        }

    return stage_metrics


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    stage_metrics: dict[str, dict[str, float]],
    queries: list[str],
    top_k: int,
    date: str,
) -> str:
    """Generate Markdown ablation report."""
    # Sort by impact (most impactful first)
    ranked = sorted(stage_metrics.items(), key=lambda kv: impact_score(kv[1]), reverse=True)

    lines = [
        "# Scoring Pipeline Ablation Report",
        f"Date: {date}",
        f"Queries: {len(queries)} (diverse set)",
        f"Top-K: {top_k}",
        "Methodology: TurboQuant+ layer-adaptive (disable one stage at a time, measure recall impact)",  # noqa: E501
        "",
        "## Stage Impact Ranking",
        "",
        "| Rank | Stage | Class | Overlap% | Rank Corr | Avg Score Δ | Filter Δ | Verdict |",
        "|------|-------|-------|----------|-----------|-------------|----------|---------|",
    ]

    for rank, (stage, m) in enumerate(ranked, 1):
        display = STAGE_DISPLAY_NAMES[stage]
        verdict = classify_verdict(m)
        overlap = f"{m['overlap_pct']:.1f}%"
        tau = f"{m['rank_corr']:.3f}"
        delta = f"{m['avg_score_delta']:+.4f}"
        filter_d = f"{m['filter_delta']:+.1f}"
        lines.append(
            f"| {rank} | {display} | `{stage}` | {overlap} | {tau} | {delta} | {filter_d} | **{verdict}** |"  # noqa: E501
        )

    lines += [
        "",
        "## Verdict Legend",
        "",
        "| Verdict | Criteria |",
        "|---------|----------|",
        "| **CRITICAL** | overlap < 80% OR rank_corr < 0.70 — removing this stage dramatically changes results |",  # noqa: E501
        "| **IMPORTANT** | overlap < 92% OR tau < 0.85 OR |delta| > 0.05 OR |filter| >= 2 |",
        "| **MINOR** | overlap < 97% OR tau < 0.95 OR |delta| > 0.02 OR |filter| >= 1 |",
        "| **NEGLIGIBLE** | all metrics within noise — stage has minimal measurable effect |",
        "",
        "## Key Findings",
        "",
    ]

    # Summarize critical/important stages
    critical = [STAGE_DISPLAY_NAMES[s] for s, m in ranked if classify_verdict(m) == "CRITICAL"]
    important = [STAGE_DISPLAY_NAMES[s] for s, m in ranked if classify_verdict(m) == "IMPORTANT"]
    minor = [STAGE_DISPLAY_NAMES[s] for s, m in ranked if classify_verdict(m) == "MINOR"]
    negligible = [STAGE_DISPLAY_NAMES[s] for s, m in ranked if classify_verdict(m) == "NEGLIGIBLE"]

    if critical:
        lines.append(f"- **Critical stages** ({len(critical)}): {', '.join(critical)}")
        lines.append("  These stages should NEVER be disabled — they fundamentally reshape recall.")
    if important:
        lines.append(f"- **Important stages** ({len(important)}): {', '.join(important)}")
        lines.append("  Notable impact — worth keeping unless you have a specific reason to drop.")
    if minor:
        lines.append(f"- **Minor stages** ({len(minor)}): {', '.join(minor)}")
        lines.append("  Small but measurable effect — consider cost vs. benefit.")
    if negligible:
        lines.append(f"- **Negligible stages** ({len(negligible)}): {', '.join(negligible)}")
        lines.append(
            "  These stages have minimal measurable impact on synthetic data. "
            "Verify on real queries before disabling."
        )

    lines += [
        "",
        "## Methodology Notes",
        "",
        "- Synthetic data: 20 realistic scored_dicts per query, varying age/confidence/access/feedback",  # noqa: E501
        "- Embeddings: 64-dimensional synthetic unit vectors (reproducible via seed)",
        "- Metrics averaged across all queries for stability",
        "- Impact score: 0.4xoverlap_loss + 0.35xrank_loss + 0.15xscore_delta + 0.10xfilter_delta",
        "- **Caveat**: Synthetic data cannot fully replicate real memory distributions.",
        "  Run `/api/memvault/recall` with real queries to validate critical findings.",
        "",
        "## Per-Query Raw Data",
        "",
        "*(Run with `--verbose` to see per-query breakdown)*",
        "",
        "## Stage Details",
        "",
    ]

    for rank, (stage, m) in enumerate(ranked, 1):
        display = STAGE_DISPLAY_NAMES[stage]
        verdict = classify_verdict(m)
        lines += [
            f"### {rank}. {display} (`{stage}`)",
            f"- Verdict: **{verdict}**",
            f"- Top-{top_k} overlap: {m['overlap_pct']:.1f}%",
            f"- Rank correlation (Kendall τ): {m['rank_corr']:.3f}",
            f"- Avg score delta: {m['avg_score_delta']:+.4f}",
            f"- Filter delta: {m['filter_delta']:+.1f} results",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Memvault scoring pipeline ablation study",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-K results to compare for overlap and rank correlation",
    )
    parser.add_argument(
        "--n-results",
        type=int,
        default=20,
        help="Number of synthetic results per query",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(WORKSHOP_ROOT / "outputs" / "scoring-ablation"),
        help="Output directory for reports",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-query progress",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")

    print("=" * 60)
    print("Memvault Scoring Pipeline Ablation Study")
    print(f"Benchmark queries: {len(BENCHMARK_QUERIES)}")
    print(f"Output: {output_dir}")
    print("=" * 60)
    print()

    stage_metrics = await run_ablation(
        queries=BENCHMARK_QUERIES,
        top_k=args.top_k,
        n_results_per_query=args.n_results,
        verbose=args.verbose,
    )

    print()
    print("Ablation complete. Generating report...")

    report = generate_report(
        stage_metrics=stage_metrics,
        queries=BENCHMARK_QUERIES,
        top_k=args.top_k,
        date=date_str,
    )

    # Save report
    report_path = output_dir / f"ablation-{date_str}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report saved: {report_path}")

    # Also print a compact summary table to stdout
    print()
    print("Summary (sorted by impact):")
    print(f"{'Rank':<5} {'Stage':<20} {'Overlap%':<10} {'Tau':<8} {'Score Δ':<10} {'Verdict'}")
    print("-" * 65)

    ranked = sorted(stage_metrics.items(), key=lambda kv: impact_score(kv[1]), reverse=True)
    for rank, (stage, m) in enumerate(ranked, 1):
        verdict = classify_verdict(m)
        print(
            f"{rank:<5} {STAGE_DISPLAY_NAMES[stage]:<20} "
            f"{m['overlap_pct']:>7.1f}%  "
            f"{m['rank_corr']:>6.3f}  "
            f"{m['avg_score_delta']:>+8.4f}  "
            f"{verdict}"
        )


if __name__ == "__main__":
    asyncio.run(main())
