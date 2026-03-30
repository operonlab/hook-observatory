#!/usr/bin/env python3
"""
ws_weekly_maintenance.py — Weekly deep maintenance via claude -p

Pipeline:
  1. Update system-map baseline (snapshot.py)
  2. Run drift check to confirm baseline consistency
  3. Launch claude -p for LLM-powered maintenance report
  4. Bark summary notification

Designed for Cronicle weekly schedule (Sunday 16:00).
Uses claude -p for LLM judgment — costs ~2K tokens per run.
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PYTHON = HOME / ".local/bin/python3"
SNAPSHOT_SCRIPT = HOME / ".claude/skills/system-map/scripts/snapshot.py"
DRIFT_SCRIPT = HOME / ".claude/skills/system-map/scripts/check_drift.py"
OUTPUT_DIR = HOME / "workshop/outputs/maintenance"
COUNTS_FILE = OUTPUT_DIR / "last-counts.json"

BARK_URL = os.environ.get("BARK_URL", "http://127.0.0.1:8090")
BARK_KEY = os.environ.get("BARK_KEY", "")

os.environ["PATH"] = (
    f"{HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin"
    f":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def bark_notify(title: str, body: str) -> None:
    if not BARK_KEY:
        log("BARK_KEY not set, skip notification")
        return
    url = f"{BARK_URL}/{BARK_KEY}/{title}/{body}"
    try:
        urllib.request.urlopen(url, timeout=10)
        log(f"Bark sent: {title}")
    except Exception as e:
        log(f"Bark failed: {e}")


def run_script(script: Path, label: str) -> tuple[int, str]:
    """Run a Python script and return (exit_code, output)."""
    try:
        result = subprocess.run(
            [str(PYTHON), str(script)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\nSTDERR: {result.stderr.strip()}"
        log(f"{label}: exit={result.returncode}")
        return result.returncode, output
    except Exception as e:
        msg = f"Error running {label}: {e}"
        log(msg)
        return 1, msg


def read_daily_logs() -> str:
    """Read this week's daily maintenance logs."""
    summaries = []
    for log_file in sorted(OUTPUT_DIR.glob("daily-*.log"))[-7:]:
        try:
            content = log_file.read_text().strip()
            # Extract last entry
            entries = content.split("---")
            if entries:
                last = entries[-1].strip()
                summaries.append(f"[{log_file.stem}] {last[:200]}")
        except Exception:
            pass
    return "\n".join(summaries) if summaries else "No daily logs found this week."


def run_claude_maintenance(context: str) -> str:
    """Run claude -p for LLM-powered maintenance analysis."""
    prompt = f"""你是 Workshop 週維護 agent。根據以下本週維護數據生成摘要報告（繁體中文）：

{context}

請生成簡潔的週維護報告，包含：
1. 本週漂移狀態總結（一行）
2. 配置同步狀態（一行）
3. 系統健康度評估（一行）
4. 下週建議事項（如有）

格式：Markdown，不超過 20 行。"""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(HOME / "workshop"),
        )
        return (
            result.stdout.strip()
            if result.returncode == 0
            else f"claude -p failed: {result.stderr}"
        )
    except FileNotFoundError:
        return "claude CLI not found — skipping LLM analysis"
    except Exception as e:
        return f"claude -p error: {e}"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    report_file = OUTPUT_DIR / f"weekly-{today}.md"
    sections = []

    # ── Step 1: Update baseline ──
    log("Step 1: Updating system-map baseline...")
    exit_code, output = run_script(SNAPSHOT_SCRIPT, "snapshot")
    sections.append(
        f"## Baseline Update\n\n{'✅ Updated' if exit_code == 0 else '❌ Failed'}\n\n```\n{output}\n```"
    )

    # ── Step 2: Drift check ──
    log("Step 2: Running drift check...")
    exit_code, output = run_script(DRIFT_SCRIPT, "drift-check")
    has_drift = exit_code != 0
    sections.append(
        f"## Drift Check\n\n{'⚠️ Drift detected' if has_drift else '✅ No drift'}\n\n```\n{output}\n```"
    )

    # ── Step 3: Current counts ──
    log("Step 3: Reading current counts...")
    counts = {}
    if COUNTS_FILE.exists():
        try:
            counts = json.loads(COUNTS_FILE.read_text())
        except Exception:
            pass
    sections.append(
        f"## System Counts\n\n- Skills: {counts.get('skills', '?')}\n- MCP servers: {counts.get('mcp', '?')}"
    )

    # ── Step 4: Daily logs summary ──
    log("Step 4: Summarizing daily logs...")
    daily_summary = read_daily_logs()
    sections.append(f"## Daily Logs This Week\n\n```\n{daily_summary}\n```")

    # ── Step 5: LLM analysis ──
    log("Step 5: Running LLM maintenance analysis...")
    context = f"Drift: {'detected' if has_drift else 'none'}\nCounts: {json.dumps(counts)}\nDaily logs:\n{daily_summary}"
    llm_report = run_claude_maintenance(context)
    sections.append(f"## LLM Analysis\n\n{llm_report}")

    # ── Write report ──
    header = f"# Weekly Maintenance Report — {datetime.now().strftime('%Y-%m-%d')}\n\n"
    report = header + "\n\n".join(sections)
    report_file.write_text(report)
    log(f"Report written to {report_file}")

    # ── Bark notification ──
    status = "⚠️ drift" if has_drift else "✅ healthy"
    bark_notify("Weekly Maintenance", f"{status}, skills={counts.get('skills', '?')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
