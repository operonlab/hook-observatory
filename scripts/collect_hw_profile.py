#!/usr/bin/env python3
"""Collect hardware profile for the current machine and optionally compare two profiles.

Usage:
    # Collect and save current machine profile
    ~/.local/bin/python3 scripts/collect_hw_profile.py

    # Collect + run benchmark tasks (embedding, rerank)
    ~/.local/bin/python3 scripts/collect_hw_profile.py --bench

    # Compare two saved profiles
    ~/.local/bin/python3 scripts/collect_hw_profile.py \\
        --compare outputs/hw-profiles/mac-mini_2026-03-31.json \\
                  outputs/hw-profiles/rtx3090_2026-03-31.json

    # Print JSON to stdout only (no file write)
    ~/.local/bin/python3 scripts/collect_hw_profile.py --stdout
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Resolve workshop root (this script lives in scripts/)
WORKSHOP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSHOP_ROOT / "core" / "src"))

from shared.hardware_profile import BenchmarkResult, HardwareProfile, compare_profiles  # noqa: E402

OUTPUT_DIR = WORKSHOP_ROOT / "outputs" / "hw-profiles"


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------


def _bench_embedding(profile: HardwareProfile) -> None:
    """Benchmark embedding latency via the MLX embed_worker."""
    worker_path = Path.home() / ".venvs" / "omlx" / "embed_worker.py"
    if not worker_path.exists():
        print("  [skip] embed_worker.py not found", file=sys.stderr)
        return

    python = Path.home() / ".local" / "bin" / "python3"
    test_texts = ["The quick brown fox jumps over the lazy dog"] * 5
    payload = json.dumps({"texts": test_texts}) + "\n"

    try:
        t0 = time.perf_counter()
        proc = subprocess.run(  # noqa: S603
            [str(python), str(worker_path)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if proc.returncode != 0:
            print(f"  [skip] embed_worker failed: {proc.stderr[:200]}", file=sys.stderr)
            return

        throughput = len(test_texts) / (elapsed_ms / 1000)
        result = BenchmarkResult(
            task_type="embedding",
            model="mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ",
            latency_ms=round(elapsed_ms, 2),
            throughput=round(throughput, 2),
            timestamp=datetime.now(UTC).isoformat(),
        )
        profile.benchmarks.append(result)
        print(f"  embedding: {elapsed_ms:.1f}ms total, {throughput:.1f} texts/s")
    except subprocess.TimeoutExpired:
        print("  [skip] embedding benchmark timed out", file=sys.stderr)
    except Exception as e:
        print(f"  [skip] embedding benchmark error: {e}", file=sys.stderr)


def _bench_rerank(profile: HardwareProfile) -> None:
    """Benchmark reranker latency via the rerank_worker."""
    worker_path = Path.home() / ".venvs" / "omlx" / "rerank_worker.py"
    if not worker_path.exists():
        print("  [skip] rerank_worker.py not found", file=sys.stderr)
        return

    python = Path.home() / ".local" / "bin" / "python3"
    query = "machine learning hardware benchmarks"
    docs = [
        "Apple M-series chips use unified memory architecture.",
        "NVIDIA RTX 3090 has 24GB GDDR6X VRAM.",
        "The GPU is used for accelerating neural network inference.",
        "Python is a popular programming language.",
        "Workshop is a modular monolith backend.",
    ]
    payload = json.dumps({"query": query, "documents": docs}) + "\n"

    try:
        t0 = time.perf_counter()
        proc = subprocess.run(  # noqa: S603
            [str(python), str(worker_path)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if proc.returncode != 0:
            print(f"  [skip] rerank_worker failed: {proc.stderr[:200]}", file=sys.stderr)
            return

        throughput = len(docs) / (elapsed_ms / 1000)
        result = BenchmarkResult(
            task_type="rerank",
            model="jina-reranker-v3-mlx",
            latency_ms=round(elapsed_ms, 2),
            throughput=round(throughput, 2),
            timestamp=datetime.now(UTC).isoformat(),
        )
        profile.benchmarks.append(result)
        print(f"  rerank: {elapsed_ms:.1f}ms total, {throughput:.1f} docs/s")
    except subprocess.TimeoutExpired:
        print("  [skip] rerank benchmark timed out", file=sys.stderr)
    except Exception as e:
        print(f"  [skip] rerank benchmark error: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _collect(args: argparse.Namespace) -> HardwareProfile:
    print("Collecting hardware profile...")
    profile = HardwareProfile.collect_local()
    s = profile.system
    print(f"  hostname : {s.hostname}")
    print(f"  platform : {s.platform} / {s.arch}")
    print(f"  cpu      : {s.cpu_brand} ({s.cpu_cores} cores)")
    print(f"  ram      : {s.ram_gb} GB")
    print(f"  gpu      : {s.gpu.name} ({s.gpu.vram_mb:.0f} MB, {s.gpu.compute_type})")

    if args.bench:
        print("\nRunning benchmarks...")
        _bench_embedding(profile)
        _bench_rerank(profile)

    return profile


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect hardware profile and optionally compare two profiles."
    )
    parser.add_argument(
        "--bench",
        action="store_true",
        help="Run embedding + rerank benchmark tasks.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout only; skip saving to file.",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE", "TARGET"),
        help="Compare two saved profiles and print markdown report.",
    )
    args = parser.parse_args()

    # --- Compare mode ---
    if args.compare:
        baseline_path, target_path = args.compare
        print(f"Loading baseline: {baseline_path}")
        baseline = HardwareProfile.from_json(baseline_path)
        print(f"Loading target:   {target_path}")
        target = HardwareProfile.from_json(target_path)
        report = compare_profiles(baseline, target)
        print("\n" + report)
        return

    # --- Collect mode ---
    profile = _collect(args)

    if args.stdout:
        print("\n" + profile.to_json())
        return

    # Save to outputs/hw-profiles/{hostname}_{date}.json
    hostname = profile.system.hostname.replace(" ", "-").lower()
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    filename = f"{hostname}_{date_str}.json"
    out_path = OUTPUT_DIR / filename

    profile.save(out_path)
    print(f"\nSaved: {out_path}")
    print("Compare later with:")
    print(f"  python3 scripts/collect_hw_profile.py --compare {out_path} <other_profile.json>")


if __name__ == "__main__":
    main()
