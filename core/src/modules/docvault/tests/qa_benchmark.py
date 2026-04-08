#!/Users/joneshong/.local/bin/python3
"""DocVault QA Benchmark Runner — systematic evaluation of retrieval + synthesis.

Usage:
    ~/.local/bin/python3 core/src/modules/docvault/tests/qa_benchmark.py
    ~/.local/bin/python3 ...qa_benchmark.py --test-set doc_a_claude_models
    ~/.local/bin/python3 ...qa_benchmark.py --output-dir outputs/docvault/benchmark
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from sdk_client.docvault import DocvaultClient

ANSWER_JUDGE_ENABLED = os.environ.get("DOCVAULT_ANSWER_JUDGE", "0") == "1"

TEST_SETS_DIR = Path(__file__).parent / "test_sets"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[5] / "outputs" / "docvault" / "benchmark"


@dataclass
class EvalResult:
    """Evaluation result for a single QA question."""

    question_id: str
    question: str
    question_type: str
    difficulty: str
    document: str
    expected_answer: str
    actual_answer: str
    keywords: list[str]
    keyword_hits: list[str]
    keyword_misses: list[str]
    keyword_hit_rate: float
    expected_confidence_range: list[float]
    actual_confidence: float | None
    confidence_in_range: bool
    citation_count: int
    latency_seconds: float
    is_negative: bool
    negative_correct: bool | None  # None if not a negative question
    crag_verdict: str | None
    passed: bool
    # LLM-as-Judge fields (populated when DOCVAULT_ANSWER_JUDGE=1)
    judge_score: float | None = None
    judge_reasoning: str | None = None
    judge_sub_scores: dict | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class BenchmarkReport:
    """Aggregate report across all questions."""

    results: list[EvalResult] = field(default_factory=list)
    total: int = 0
    passed: int = 0

    # Aggregate metrics
    answer_hit_rate: float = 0.0
    confidence_calibration: float = 0.0
    negative_detection_rate: float = 0.0
    number_accuracy: float = 0.0
    hallucination_rate: float = 0.0
    avg_latency: float = 0.0
    judge_avg_score: float | None = None  # LLM-as-Judge average (when enabled)

    # Breakdowns
    by_document: dict = field(default_factory=dict)
    by_type: dict = field(default_factory=dict)
    by_difficulty: dict = field(default_factory=dict)

    def compute(self):
        self.total = len(self.results)
        if not self.total:
            return

        # Answer Hit Rate: keyword hit rate averaged across all questions
        self.answer_hit_rate = sum(r.keyword_hit_rate for r in self.results) / self.total

        # Confidence Calibration: % where actual confidence is within expected range
        calibrated = sum(1 for r in self.results if r.confidence_in_range)
        self.confidence_calibration = calibrated / self.total

        # Negative Detection Rate
        negatives = [r for r in self.results if r.is_negative]
        if negatives:
            self.negative_detection_rate = sum(1 for r in negatives if r.negative_correct) / len(
                negatives
            )

        # Number Accuracy (number_verify type)
        number_qs = [r for r in self.results if r.question_type == "number_verify"]
        if number_qs:
            self.number_accuracy = sum(r.keyword_hit_rate for r in number_qs) / len(number_qs)

        # Hallucination Rate: questions where crag_verdict indicates low groundedness
        flagged = sum(1 for r in self.results if r.crag_verdict and "low" in r.crag_verdict.lower())
        self.hallucination_rate = flagged / self.total

        # Average Latency
        self.avg_latency = sum(r.latency_seconds for r in self.results) / self.total

        # LLM-as-Judge average
        judged = [r for r in self.results if r.judge_score is not None]
        if judged:
            self.judge_avg_score = sum(r.judge_score for r in judged) / len(judged)

        # Passed count
        self.passed = sum(1 for r in self.results if r.passed)

        # Breakdowns
        self.by_document = self._breakdown("document")
        self.by_type = self._breakdown("question_type")
        self.by_difficulty = self._breakdown("difficulty")

    def _breakdown(self, attr: str) -> dict:
        groups: dict[str, list[EvalResult]] = {}
        for r in self.results:
            key = getattr(r, attr)
            groups.setdefault(key, []).append(r)

        breakdown = {}
        for key, items in sorted(groups.items()):
            total = len(items)
            hit_rate = sum(r.keyword_hit_rate for r in items) / total
            avg_lat = sum(r.latency_seconds for r in items) / total
            passed = sum(1 for r in items if r.passed)
            breakdown[key] = {
                "total": total,
                "passed": passed,
                "hit_rate": round(hit_rate, 3),
                "avg_latency": round(avg_lat, 1),
            }
        return breakdown

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "answer_hit_rate": round(self.answer_hit_rate, 3),
                "confidence_calibration": round(self.confidence_calibration, 3),
                "negative_detection_rate": round(self.negative_detection_rate, 3),
                "number_accuracy": round(self.number_accuracy, 3),
                "hallucination_rate": round(self.hallucination_rate, 3),
                "avg_latency_seconds": round(self.avg_latency, 1),
                "judge_avg_score": round(self.judge_avg_score, 3)
                if self.judge_avg_score is not None
                else None,
            },
            "targets": {
                "answer_hit_rate": ">= 0.80",
                "confidence_calibration": ">= 0.70",
                "negative_detection_rate": ">= 0.90",
                "number_accuracy": ">= 0.70",
                "hallucination_rate": "<= 0.10",
                "avg_latency_seconds": "<= 30",
            },
            "by_document": self.by_document,
            "by_type": self.by_type,
            "by_difficulty": self.by_difficulty,
            "results": [r.to_dict() for r in self.results],
        }


def load_test_sets(filter_name: str | None = None) -> list[dict]:
    """Load test set JSON files from the test_sets directory."""
    questions = []
    for path in sorted(TEST_SETS_DIR.glob("*.json")):
        if filter_name and filter_name not in path.stem:
            continue
        with open(path) as f:
            data = json.load(f)
        for q in data["questions"]:
            q["_source_file"] = path.stem
        questions.extend(data["questions"])
    return questions


def check_keywords(answer: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    """Check which keywords appear in the answer (case-insensitive)."""
    answer_lower = answer.lower()
    hits = []
    misses = []
    for kw in keywords:
        if kw.lower() in answer_lower:
            hits.append(kw)
        else:
            misses.append(kw)
    return hits, misses


def check_negative(answer: str) -> bool:
    """Check if the answer correctly indicates the information is not in the document."""
    answer_lower = answer.lower()
    refusal_signals = [
        "not mention",
        "not include",
        "not contain",
        "does not",
        "no information",
        "not found",
        "not available",
        "not specified",
        "not discussed",
        "not covered",
        "not addressed",
        "cannot find",
        "cannot determine",
        "no relevant",
        "unable to find",
        "unable to answer",
        "未提及",
        "沒有提到",
        "沒有包含",
        "找不到",
        "無法",
        "未涵蓋",
        "not in the document",
        "not present",
        "insufficient",
        "i don't have",
    ]
    return any(sig in answer_lower for sig in refusal_signals)


def evaluate_question(case: dict, response: dict, latency: float) -> EvalResult:
    """Evaluate a single QA response against expected values."""
    answer = response.get("answer", "")
    confidence = response.get("confidence")
    citations = response.get("citations", [])
    crag_verdict = response.get("crag_verdict")

    keywords = case.get("keywords", [])
    hits, misses = check_keywords(answer, keywords)
    hit_rate = len(hits) / len(keywords) if keywords else 0.0

    expected_range = case.get("expected_confidence_range", [0, 1])
    confidence_val = confidence if isinstance(confidence, (int, float)) else 0.0
    in_range = expected_range[0] <= confidence_val <= expected_range[1]

    is_negative = case["type"] == "negative"
    negative_correct = None
    if is_negative:
        negative_correct = check_negative(answer)

    # A question passes if:
    # - negative: correctly refuses
    # - non-negative: keyword hit rate >= 0.5
    if is_negative:
        passed = negative_correct is True
    else:
        passed = hit_rate >= 0.5

    return EvalResult(
        question_id=case["id"],
        question=case["question"],
        question_type=case["type"],
        difficulty=case["difficulty"],
        document=case["document"],
        expected_answer=case["expected_answer"],
        actual_answer=answer,
        keywords=keywords,
        keyword_hits=hits,
        keyword_misses=misses,
        keyword_hit_rate=round(hit_rate, 3),
        expected_confidence_range=expected_range,
        actual_confidence=confidence_val,
        confidence_in_range=in_range,
        citation_count=len(citations),
        latency_seconds=round(latency, 1),
        is_negative=is_negative,
        negative_correct=negative_correct,
        crag_verdict=crag_verdict,
        passed=passed,
    )


async def _run_judge_batch(results: list[EvalResult], cases: list[dict], verbose: bool) -> None:
    """Run LLM-as-Judge evaluation on all results (async batch)."""
    from core.src.modules.docvault.ops.answer_judge import judge_answer

    if verbose:
        print("\n--- Running LLM-as-Judge evaluation ---")

    for result in results:
        if verbose:
            print(f"  Judging {result.question_id}...", end=" ", flush=True)
        try:
            judge_result = await judge_answer(
                question=result.question,
                expected_answer=result.expected_answer,
                actual_answer=result.actual_answer,
                is_negative=result.is_negative,
            )
            if judge_result:
                result.judge_score = judge_result.score
                result.judge_reasoning = judge_result.reasoning
                result.judge_sub_scores = judge_result.sub_scores.model_dump()
                # Override pass/fail with judge score when enabled
                if result.is_negative:
                    result.passed = judge_result.score >= 0.6
                else:
                    result.passed = judge_result.score >= 0.6
                if verbose:
                    print(f"score={judge_result.score:.2f}")
        except Exception as e:
            if verbose:
                print(f"ERROR: {e}")


def run_benchmark(
    client: DocvaultClient,
    questions: list[dict],
    verbose: bool = True,
) -> BenchmarkReport:
    """Run all questions through the QA API and evaluate results."""
    report = BenchmarkReport()

    for i, case in enumerate(questions, 1):
        qid = case["id"]
        question = case["question"]

        if verbose:
            print(f"\n[{i}/{len(questions)}] {qid}: {question[:60]}...")

        start = time.time()
        try:
            response = client.qa(question)
        except Exception as e:
            response = {"answer": f"ERROR: {e}", "confidence": 0.0, "citations": []}
        latency = time.time() - start

        result = evaluate_question(case, response, latency)
        report.results.append(result)

        if verbose:
            status = "PASS" if result.passed else "FAIL"
            print(
                f"  [{status}] hit={result.keyword_hit_rate:.0%} "
                f"conf={result.actual_confidence} lat={result.latency_seconds}s"
            )
            if result.keyword_misses:
                print(f"  Missing: {result.keyword_misses}")
            if result.is_negative:
                print(f"  Negative correct: {result.negative_correct}")

    # LLM-as-Judge batch evaluation (when enabled)
    if ANSWER_JUDGE_ENABLED:
        import asyncio

        asyncio.run(_run_judge_batch(report.results, questions, verbose))

    report.compute()
    return report


def print_summary(report: BenchmarkReport):
    """Print a human-readable summary of the benchmark results."""
    s = report.to_dict()["summary"]
    t = report.to_dict()["targets"]

    print("\n" + "=" * 60)
    print("DocVault QA Benchmark Report")
    print("=" * 60)
    print(f"\nTotal: {s['total']} | Passed: {s['passed']} | Failed: {s['total'] - s['passed']}")
    print()

    metrics = []
    if s.get("judge_avg_score") is not None:
        metrics.append(("LLM Judge Score", s["judge_avg_score"], ">= 0.60"))
    metrics += [
        ("Answer Hit Rate", s["answer_hit_rate"], t["answer_hit_rate"]),
        ("Confidence Calibration", s["confidence_calibration"], t["confidence_calibration"]),
        ("Negative Detection", s["negative_detection_rate"], t["negative_detection_rate"]),
        ("Number Accuracy", s["number_accuracy"], t["number_accuracy"]),
        ("Hallucination Rate", s["hallucination_rate"], t["hallucination_rate"]),
        ("Avg Latency (s)", s["avg_latency_seconds"], t["avg_latency_seconds"]),
    ]

    print(f"{'Metric':<25} {'Actual':>8} {'Target':>10}")
    print("-" * 45)
    for name, actual, target in metrics:
        if isinstance(actual, float) and actual <= 1.0 and name != "Avg Latency (s)":
            actual_str = f"{actual:.1%}"
        else:
            actual_str = f"{actual}"
        print(f"{name:<25} {actual_str:>8} {target:>10}")

    for label, breakdown in [
        ("By Document", report.by_document),
        ("By Type", report.by_type),
        ("By Difficulty", report.by_difficulty),
    ]:
        print(f"\n{label}:")
        for key, stats in breakdown.items():
            print(
                f"  {key:<20} {stats['passed']}/{stats['total']} pass  "
                f"hit={stats['hit_rate']:.0%}  lat={stats['avg_latency']}s"
            )

    # Failed questions detail
    failed = [r for r in report.results if not r.passed]
    if failed:
        print(f"\nFailed Questions ({len(failed)}):")
        for r in failed:
            print(f"  {r.question_id} [{r.question_type}] hit={r.keyword_hit_rate:.0%}")
            print(f"    Q: {r.question[:80]}")
            print(f"    Expected: {r.expected_answer[:80]}")
            print(f"    Actual: {r.actual_answer[:80]}")
            if r.keyword_misses:
                print(f"    Missing keywords: {r.keyword_misses}")


def main():
    parser = argparse.ArgumentParser(description="DocVault QA Benchmark Runner")
    parser.add_argument("--test-set", help="Filter to a specific test set (partial name match)")
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory for report"
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="HTTP timeout per request (seconds)"
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-question output")
    args = parser.parse_args()

    questions = load_test_sets(args.test_set)
    if not questions:
        print(f"No test sets found in {TEST_SETS_DIR}")
        sys.exit(1)

    print(f"Loaded {len(questions)} questions from {TEST_SETS_DIR}")

    client = DocvaultClient(timeout=args.timeout)

    report = run_benchmark(client, questions, verbose=not args.quiet)
    print_summary(report)

    # Save JSON report
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"benchmark_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
