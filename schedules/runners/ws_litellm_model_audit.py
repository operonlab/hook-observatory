#!/usr/bin/env python3
"""ws_litellm_model_audit.py — Daily LiteLLM model drift audit.

Why
---
LiteLLM upstream renames models without warning. Each rename silently
breaks every hardcoded ``model="..."`` reference in the codebase, and we
only notice when a hook starts timing out 17s on Gemini 429 retries.

This runner runs daily and:
  1. Queries LiteLLM ``/v1/models`` for the current model list.
  2. Loads ``core/src/shared/llm_policy.TASK_MODEL_PREFERENCES`` and
     flattens it into the "models we expect to exist" set.
  3. Greps the codebase for ``model="<name>"`` patterns to catch any
     hardcoded reference that bypassed the policy module.
  4. Diffs both expected sources against the live LiteLLM list and writes
     a JSON report. Exits non-zero when drift is detected so Cronicle
     surfaces the run as failed.

Report: ``~/workshop/outputs/litellm-audit/YYYY-MM-DD.json``
Log:    ``~/workshop/outputs/litellm-audit/logs/audit.log``
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Make `from src.shared.llm_policy import ...` work when run via cron.
HOME = Path.home()
WORKSHOP = HOME / "workshop"
sys.path.insert(0, str(WORKSHOP / "core"))

OUT_DIR = WORKSHOP / "outputs" / "litellm-audit"
LOG_DIR = OUT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "audit.log"

# Codebase roots to grep for hardcoded model strings.
CODEBASE_ROOTS = [
    WORKSHOP / "core" / "src",
    WORKSHOP / "scripts",
    WORKSHOP / "libs",
    WORKSHOP / "schedules" / "runners",
]

# Directories to skip even when nested under the roots.
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git", "_archive", ".worktrees"}

# Pattern matches model="<name>" or model='<name>' or sub_model="<name>".
# Restricted to provider-prefixed names so we don't sweep up unrelated strings.
PROVIDER_PREFIXES = (
    "gpt-",
    "gemini-",
    "claude-",
    "deepseek-",
    "qwen",
    "glm-",
    "kimi-",
    "moonshot-",
    "grok-",
    "minimax-",
    "nemotron",
)
MODEL_RE = re.compile(
    r'(?:sub_model|model)\s*=\s*[\"\']('
    + "|".join(re.escape(p) for p in PROVIDER_PREFIXES)
    + r')[\w.\-/]*[\"\']'
)


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001,S110 — log file write is best-effort
        pass


def scan_codebase_hardcoded() -> dict[str, list[str]]:
    """Return ``{model_name: [file:line, ...]}`` for every hardcoded reference."""
    findings: dict[str, list[str]] = {}
    for root in CODEBASE_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001 — skip files we can't read
                print(f"[audit] skip unreadable {path}: {exc}", flush=True)
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for match in MODEL_RE.finditer(line):
                    # Extract the quoted model name.
                    quoted = re.search(r'[\"\']([^\"\']+)[\"\']', match.group(0))
                    if not quoted:
                        continue
                    name = quoted.group(1)
                    findings.setdefault(name, []).append(
                        f"{path.relative_to(WORKSHOP)}:{lineno}"
                    )
    return findings


def main() -> int:
    _log("=== LiteLLM model drift audit start ===")

    # 1. Live model list.
    from src.shared.llm_policy import (  # type: ignore[import-not-found]
        all_referenced_models,
        clear_cache,
        fetch_available_models,
    )

    clear_cache()
    live = fetch_available_models()
    if not live:
        _log("ERROR: LiteLLM /v1/models unreachable or empty — audit aborted")
        return 2
    _log(f"LiteLLM serves {len(live)} models")

    # 2. Models the policy module expects to exist.
    policy_expected = all_referenced_models()
    _log(f"Policy expects {len(policy_expected)} models across all task tags")

    # 3. Hardcoded references in the codebase.
    hardcoded = scan_codebase_hardcoded()
    _log(f"Codebase has {len(hardcoded)} unique hardcoded model names")

    # 4. Diffs.
    policy_drift = sorted(policy_expected - live)
    hardcoded_drift = sorted(set(hardcoded.keys()) - live)
    extra_in_litellm = sorted(live - policy_expected - set(hardcoded.keys()))

    report = {
        "date": datetime.now().date().isoformat(),
        "timestamp": datetime.now().isoformat(),
        "litellm_serving_count": len(live),
        "litellm_serving": sorted(live),
        "policy_expected": sorted(policy_expected),
        "hardcoded_in_codebase": {k: sorted(v) for k, v in hardcoded.items()},
        "drift": {
            "policy_models_missing_from_litellm": policy_drift,
            "hardcoded_models_missing_from_litellm": [
                {"model": m, "locations": sorted(hardcoded[m])} for m in hardcoded_drift
            ],
            "litellm_models_not_used_anywhere": extra_in_litellm,
        },
    }

    out_file = OUT_DIR / f"{report['date']}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    _log(f"Report written: {out_file}")

    # 5. Surface drift.
    has_drift = bool(policy_drift or hardcoded_drift)
    if policy_drift:
        _log(f"⚠️  POLICY DRIFT: {policy_drift}")
    if hardcoded_drift:
        _log("⚠️  HARDCODED DRIFT — these will fail at runtime:")
        for m in hardcoded_drift:
            _log(f"    {m}: used at {hardcoded[m]}")
    if extra_in_litellm:
        _log(f"ℹ️  Unused models on LiteLLM (consider adding to policy): {extra_in_litellm}")

    _log(f"=== Audit done. drift={has_drift} ===")
    # Non-zero exit when hardcoded drift exists — Cronicle marks the job red.
    return 1 if hardcoded_drift else 0


if __name__ == "__main__":
    sys.exit(main())
