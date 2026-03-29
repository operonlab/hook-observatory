"""Skill Evolver SDK -- wraps the skill-evolver CLI via subprocess (no HTTP server).

Skill Evolver is a batch station for automated overnight skill optimization,
inspired by Karpathy's AutoResearch keep/discard loop.

Usage:
    from sdk_client.skill_evolver import SkillEvolverClient

    client = SkillEvolverClient()

    # Preview what would be evolved
    targets = client.dry_run()

    # Run evolution (1 skill, 2 rounds)
    results = client.run(max_skills=1, max_rounds=2)

    # Check latest report
    report = client.status()

    # View experiment ledger
    entries = client.ledger(last=10)
"""

import json
import os
import subprocess


class SkillEvolverError(Exception):
    """Raised when the skill-evolver CLI returns a non-zero exit code."""

    def __init__(self, message: str, returncode: int = 1):
        self.returncode = returncode
        super().__init__(message)


class SkillEvolverClient:
    """Skill Evolver SDK -- wraps the CLI via subprocess.

    Args:
        cli_path: Path to skill_evolver.py CLI.
        python: Python interpreter path.
        default_timeout: Default subprocess timeout in seconds.
    """

    def __init__(
        self,
        cli_path: str | None = None,
        python: str | None = None,
        default_timeout: int = 600,
    ):
        self.cli_path = cli_path or os.environ.get(
            "SKILL_EVOLVER_CLI",
            os.path.expanduser(
                "~/workshop/stations/skill-evolver/cli/skill_evolver.py"
            ),
        )
        self._python = python or os.environ.get(
            "PYTHON_PATH", "/Users/joneshong/.local/bin/python3"
        )
        self._default_timeout = default_timeout

    def _run(self, *args: str, timeout: int | None = None) -> str:
        """Run skill-evolver CLI and return stdout."""
        t = timeout or self._default_timeout
        try:
            result = subprocess.run(  # noqa: S603
                [self._python, self.cli_path, *args],
                capture_output=True,
                text=True,
                timeout=t,
            )
        except subprocess.TimeoutExpired as e:
            raise SkillEvolverError(
                f"Timeout after {t}s: skill-evolver {' '.join(args)}",
                returncode=-1,
            ) from e
        except FileNotFoundError as e:
            raise SkillEvolverError(
                f"CLI not found: {self.cli_path} (python: {self._python})",
                returncode=-1,
            ) from e

        if result.returncode != 0:
            msg = result.stderr.strip() or f"Exit code {result.returncode}"
            raise SkillEvolverError(msg, returncode=result.returncode)

        return result.stdout

    def dry_run(self, config: str | None = None) -> str:
        """Preview which skills would be evolved without running."""
        args = ["dry-run"]
        if config:
            args.extend(["--config", config])
        return self._run(*args, timeout=60)

    def run(
        self,
        max_skills: int | None = None,
        max_rounds: int | None = None,
        config: str | None = None,
        timeout: int = 900,
    ) -> list[dict]:
        """Run evolution loop. Returns JSON results.

        Default timeout is 900s (15 min) because each round involves
        ~13 claude -p calls (~30s each) for baseline + mutation + scoring.
        """
        args = ["run", "--json"]
        if max_skills:
            args.extend(["--max-skills", str(max_skills)])
        if max_rounds:
            args.extend(["--max-rounds", str(max_rounds)])
        if config:
            args.extend(["--config", config])
        output = self._run(*args, timeout=timeout)
        # JSON array is printed after text output. Find the first '[' and
        # parse everything from there to the end (multi-line JSON).
        idx = output.find("\n[")
        if idx >= 0:
            json_str = output[idx + 1:]  # skip the newline
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        # Fallback: try parsing the whole output
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []

    def status(self) -> str:
        """Show latest evolution report."""
        return self._run("status", timeout=30)

    def ledger(self, last: int = 20, as_json: bool = False) -> str | list[dict]:
        """Show evolution ledger entries."""
        args = ["ledger", "--last", str(last)]
        if as_json:
            args.append("--json")
            output = self._run(*args, timeout=30)
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return []
        return self._run(*args, timeout=30)
