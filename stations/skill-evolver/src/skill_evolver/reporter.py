"""Generate evolution reports — the morning briefing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .config import REPORTS_DIR
from .runner import EvolutionResult


def generate_report(results: list[EvolutionResult], date_str: str | None = None) -> str:
    """Generate a Markdown evolution report."""
    if date_str is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")

    total_skills = len(results)
    total_rounds = sum(r.rounds_run for r in results)
    total_kept = sum(r.rounds_kept for r in results)
    improved = [r for r in results if r.improvement > 0]
    best = max(results, key=lambda r: r.improvement) if results else None

    lines = [
        f"# Skill Evolution Report — {date_str}",
        "",
        "## Summary",
        f"- Skills evolved: {len(improved)}/{total_skills}",
        f"- Total rounds: {total_rounds}",
        (
            f"- Mutations kept: {total_kept}"
            f" ({total_kept / total_rounds * 100:.0f}%)"
            if total_rounds > 0 else "- Mutations kept: 0"
        ),
        (
            f"- Best improvement: {best.skill_name}"
            f" (+{best.improvement:.1f}%)"
            if best and best.improvement > 0
            else "- No improvements this run"
        ),
        "",
        "## Detailed Results",
        "",
        "| Skill | Baseline | Final | Change | Kept/Total | Best Theme |",
        "|-------|----------|-------|--------|------------|------------|",
    ]

    for r in sorted(results, key=lambda x: -x.improvement):
        change = f"+{r.improvement:.1f}%" if r.improvement > 0 else f"{r.improvement:.1f}%"
        lines.append(
            f"| {r.skill_name} | {r.baseline_composite:.1f} | "
            f"{r.final_composite:.1f} | {change} | "
            f"{r.rounds_kept}/{r.rounds_run} | {r.best_theme} |"
        )

    # Per-skill round details for improved skills
    if improved:
        lines.extend(["", "## Round Details (improved skills only)", ""])

        for r in improved:
            lines.extend([
                f"### {r.skill_name}",
                "",
                "| Round | Theme | Verdict | Score | Delta |",
                "|-------|-------|---------|-------|-------|",
            ])
            for rr in r.round_results:
                lines.append(
                    f"| {rr.round} | {rr.theme} | {rr.verdict} | "
                    f"{rr.variant_score:.1f} | {rr.delta:+.2f} |"
                )
            lines.append("")

    # Learning insights from discarded rounds
    discarded_themes: dict[str, int] = {}
    for r in results:
        for rr in r.round_results:
            if rr.verdict == "discard":
                discarded_themes[rr.theme] = discarded_themes.get(rr.theme, 0) + 1

    if discarded_themes:
        lines.extend([
            "## Insights",
            "",
            "### Least effective themes (most discards)",
            "",
        ])
        for theme, count in sorted(discarded_themes.items(), key=lambda x: -x[1]):
            lines.append(f"- `{theme}`: {count} discards")
        lines.append("")

    lines.append(f"\n---\n*Generated at {datetime.now(UTC).isoformat()}*")
    return "\n".join(lines)


def save_report(results: list[EvolutionResult], date_str: str | None = None) -> Path:
    """Generate and save the report to disk."""
    if date_str is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = generate_report(results, date_str)
    report_path = REPORTS_DIR / f"evolution-{date_str}.md"
    report_path.write_text(report)
    return report_path
