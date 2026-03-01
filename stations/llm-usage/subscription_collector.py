#!/usr/bin/env python3
"""
Subscription Usage Collector — tracks membership-based CLI tool usage.

Collects usage data from:
- Claude Code: sysmon API (5h/7d window percentages)
- Codex CLI: session log parsing (best-effort)
- Gemini CLI: session log parsing (best-effort)

Usage:
    python3 subscription_collector.py                # Collect all
    python3 subscription_collector.py --provider cc  # Claude Code only
    python3 subscription_collector.py --output FILE  # Write to file
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def run(cmd: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


# ---------------------------------------------------------------------------
# Claude Code usage
# ---------------------------------------------------------------------------


def collect_claude_code(config: dict) -> dict:
    """Collect Claude Code subscription usage via sysmon API."""
    mp_cfg = config.get("model_policy", {})
    sub_cfg = config.get("subscriptions", {}).get("claude-code", {})

    result = {
        "provider": "anthropic",
        "cli": "claude-code",
        "plan": sub_cfg.get("plan", "max_5"),
        "monthly_cost_usd": sub_cfg.get("monthly_cost_usd", 100.00),
        "collected_at": datetime.now(UTC).isoformat(),
    }

    # Try sysmon API first (same source as model-policy)
    sysmon_url = mp_cfg.get("sysmon_url", "")
    cc_5h, cc_7d = _fetch_sysmon_usage(sysmon_url)

    if cc_5h is not None:
        result["quota_5h_pct"] = cc_5h
        result["quota_7d_pct"] = cc_7d
        result["source"] = "sysmon_api"
    else:
        # Fallback: read model-policy state.json
        state_path = Path(
            mp_cfg.get("state_path", "~/.claude/data/model-policy/state.json")
        ).expanduser()
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
            result["current_mode"] = state.get("mode", "unknown")
            result["mode_updated_at"] = state.get("updated_at")
            result["source"] = "state_file"
        else:
            result["source"] = "unavailable"

    # Count today's sessions from Claude project dirs
    session_count = _count_cc_sessions_today()
    if session_count is not None:
        result["sessions_today"] = session_count

    return result


def _fetch_sysmon_usage(url: str) -> tuple[int | None, int | None]:
    """Fetch CC usage from sysmon API."""
    if not url:
        return None, None
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        cc_5h = _parse_pct(data.get("llm_cc_5h", "?"))
        cc_7d = _parse_pct(data.get("llm_cc_7d", "?"))
        return cc_5h, cc_7d
    except Exception:
        return None, None


def _parse_pct(val: str) -> int | None:
    if isinstance(val, str) and val.endswith("%"):
        try:
            return int(val.rstrip("%"))
        except ValueError:
            pass
    if isinstance(val, (int, float)):
        return int(val)
    return None


def _count_cc_sessions_today() -> int | None:
    """Count Claude Code sessions from today by checking project dirs."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return None

    count = 0

    # Check for JSONL session files modified today
    out = run(
        f'find "{projects_dir}" -name "*.jsonl" -newer '
        f'"$(date -v0H -v0M -v0S +%Y%m%d)" -type f 2>/dev/null | wc -l'
    )

    # Simpler approach: count dirs with recent modification
    out = run(
        f'find "{projects_dir}" -maxdepth 2 -name "*.jsonl" '
        f'-mtime -1 2>/dev/null | wc -l'
    )
    try:
        count = int(out.strip())
    except (ValueError, TypeError):
        return None

    return count


# ---------------------------------------------------------------------------
# Codex CLI usage
# ---------------------------------------------------------------------------


def collect_codex(config: dict) -> dict:
    """Collect Codex CLI subscription usage (best-effort)."""
    sub_cfg = config.get("subscriptions", {}).get("codex-cli", {})

    result = {
        "provider": "openai",
        "cli": "codex-cli",
        "plan": sub_cfg.get("plan", "pro"),
        "monthly_cost_usd": sub_cfg.get("monthly_cost_usd", 200.00),
        "collected_at": datetime.now(UTC).isoformat(),
    }

    # Check if codex is installed
    codex_path = run("which codex 2>/dev/null")
    result["installed"] = bool(codex_path)

    if not codex_path:
        result["source"] = "not_installed"
        return result

    # Try to get usage info (codex may have a usage flag)
    usage_out = run("codex usage 2>/dev/null")
    if usage_out:
        result["raw_usage"] = usage_out
        result["source"] = "cli_usage"
    else:
        result["source"] = "no_usage_api"

    return result


# ---------------------------------------------------------------------------
# Gemini CLI usage
# ---------------------------------------------------------------------------


def collect_gemini(config: dict) -> dict:
    """Collect Gemini CLI subscription usage (best-effort)."""
    sub_cfg = config.get("subscriptions", {}).get("gemini-cli", {})

    result = {
        "provider": "google",
        "cli": "gemini-cli",
        "plan": sub_cfg.get("plan", "advanced"),
        "monthly_cost_usd": sub_cfg.get("monthly_cost_usd", 0),
        "collected_at": datetime.now(UTC).isoformat(),
    }

    # Check if gemini is installed
    gemini_path = run("which gemini 2>/dev/null")
    result["installed"] = bool(gemini_path)

    if not gemini_path:
        result["source"] = "not_installed"
        return result

    result["source"] = "installed_no_usage_api"
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def collect_all(config: dict, provider: str | None = None) -> dict:
    """Collect subscription usage for all or specific provider."""
    result = {
        "type": "subscription_usage",
        "timestamp": datetime.now(UTC).isoformat(),
        "providers": [],
    }

    collectors = {
        "cc": ("claude-code", collect_claude_code),
        "codex": ("codex-cli", collect_codex),
        "gemini": ("gemini-cli", collect_gemini),
    }

    if provider:
        if provider in collectors:
            _name, fn = collectors[provider]
            result["providers"].append(fn(config))
        else:
            print(f"Unknown provider: {provider}", file=sys.stderr)
            sys.exit(1)
    else:
        for _, fn in collectors.values():
            result["providers"].append(fn(config))

    # Calculate total monthly cost
    result["total_monthly_cost_usd"] = sum(
        p.get("monthly_cost_usd", 0) for p in result["providers"]
    )

    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Subscription Usage Collector",
    )
    parser.add_argument(
        "--provider", "-p", choices=["cc", "codex", "gemini"],
        help="Collect for specific provider only",
    )
    parser.add_argument(
        "--output", "-o", type=str,
        help="Output file path",
    )
    parser.add_argument("--config", type=str, help="Config file path")
    parser.add_argument(
        "--compact", action="store_true",
        help="Compact JSON",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    config = load_config(config_path)

    result = collect_all(config, provider=args.provider)

    indent = None if args.compact else 2
    output = json.dumps(result, indent=indent, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n")
        print(f"Report saved to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
