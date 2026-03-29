"""Prompt mutation engine — generates SKILL.md variants one theme at a time."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import MUTATION_THEMES, Config


def load_evolution_directions(evolution_path: Path) -> str:
    """Load human-authored evolution directions."""
    if evolution_path.exists():
        return evolution_path.read_text()
    return "Focus on simplification and clarity."


def build_mutation_prompt(
    skill_md: str,
    theme: str,
    evolution_directions: str,
    round_num: int,
    prior_results: list[dict] | None = None,
) -> str:
    """Build the prompt for the mutation LLM call."""
    prior_context = ""
    if prior_results:
        recent = prior_results[-3:]  # Last 3 rounds
        lines = []
        for r in recent:
            lines.append(
                f"  Round {r['round']}: theme={r['theme']}, "
                f"verdict={r['verdict']}, delta={r.get('delta', 'N/A')}"
            )
        prior_context = "\n\nPrior attempts (learn from these):\n" + "\n".join(lines)

    return f"""You are a skill prompt optimizer. Your task is to improve a SKILL.md file
by applying a single mutation theme.

## Mutation Theme: {theme}

Theme definitions:
- simplify: Remove lines/sections that don't affect output quality. Less is more.
- clarify: Make instructions more explicit and unambiguous.
- restructure: Reorder sections for better logical flow.
- example_tune: Adjust, add, or remove examples for better guidance.
- constraint: Add or adjust constraints to improve output consistency.

## Evolution Directions (from human author)
{evolution_directions}

## Rules
1. Only apply the "{theme}" theme — do not mix themes.
2. Preserve all YAML frontmatter (name, description, version, tools, io, etc.) exactly.
3. Never modify lines marked with MANDATORY or CRITICAL.
4. Never change the skill's fundamental purpose or io schema.
5. Keep the overall structure recognizable — this is refinement, not rewriting.
6. If simplifying, prefer removing redundant examples or verbose explanations.
7. Output ONLY the modified SKILL.md content — no explanation, no markdown fences.
{prior_context}

## Current SKILL.md (round {round_num})
{skill_md}

## Output
Return the improved SKILL.md content. Only the file content, nothing else."""


def mutate(
    skill_md: str,
    theme: str,
    config: Config,
    evolution_path: Path,
    round_num: int = 1,
    prior_results: list[dict] | None = None,
) -> str | None:
    """Generate a mutated version of the SKILL.md using the specified theme.

    Returns the mutated content, or None if mutation failed.
    """
    directions = load_evolution_directions(evolution_path)
    prompt = build_mutation_prompt(
        skill_md, theme, directions, round_num, prior_results
    )

    try:
        result = subprocess.run(  # noqa: S603
            [
                config.claude_bin, "-p", prompt,
                "--model", config.judge_model,
                "--max-turns", "1",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return None

        output = result.stdout.strip()

        # Strip markdown fences if present
        if output.startswith("```"):
            lines = output.split("\n")
            # Remove first and last fence lines
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            output = "\n".join(lines)

        # Validate: must still have frontmatter
        if not output.startswith("---"):
            return None

        # Validate: must have closing frontmatter delimiter
        rest = output[3:]
        if "---" not in rest:
            return None

        return output

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def select_theme(round_num: int, prior_results: list[dict] | None = None) -> str:
    """Select mutation theme for this round.

    Cycles through themes, but avoids recently failed themes.
    """
    failed_themes = set()
    if prior_results:
        for r in prior_results[-len(MUTATION_THEMES):]:
            if r.get("verdict") == "discard":
                failed_themes.add(r.get("theme", ""))

    # Cycle through themes, skipping recently failed ones
    for offset in range(len(MUTATION_THEMES)):
        idx = (round_num - 1 + offset) % len(MUTATION_THEMES)
        theme = MUTATION_THEMES[idx]
        if theme not in failed_themes:
            return theme

    # All themes failed recently — just cycle
    return MUTATION_THEMES[(round_num - 1) % len(MUTATION_THEMES)]
