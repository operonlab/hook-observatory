#!/usr/bin/env python3
"""
ws_observation_gate.py — Observation period checker for dry-run features.

Checks if a dry-run feature has accumulated enough data during its observation
period, then sends a Bark notification with a summary and recommendation.

Usage:
  python3 ws_observation_gate.py <feature_key>

Supported features are defined in FEATURES dict below.
Add new entries when any dry-run / observation-period feature is deployed.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
BARK_URL = "http://127.0.0.1:8090"
BARK_KEY = os.environ.get("BARK_KEY", "")
LOG_DIR = HOME / "workshop" / "outputs" / "observation-gate"


# ── Feature Definitions ──────────────────────────────────────────
# Each feature defines:
#   log_path: where to find the dry-run output
#   min_entries: minimum entries to consider "enough data"
#   separator: how to count entries in the log
#   description: human-readable name
#   next_action: what to do after observation passes

FEATURES = {
    "dream-consolidation": {
        "log_path": HOME / "workshop" / "outputs" / "memvault" / "logs" / "dream.log",
        "min_entries": 3,
        "separator": "=" * 60,
        "description": "Memvault Dream Consolidation",
        "next_action": (
            "檢查 dream.log 品質，決定是否開啟 mutation 模式（讓 dream phase 實際修改記憶）"
        ),
    },
    # ── Add future dry-run features here ──
    # "feature-key": {
    #     "log_path": ...,
    #     "min_entries": ...,
    #     "separator": ...,
    #     "description": ...,
    #     "next_action": ...,
    # },
}


def bark_notify(title: str, body: str, group: str = "observation") -> None:
    """Send Bark push notification (best-effort, URL-encoded path)."""
    if not BARK_KEY:
        print("[WARN] BARK_KEY not set, skipping notification")
        return
    try:
        encoded_title = urllib.parse.quote(title)
        encoded_body = urllib.parse.quote(body)
        url = f"{BARK_URL}/{BARK_KEY}/{encoded_title}/{encoded_body}?group={group}&sound=minuet"
        urllib.request.urlopen(url, timeout=5)
        print(f"[OK] Bark sent: {title}")
    except Exception as e:
        print(f"[WARN] Bark failed: {e}")


def check_feature(key: str) -> None:
    """Check observation status for a feature and notify."""
    feat = FEATURES.get(key)
    if not feat:
        print(f"[ERROR] Unknown feature: {key}")
        print(f"Available: {', '.join(FEATURES.keys())}")
        sys.exit(1)

    log_path = Path(feat["log_path"])
    desc = feat["description"]
    min_entries = feat["min_entries"]
    separator = feat["separator"]
    next_action = feat["next_action"]

    print(f"Checking: {desc}")
    print(f"Log: {log_path}")

    if not log_path.exists():
        bark_notify(
            f"⚠️ {desc} 觀察期無輸出",
            f"Log 檔不存在: {log_path.name}\n可能 LiteLLM 連不上或 pipeline 未執行",
        )
        print("[RESULT] No log file found")
        return

    content = log_path.read_text(encoding="utf-8", errors="replace")
    entry_count = content.count(separator)

    print(f"Entries found: {entry_count} (min: {min_entries})")

    # Log the check
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    check_log = LOG_DIR / "checks.jsonl"
    with open(check_log, "a") as f:
        json.dump(
            {
                "ts": ts,
                "feature": key,
                "entries": entry_count,
                "status": "pass" if entry_count >= min_entries else "insufficient",
            },
            f,
        )
        f.write("\n")

    if entry_count >= min_entries:
        # Get last entry preview (last 500 chars)
        preview = content[-500:].strip()
        last_lines = preview.split("\n")[-5:]
        preview_text = "\n".join(last_lines)

        bark_notify(
            f"✅ {desc} 觀察期結束",
            f"{entry_count} 篇報告已累積\n下一步: {next_action}\n最近: {preview_text[:100]}",
        )
        print(f"[RESULT] PASS — {entry_count} entries, notification sent")
    else:
        bark_notify(
            f"⚠️ {desc} 資料不足",
            f"僅 {entry_count}/{min_entries} 篇報告\n建議延長觀察期或檢查 pipeline 是否正常執行",
        )
        print(f"[RESULT] INSUFFICIENT — {entry_count}/{min_entries}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <feature_key>")
        print(f"Available: {', '.join(FEATURES.keys())}")
        sys.exit(1)

    check_feature(sys.argv[1])
