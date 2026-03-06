"""
Verify-completion gate — SubagentStop handler.

Inspired by Trellis Ralph Loop: blocks sub-agent completion until
programmatic verification commands pass (lint, typecheck, test).

Config: `.verify.json` in project root (opt-in).

```json
{
  "commands": ["ruff check .", "pnpm run lint"],
  "max_iterations": 5,
  "timeout_minutes": 30
}
```

Only triggers for code-modifying agent types.
Tracks state in /tmp to prevent infinite loops.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time

from .base import ALLOW, HookResult, block, message, run_cmd

# Agent types that modify code and should be verified
_CODE_AGENTS = frozenset(
    {
        "worker",
        "designer",
        "foreman",
        "codex-dispatcher",
        "gemini-dispatcher",
        "copilot-dispatcher",
    }
)

# Agent types that are read-only — never verify
_SKIP_AGENTS = frozenset(
    {
        "explorer",
        "Explore",
        "Plan",
        "researcher",
        "reviewer",
        "browser",
        "media",
        "claude-code-guide",
        "writer",
        "statusline-setup",
    }
)

_DEFAULT_MAX_ITER = 5
_DEFAULT_TIMEOUT_MIN = 30
_CMD_TIMEOUT = 60  # per-command timeout in seconds


def _state_path(session_id: str, agent_id: str) -> str:
    key = f"{session_id}:{agent_id}"
    h = hashlib.sha256(key.encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f".verify-state-{h}.json")


def _load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: str, state: dict) -> None:
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def _find_verify_config(cwd: str) -> dict | None:
    """Find .verify.json in cwd or git root."""
    # Check cwd first
    candidate = os.path.join(cwd, ".verify.json")
    if os.path.isfile(candidate):
        try:
            with open(candidate) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    # Check git root if different from cwd
    result = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=cwd, timeout=5)
    if result and result.returncode == 0:
        git_root = result.stdout.strip()
        if git_root != cwd:
            candidate = os.path.join(git_root, ".verify.json")
            if os.path.isfile(candidate):
                try:
                    with open(candidate) as f:
                        return json.load(f)
                except (OSError, json.JSONDecodeError):
                    return None

    return None


def _run_verify(commands: list[str], cwd: str) -> list[dict]:
    """Run verify commands, return list of {cmd, passed, output}."""
    results = []
    for cmd in commands:
        r = run_cmd(cmd, cwd=cwd, timeout=_CMD_TIMEOUT)
        passed = r is not None and r.returncode == 0
        output = ""
        if r and not passed:
            output = (r.stdout or "") + (r.stderr or "")
            # Truncate to avoid huge block reasons
            if len(output) > 1500:
                output = output[:1500] + "\n... (truncated)"
        results.append({"cmd": cmd, "passed": passed, "output": output})
    return results


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if event_type != "SubagentStop":
        return ALLOW

    # Parse event data
    try:
        data = json.loads(raw_input) if raw_input.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        return ALLOW

    agent_type = data.get("agent_type", data.get("subagent_type", ""))
    agent_id = data.get("agent_id", "unknown")
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd", os.getcwd())

    # Only verify code-modifying agents
    if agent_type in _SKIP_AGENTS:
        return ALLOW
    if agent_type and agent_type not in _CODE_AGENTS:
        return ALLOW

    # Find verify config
    config = _find_verify_config(cwd)
    if not config or not config.get("commands"):
        return ALLOW

    commands = config["commands"]
    max_iter = config.get("max_iterations", _DEFAULT_MAX_ITER)
    timeout_min = config.get("timeout_minutes", _DEFAULT_TIMEOUT_MIN)

    # Load/init state
    sp = _state_path(session_id, agent_id)
    state = _load_state(sp)

    if not state:
        state = {"iteration": 0, "started_at": time.time(), "agent_id": agent_id}

    # Check limits — fail-open if exceeded
    elapsed_min = (time.time() - state.get("started_at", time.time())) / 60
    if state["iteration"] >= max_iter:
        _cleanup_state(sp)
        return message(
            f"[verify-completion] Max iterations ({max_iter}) reached. "
            "Allowing completion — please review manually."
        )
    if elapsed_min > timeout_min:
        _cleanup_state(sp)
        return message(
            f"[verify-completion] Timeout ({timeout_min}min) reached. "
            "Allowing completion — please review manually."
        )

    # Run verification
    results = _run_verify(commands, cwd)
    all_passed = all(r["passed"] for r in results)

    if all_passed:
        _cleanup_state(sp)
        return ALLOW

    # Some failed — block and report
    state["iteration"] += 1
    _save_state(sp, state)

    failed = [r for r in results if not r["passed"]]
    report_lines = [
        f"[verify-completion] Iteration {state['iteration']}/{max_iter} — "
        f"{len(failed)} command(s) failed:",
    ]
    for r in failed:
        report_lines.append(f"\n--- FAIL: {r['cmd']} ---")
        if r["output"]:
            report_lines.append(r["output"])

    report_lines.append(
        f"\nFix the issues and try again. ({max_iter - state['iteration']} attempts remaining)"
    )

    return block("\n".join(report_lines))


def _cleanup_state(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
