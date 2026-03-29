"""Keep/Discard main loop — the AutoResearch core."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import DATA_DIR, LEDGER_PATH, STATION_DIR, Config
from .executor import execute_all_cases, load_golden_cases
from .mutator import mutate, select_theme
from .scorer import score_skill
from .selector import SkillTarget


@dataclass
class RoundResult:
    round: int
    theme: str
    verdict: str  # "keep" | "discard" | "error"
    baseline_score: float
    variant_score: float
    delta: float
    score_detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "round": self.round,
            "theme": self.theme,
            "verdict": self.verdict,
            "baseline_score": round(self.baseline_score, 2),
            "variant_score": round(self.variant_score, 2),
            "delta": round(self.delta, 2),
            "score_detail": self.score_detail,
        }


@dataclass
class EvolutionResult:
    skill_name: str
    rounds_run: int
    rounds_kept: int
    baseline_composite: float
    final_composite: float
    improvement: float
    best_theme: str
    round_results: list[RoundResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "rounds_run": self.rounds_run,
            "rounds_kept": self.rounds_kept,
            "baseline_composite": round(self.baseline_composite, 2),
            "final_composite": round(self.final_composite, 2),
            "improvement_pct": round(self.improvement, 1),
            "best_theme": self.best_theme,
            "rounds": [r.to_dict() for r in self.round_results],
        }


def backup_skill_md(skill_path: Path) -> str:
    """Backup original SKILL.md and return its content."""
    content = skill_path.read_text()
    backup_path = skill_path.with_suffix(".md.bak")
    backup_path.write_text(content)
    return content


def restore_skill_md(skill_path: Path):
    """Restore SKILL.md from backup."""
    backup_path = skill_path.with_suffix(".md.bak")
    if backup_path.exists():
        shutil.copy2(backup_path, skill_path)


def append_ledger(entry: dict):
    """Append an entry to the evolution ledger (cross-night learning)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ledger = []
    if LEDGER_PATH.exists():
        try:
            ledger = json.loads(LEDGER_PATH.read_text())
        except json.JSONDecodeError:
            ledger = []

    ledger.append(entry)

    # Keep last 500 entries to prevent unbounded growth
    if len(ledger) > 500:
        ledger = ledger[-500:]

    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))


def evolve_skill(skill: SkillTarget, config: Config, eval_budget: list[int]) -> EvolutionResult:
    """Run the AutoResearch keep/discard loop for a single skill.

    Args:
        skill: Target skill to evolve
        config: Evolution configuration
        eval_budget: Mutable list[int] with remaining eval calls (shared across skills)

    Returns:
        EvolutionResult with all round details
    """
    evolution_path = STATION_DIR / "evolution.md"
    golden_cases = load_golden_cases(skill.name)

    if not golden_cases:
        return EvolutionResult(
            skill_name=skill.name,
            rounds_run=0,
            rounds_kept=0,
            baseline_composite=0,
            final_composite=0,
            improvement=0,
            best_theme="none",
        )

    # Backup original
    original_content = backup_skill_md(skill.path)
    original_lines = len(original_content.splitlines())

    # Measure baseline
    baseline_results = execute_all_cases(skill.name, config)
    eval_budget[0] -= len(golden_cases)

    baseline_tokens = sum(r.token_count for r in baseline_results if r.success)
    baseline_avg_tokens = baseline_tokens // max(1, len([r for r in baseline_results if r.success]))

    baseline_score = score_skill(
        baseline_results,
        golden_cases,
        original_lines,
        baseline_avg_tokens,
        original_lines,
        config,
    )

    current_score = baseline_score
    current_content = original_content

    round_results: list[RoundResult] = []
    rounds_kept = 0
    best_theme = "none"
    best_delta = 0.0

    for round_num in range(1, config.max_rounds_per_skill + 1):
        # Budget check
        if eval_budget[0] <= 0:
            break

        # Select theme (avoids recently failed ones)
        theme = select_theme(round_num, [r.to_dict() for r in round_results])

        # Mutate
        variant = mutate(
            current_content,
            theme,
            config,
            evolution_path,
            round_num=round_num,
            prior_results=[r.to_dict() for r in round_results],
        )

        if variant is None:
            round_results.append(
                RoundResult(
                    round=round_num,
                    theme=theme,
                    verdict="error",
                    baseline_score=current_score.composite,
                    variant_score=0,
                    delta=0,
                )
            )
            continue

        # Apply variant
        skill.path.write_text(variant)
        variant_lines = len(variant.splitlines())

        # Execute with variant
        variant_results = execute_all_cases(skill.name, config)
        eval_budget[0] -= len(golden_cases)

        # Score variant (with capability guard)
        variant_score = score_skill(
            variant_results,
            golden_cases,
            variant_lines,
            baseline_avg_tokens,
            original_lines,
            config,
            original_md=original_content,
            variant_md=variant,
        )

        delta = variant_score.composite - current_score.composite

        if delta > 0:
            # KEEP — variant is better
            current_score = variant_score
            current_content = variant
            rounds_kept += 1
            verdict = "keep"

            if delta > best_delta:
                best_delta = delta
                best_theme = theme
        else:
            # DISCARD — restore previous version
            skill.path.write_text(current_content)
            verdict = "discard"

        rr = RoundResult(
            round=round_num,
            theme=theme,
            verdict=verdict,
            baseline_score=(
                current_score.composite
                if verdict == "discard"
                else (current_score.composite - delta)
            ),
            variant_score=variant_score.composite,
            delta=delta,
            score_detail=variant_score.to_dict(),
        )
        round_results.append(rr)

        # Record to ledger
        append_ledger(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "skill": skill.name,
                "round": round_num,
                "theme": theme,
                "verdict": verdict,
                "delta": round(delta, 2),
                "composite": round(variant_score.composite, 2),
                "detail": variant_score.to_dict(),
            }
        )

    # If no improvement, restore original
    if rounds_kept == 0:
        restore_skill_md(skill.path)

    # Clean up backup
    backup_path = skill.path.with_suffix(".md.bak")
    if backup_path.exists():
        backup_path.unlink()

    improvement = (
        ((current_score.composite - baseline_score.composite) / baseline_score.composite * 100)
        if baseline_score.composite > 0
        else 0
    )

    return EvolutionResult(
        skill_name=skill.name,
        rounds_run=len(round_results),
        rounds_kept=rounds_kept,
        baseline_composite=baseline_score.composite,
        final_composite=current_score.composite,
        improvement=improvement,
        best_theme=best_theme,
        round_results=round_results,
    )
