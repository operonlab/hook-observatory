"""Frozen metric scoring — quality x efficiency x brevity."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .config import FROZEN_EVALS_DIR, Config
from .executor import ExecutionResult, GoldenCase


@dataclass
class Score:
    quality: float  # 0-100, LLM-as-Judge
    efficiency: float  # 0-100, token efficiency
    brevity: float  # 0-100, SKILL.md conciseness
    composite: float  # weighted average

    def to_dict(self) -> dict:
        return {
            "quality": round(self.quality, 1),
            "efficiency": round(self.efficiency, 1),
            "brevity": round(self.brevity, 1),
            "composite": round(self.composite, 2),
        }


def load_frozen_judge_prompt() -> str:
    """Load the frozen LLM-as-Judge system prompt."""
    judge_path = FROZEN_EVALS_DIR / "quality_judge.txt"
    if judge_path.exists():
        return judge_path.read_text()
    # Fallback if not yet created
    return (
        "You are a quality evaluator for AI skill outputs. "
        "Score the output 0-100 based on the expected traits. "
        'Return ONLY a JSON object: {"score": N, "reason": "brief"}'
    )


def load_scoring_rubric() -> dict:
    """Load the frozen scoring rubric."""
    rubric_path = FROZEN_EVALS_DIR / "scoring_rubric.json"
    if rubric_path.exists():
        return json.loads(rubric_path.read_text())
    return {"quality": 0.6, "efficiency": 0.2, "brevity": 0.2}


def judge_quality(
    output: str,
    case: GoldenCase,
    config: Config,
) -> float:
    """Use LLM-as-Judge to score output quality against expected traits.

    Returns a score from 0-100.
    """
    judge_prompt = load_frozen_judge_prompt()
    traits_str = "\n".join(f"- {t}" for t in case.expected_traits)

    user_prompt = f"""## Task Input
{case.input}

## Expected Traits
{traits_str}

## Actual Output
{output}

Score this output 0-100 based on how well it satisfies the expected traits.
Return ONLY a JSON object: {{"score": N, "reason": "brief explanation"}}"""

    try:
        result = subprocess.run(  # noqa: S603
            [
                config.claude_bin,
                "-p",
                f"System: {judge_prompt}\n\nUser: {user_prompt}",
                "--model",
                config.judge_model,
                "--max-turns",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return 50.0  # neutral score on failure

        text = result.stdout.strip()
        # Try to parse JSON from response
        # Handle case where response includes markdown fences
        if "```" in text:
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    text = line
                    break

        # Find JSON object in response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            score = float(data.get("score", 50))
            return max(0.0, min(100.0, score))

        return 50.0

    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return 50.0


def compute_efficiency(
    results: list[ExecutionResult],
    baseline_tokens: int,
) -> float:
    """Compute token efficiency score (0-100).

    Higher score = fewer tokens used (relative to baseline).
    """
    if not results or baseline_tokens <= 0:
        return 50.0

    total_tokens = sum(r.token_count for r in results if r.success)
    if total_tokens <= 0:
        return 50.0

    avg_tokens = total_tokens / len([r for r in results if r.success])
    # Ratio: baseline / actual. > 1 means more efficient
    ratio = baseline_tokens / avg_tokens if avg_tokens > 0 else 1.0
    # Normalize to 0-100: ratio of 1.0 = 50, 2.0 = 100, 0.5 = 0
    score = min(100.0, max(0.0, ratio * 50.0))
    return score


def compute_brevity(current_lines: int, baseline_lines: int) -> float:
    """Compute SKILL.md brevity score (0-100).

    Shorter is better, but only if quality is maintained.
    """
    if baseline_lines <= 0:
        return 50.0

    ratio = baseline_lines / current_lines if current_lines > 0 else 1.0
    # ratio > 1 means current is shorter (good)
    # Normalize: 1.0 = 50, 1.5 = 75, 0.5 = 25
    score = min(100.0, max(0.0, ratio * 50.0))
    return score


def extract_tools_list(skill_md: str) -> set[str]:
    """Extract tools from YAML frontmatter."""
    import re

    match = re.search(r"^tools:\s*(.+)$", skill_md, re.MULTILINE)
    if not match:
        return set()
    raw = match.group(1).strip()
    return {t.strip() for t in raw.split(",") if t.strip()}


def check_capability_preserved(original_md: str, variant_md: str) -> bool:
    """Verify the variant didn't lose tools or key integrations.

    Returns True if capabilities are preserved, False if degraded.
    """
    original_tools = extract_tools_list(original_md)
    variant_tools = extract_tools_list(variant_md)

    # Tools must not decrease
    if original_tools and not original_tools.issubset(variant_tools):
        return False

    return True


def score_skill(
    exec_results: list[ExecutionResult],
    golden_cases: list[GoldenCase],
    skill_md_lines: int,
    baseline_tokens: int,
    baseline_lines: int,
    config: Config,
    original_md: str = "",
    variant_md: str = "",
) -> Score:
    """Compute the composite score for a skill variant.

    Three frozen dimensions:
    1. Quality: LLM-as-Judge per golden case (weighted average)
    2. Efficiency: Token consumption relative to baseline
    3. Brevity: SKILL.md line count relative to baseline

    Plus a capability guard: if tools list shrinks, score is zeroed.
    """
    # Capability guard: if tools were removed, reject immediately
    if original_md and variant_md:
        if not check_capability_preserved(original_md, variant_md):
            return Score(quality=0, efficiency=0, brevity=0, composite=0)
    weights = config.scoring_weights

    # Quality: weighted average of per-case judge scores
    quality_scores = []
    for result, case in zip(exec_results, golden_cases, strict=False):
        if result.success:
            q = judge_quality(result.output, case, config)
            quality_scores.append((q, case.weight))
        else:
            quality_scores.append((0.0, case.weight))

    total_weight = sum(w for _, w in quality_scores)
    quality = sum(s * w for s, w in quality_scores) / total_weight if total_weight > 0 else 0.0

    efficiency = compute_efficiency(exec_results, baseline_tokens)
    brevity = compute_brevity(skill_md_lines, baseline_lines)

    composite = (
        quality * weights.quality + efficiency * weights.efficiency + brevity * weights.brevity
    )

    return Score(
        quality=quality,
        efficiency=efficiency,
        brevity=brevity,
        composite=composite,
    )
