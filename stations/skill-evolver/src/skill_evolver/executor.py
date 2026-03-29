"""Execute a skill against golden test cases and collect results."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass

from .config import GOLDEN_CASES_DIR, Config


@dataclass
class ExecutionResult:
    case_id: str
    output: str
    token_count: int
    latency_ms: int
    success: bool
    error: str | None = None


@dataclass
class GoldenCase:
    id: str
    input: str
    expected_traits: list[str]
    weight: float = 1.0


def load_golden_cases(skill_name: str) -> list[GoldenCase]:
    """Load golden test cases for a skill."""
    cases_path = GOLDEN_CASES_DIR / skill_name / "cases.json"
    if not cases_path.exists():
        return []

    data = json.loads(cases_path.read_text())
    cases = data.get("cases", data) if isinstance(data, dict) else data
    return [
        GoldenCase(
            id=c["id"],
            input=c["input"],
            expected_traits=c["expected_traits"],
            weight=c.get("weight", 1.0),
        )
        for c in cases
    ]


def execute_skill(
    skill_name: str,
    case: GoldenCase,
    config: Config,
) -> ExecutionResult:
    """Execute a skill with a golden case input using claude CLI headless mode.

    Uses `claude -p` to run the skill and capture output.
    """
    prompt = (
        f"Use the /{skill_name} skill to process the following input. "
        f"Output only the skill's result, nothing else.\n\n"
        f"Input:\n{case.input}"
    )

    start = time.monotonic()
    try:
        result = subprocess.run(  # noqa: S603
            [
                config.claude_bin, "-p", prompt,
                "--model", config.judge_model,
                "--max-turns", "3",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if result.returncode != 0:
            return ExecutionResult(
                case_id=case.id,
                output="",
                token_count=0,
                latency_ms=elapsed_ms,
                success=False,
                error=result.stderr[:500] if result.stderr else "Non-zero exit",
            )

        output = result.stdout.strip()
        # Rough token estimate: ~4 chars per token
        token_estimate = len(output) // 4

        return ExecutionResult(
            case_id=case.id,
            output=output,
            token_count=token_estimate,
            latency_ms=elapsed_ms,
            success=True,
        )

    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ExecutionResult(
            case_id=case.id,
            output="",
            token_count=0,
            latency_ms=elapsed_ms,
            success=False,
            error="Execution timeout (180s)",
        )


def execute_all_cases(
    skill_name: str,
    config: Config,
) -> list[ExecutionResult]:
    """Execute all golden cases for a skill."""
    cases = load_golden_cases(skill_name)
    results = []
    for case in cases:
        result = execute_skill(skill_name, case, config)
        results.append(result)
    return results
