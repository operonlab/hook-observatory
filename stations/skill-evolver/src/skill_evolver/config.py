"""Configuration for Skill Evolution Engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STATION_DIR = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = Path.home() / ".claude" / "skills"
DATA_DIR = Path.home() / ".claude" / "data" / "skill-evolver"
FROZEN_EVALS_DIR = STATION_DIR / "frozen_evals"
GOLDEN_CASES_DIR = STATION_DIR / "golden_cases"
REPORTS_DIR = STATION_DIR / "reports"
LEDGER_PATH = DATA_DIR / "evolution_ledger.json"

# Mutation themes — each round picks one, never mixes
MUTATION_THEMES = [
    "simplify",      # Remove lines that don't affect quality
    "clarify",       # Make instructions more explicit
    "restructure",   # Reorder sections for better flow
    "example_tune",  # Adjust/add/remove examples
    "constraint",    # Tighten or relax constraints
]

# Skills that must never be evolved (system-level side effects)
NEVER_EVOLVE = frozenset({
    "envkit", "tmux-relay", "tmux-expert", "session-redactor",
    "session-intelligence", "system-monitor", "sentinel",
    "update-config", "create-skill", "create-command",
    "skill-publish", "skill-proxy",
})


@dataclass
class ScoringWeights:
    quality: float = 0.6
    efficiency: float = 0.2
    brevity: float = 0.2


@dataclass
class Config:
    max_skills_per_night: int = 5
    max_rounds_per_skill: int = 10
    max_eval_calls: int = 50  # hard ceiling
    scoring_weights: ScoringWeights = field(default_factory=ScoringWeights)
    judge_model: str = "claude-haiku-4-5-20251001"
    python_bin: str = str(Path.home() / ".local" / "bin" / "python3")
    anvil_bin: str = str(Path.home() / ".local" / "bin" / "anvil")
    claude_bin: str = "claude"

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        if path and path.exists():
            data = json.loads(path.read_text())
            weights = ScoringWeights(**data.pop("scoring_weights", {}))
            return cls(scoring_weights=weights, **data)
        return cls()

    def to_dict(self) -> dict:
        return {
            "max_skills_per_night": self.max_skills_per_night,
            "max_rounds_per_skill": self.max_rounds_per_skill,
            "max_eval_calls": self.max_eval_calls,
            "scoring_weights": {
                "quality": self.scoring_weights.quality,
                "efficiency": self.scoring_weights.efficiency,
                "brevity": self.scoring_weights.brevity,
            },
            "judge_model": self.judge_model,
        }
