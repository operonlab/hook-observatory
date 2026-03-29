"""Select which skills to evolve based on Anvil data + evolution.md directives."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import NEVER_EVOLVE, SKILLS_DIR, STATION_DIR, Config


@dataclass
class SkillTarget:
    name: str
    path: Path
    priority: str  # "pinned" | "high-frequency" | "low-utility"
    invocations_7d: int = 0
    success_rate: float = 1.0


def parse_evolution_md(evolution_path: Path) -> tuple[list[str], set[str]]:
    """Parse evolution.md for pinned skills and exclusions."""
    pinned: list[str] = []
    excluded: set[str] = set()

    if not evolution_path.exists():
        return pinned, excluded

    text = evolution_path.read_text()
    section = None

    for line in text.splitlines():
        stripped = line.strip()
        if "指定進化" in stripped or "pinned" in stripped.lower():
            section = "pinned"
            continue
        elif "排除" in stripped or "exclude" in stripped.lower():
            section = "excluded"
            continue
        elif stripped.startswith("## "):
            section = None
            continue

        if section and stripped.startswith("- "):
            name = stripped.lstrip("- ").split("#")[0].split(",")[0].strip()
            if name:
                if section == "pinned":
                    pinned.append(name)
                else:
                    excluded.add(name)

    return pinned, excluded


def get_anvil_stats(config: Config) -> dict[str, dict]:
    """Fetch skill usage stats from Anvil CLI."""
    try:
        result = subprocess.run(  # noqa: S603
            [config.anvil_bin, "stats", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        # Extract top_skills from global stats
        stats = {}
        for item in data.get("top_skills", []):
            stats[item["skill_name"]] = {
                "invocations": item.get("count", 0),
                "success_rate": item.get("success_rate", 1.0),
            }
        return stats
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return {}


def has_golden_cases(skill_name: str) -> bool:
    """Check if a skill has golden test cases defined."""
    cases_dir = STATION_DIR / "golden_cases" / skill_name
    return (cases_dir / "cases.json").exists()


def is_evolvable(skill_name: str, excluded: set[str]) -> bool:
    """Check if a skill can be evolved (not in never-evolve or excluded list)."""
    if skill_name in NEVER_EVOLVE or skill_name in excluded:
        return False

    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        return False

    # Check for disable-model-invocation flag
    content = skill_path.read_text(errors="ignore")
    if "disable-model-invocation: true" in content[:500]:
        return False

    # Skip reference-only skills (prefix _ref-)
    if skill_name.startswith("_ref-"):
        return False

    return True


def select_skills(config: Config) -> list[SkillTarget]:
    """Select skills for tonight's evolution run.

    Priority order:
    1. Pinned skills from evolution.md (highest)
    2. High-frequency skills from Anvil stats (with golden cases)
    3. Up to max_skills_per_night total
    """
    evolution_path = STATION_DIR / "evolution.md"
    pinned, excluded = parse_evolution_md(evolution_path)
    anvil_stats = get_anvil_stats(config)

    selected: list[SkillTarget] = []
    seen: set[str] = set()

    # Phase 1: Pinned skills
    for name in pinned:
        if len(selected) >= config.max_skills_per_night:
            break
        if not is_evolvable(name, excluded):
            continue
        if not has_golden_cases(name):
            continue
        if name in seen:
            continue
        seen.add(name)
        stats = anvil_stats.get(name, {})
        selected.append(SkillTarget(
            name=name,
            path=SKILLS_DIR / name / "SKILL.md",
            priority="pinned",
            invocations_7d=stats.get("invocations", 0),
            success_rate=stats.get("success_rate", 1.0),
        ))

    # Phase 2: High-frequency skills with golden cases
    ranked = sorted(
        anvil_stats.items(),
        key=lambda x: x[1].get("invocations", 0),
        reverse=True,
    )
    for name, stats in ranked:
        if len(selected) >= config.max_skills_per_night:
            break
        if name in seen:
            continue
        if not is_evolvable(name, excluded):
            continue
        if not has_golden_cases(name):
            continue
        seen.add(name)
        selected.append(SkillTarget(
            name=name,
            path=SKILLS_DIR / name / "SKILL.md",
            priority="high-frequency",
            invocations_7d=stats.get("invocations", 0),
            success_rate=stats.get("success_rate", 1.0),
        ))

    return selected
