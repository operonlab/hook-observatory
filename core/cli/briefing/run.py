#!/usr/bin/env python3
"""Daily Intelligence Briefing — V6 Streaming Pipeline

Each topic runs independently in parallel:
  search (Haiku+WebSearch, retry 3x) → analyze (Sonnet) → write to DB → done

No waiting. A topic that finishes first appears on the frontend immediately.
Search failure = skip topic (never fabricate data).
Only CLI needed: claude
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────

DATE = date.today().isoformat()
MONTH = datetime.now().month
YEAR = datetime.now().year

OUTPUT_ROOT = (
    Path(os.environ.get("WORKSHOP_OUTPUTS_DIR", Path.home() / "workshop" / "outputs"))
    / "daily-briefing"
)
OUTPUT_DIR = OUTPUT_ROOT / DATE
RAW_DIR = OUTPUT_DIR / "raw"
ANALYSIS_DIR = OUTPUT_DIR / "analysis"
LOG_DIR = OUTPUT_ROOT / "logs"

API_BASE = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("SPACE_ID", "default")
INTERNAL_KEY = os.environ.get("CORE_INTERNAL_API_KEY", "")

SEARCH_MAX_RETRIES = 3
SEARCH_TIMEOUT = 300
ANALYSIS_TIMEOUT = 600
MAX_PARALLEL_TOPICS = 3

for d in [RAW_DIR, ANALYSIS_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Logging ──────────────────────────────────────────────────────────

log_file = LOG_DIR / f"{DATE}.log"
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("briefing")

# ─── Helpers ──────────────────────────────────────────────────────────

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\r")


def clean_output(text: str) -> str:
    return ANSI_RE.sub("", text)


def _backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff with jitter: base * 2^attempt + uniform(0, 10%)."""
    delay = min(base * (2**attempt), cap)
    return delay + random.uniform(0, delay * 0.1)


def _auth_headers(extra: dict | None = None) -> dict:
    h = {}
    if INTERNAL_KEY:
        h["X-Internal-Key"] = INTERNAL_KEY
    if extra:
        h.update(extra)
    return h


def api_get(path: str) -> dict | list | None:
    url = f"{API_BASE}{path}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=_auth_headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # 4xx errors won't benefit from retry
            log.error("API GET %s -> %d", path, e.code)
            return None
        except Exception as e:
            if attempt < 2:
                delay = _backoff_delay(attempt)
                log.warning(
                    "API GET %s failed (attempt %d/3), retry in %.1fs: %s",
                    path, attempt + 1, delay, e,
                )
                time.sleep(delay)
            else:
                log.error("API GET %s failed: %s", path, e)
    return None


def api_post(path: str, data: dict) -> dict | None:
    url = f"{API_BASE}{path}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_auth_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        log.error("API POST %s -> %d: %s", path, e.code, body)
        return None
    except Exception as e:
        log.error("API POST %s failed: %s", path, e)
        return None


def api_patch(path: str, data: dict) -> dict | None:
    url = f"{API_BASE}{path}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_auth_headers({"Content-Type": "application/json"}),
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.error("API PATCH %s failed: %s", path, e)
        return None


def run_cli(cmd: list[str], timeout: int = 600) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=_cli_env()
        )
        return clean_output(result.stdout)
    except subprocess.TimeoutExpired:
        log.warning("CLI timeout (%ds): %s", timeout, cmd[0])
        return ""
    except Exception as e:
        log.error("CLI error: %s -- %s", cmd[0], e)
        return ""


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    home = str(Path.home())
    env["PATH"] = f"{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"
    env.pop("CLAUDECODE", None)
    return env


def notify(title: str, message: str, sound: str = "Glass") -> None:
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}" sound name "{sound}"',
            ],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass


# ─── Load Topics ─────────────────────────────────────────────────────


def load_topics() -> list[dict]:
    data = api_get(f"/api/briefing/topics?space_id={SPACE_ID}&page_size=50")
    if not data or not data.get("items"):
        return []
    topics = []
    for t in data["items"]:
        if not t.get("enabled", True):
            continue
        params: dict = {
            "id": t["id"],
            "name": t["name"],
            "display_name": t["display_name"],
            "type": t.get("topic_type", "news"),
            "prompt_template": t.get("prompt_template"),
        }
        params.update(t.get("search_config") or {})
        topics.append(params)
    return topics


# ─── Search (Haiku + WebSearch, retry 3x) ────────────────────────────


def build_search_prompt(topic: dict) -> str:
    if topic.get("type") == "weather":
        cities = topic.get("cities", [{"name_en": "Taipei", "name_cn": "Taipei"}])
        cities_str = ", ".join(f"{c['name_cn']}({c['name_en']})" for c in cities)
        return (
            f"Today is {DATE}. Use WebSearch to get weather for: {cities_str}\n"
            "Search '[city] weather forecast' for each.\n"
            "Output markdown in Traditional Chinese: current/humidity/wind/AQI/forecast/warnings."
        )

    name_en = topic.get("search_query_en", topic["name"])
    name_cn = topic["display_name"]
    focus = topic.get("focus_areas", "")

    return textwrap.dedent(f"""\
        Intelligence analyst. Today: {DATE} ({YEAR}/{MONTH}).
        TOPIC: {name_cn} ({name_en}). FOCUS: {focus}

        Use WebSearch. Run 5+ searches:
        1. "{name_en} news this week {YEAR}"
        2. "{name_cn} latest"
        3. "{name_en} analysis {YEAR}"
        4. "{name_en} reddit hacker news"
        5. Other FOCUS angles

        Output strict markdown in Traditional Chinese:
        ## {name_cn}
        ### Trends (1-5)
        ### Key News (15+ items: title, source, URL, 2-sentence summary, sentiment)
        ### Extreme Views (list or 'None found')
        Exclude ads. Include EN+CN sources.""")


def search_with_retry(topic: dict) -> str:
    """Search with retry. Returns content or empty string (never fabricates)."""
    key = topic["name"]
    prompt = topic.get("prompt_template") or build_search_prompt(topic)
    if topic.get("prompt_template"):
        prompt = prompt.format(
            DATE=DATE,
            YEAR=YEAR,
            MONTH=MONTH,
            display_name=topic["display_name"],
            name=key,
        )

    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        "haiku",
        "--allowedTools",
        "WebSearch,WebFetch",
        "--permission-mode",
        "plan",
    ]

    for attempt in range(1, SEARCH_MAX_RETRIES + 1):
        log.info("  [%s] search attempt %d/%d", key, attempt, SEARCH_MAX_RETRIES)
        raw = run_cli(cmd, timeout=SEARCH_TIMEOUT)
        if raw and len(raw) > 100:
            return raw
        log.warning("  [%s] attempt %d failed", key, attempt)

    log.error("  [%s] all %d attempts failed — skipping (no fabrication)", key, SEARCH_MAX_RETRIES)
    return ""


# ─── Analyze (Sonnet) ────────────────────────────────────────────────


def analyze(topic: dict, raw_content: str) -> str:
    display = topic["display_name"]
    weather = "(weather: focus accuracy)" if topic.get("type") == "weather" else ""

    prompt = textwrap.dedent(f"""\
        Today: {DATE}. Senior intelligence analyst.
        Raw data for "{display}" {weather}:

        {raw_content}

        TWO parts:

        # Analysis
        ## {display} Analysis
        ### Top 5 Trends (with reasoning)
        ### Top 10 Headlines (with importance)
        ### Extreme View Assessment
        ### Overall Sentiment
        ### Overlooked Angles

        # Conclusion
        ## {display} Conclusion
        ### Key Findings (3-5)
        ### Consensus
        ### Divergent Views
        ### Confidence: X.X (0.0-1.0)

        Rules: Opinionated + reasoned. Traditional Chinese. Quality > quantity.""")

    return run_cli(
        ["claude", "-p", prompt, "--model", "sonnet", "--permission-mode", "plan"],
        timeout=ANALYSIS_TIMEOUT,
    )


# ─── Extract Conclusion ──────────────────────────────────────────────


def extract_conclusion(analysis: str, display_name: str) -> str:
    for marker in [
        f"## {display_name} Conclusion",
        f"## {display_name} 結論",
        "## Conclusion",
        "## 結論",
        "# Conclusion",
        "# 結論",
    ]:
        idx = analysis.find(marker)
        if idx != -1:
            return analysis[idx:].strip()
    for marker in ["### Key Findings", "### 核心發現"]:
        idx = analysis.find(marker)
        if idx != -1:
            return analysis[idx:].strip()
    return ""


# ─── Per-Topic Pipeline (runs independently) ─────────────────────────


def process_topic(topic: dict) -> dict:
    """Full pipeline for one topic: search → analyze → write to DB.
    Returns result dict with status."""
    key = topic["name"]
    display = topic["display_name"]
    log.info("[%s] START", display)

    # Create briefing record
    briefing = api_post(
        f"/api/briefing/daily?space_id={SPACE_ID}",
        {
            "date": DATE,
            "topic_id": topic["id"],
            "domain": key,
            "status": "searching",
        },
    )
    if not briefing:
        log.error("[%s] failed to create briefing", display)
        return {"topic": key, "status": "error", "reason": "create_failed"}

    bid = briefing["id"]
    base = f"/api/briefing/daily/{bid}/entries?space_id={SPACE_ID}"

    # Phase 1: Search (retry 3x)
    raw = search_with_retry(topic)
    if not raw:
        api_patch(f"/api/briefing/daily/{bid}", {"status": "failed"})
        log.error("[%s] SEARCH FAILED — skipped", display)
        return {"topic": key, "status": "search_failed"}

    (RAW_DIR / f"{key}.md").write_text(raw, encoding="utf-8")
    log.info("[%s] search ok: %d lines", display, raw.count("\n"))

    # Write raw entry immediately
    api_post(base, {"phase": "raw", "key": key, "content": raw, "metadata": {"chars": len(raw)}})

    # Phase 2: Analyze
    api_patch(f"/api/briefing/daily/{bid}", {"status": "analyzing"})
    analysis = analyze(topic, raw)

    if not analysis:
        api_patch(f"/api/briefing/daily/{bid}", {"status": "failed"})
        log.error("[%s] ANALYSIS FAILED", display)
        return {"topic": key, "status": "analysis_failed"}

    (ANALYSIS_DIR / f"{key}.md").write_text(analysis, encoding="utf-8")
    log.info("[%s] analysis ok: %d lines", display, analysis.count("\n"))

    # Write analysis entry
    api_patch(f"/api/briefing/daily/{bid}", {"status": "synthesizing"})
    api_post(
        base,
        {
            "phase": "analysis",
            "key": "claude-sonnet",
            "content": analysis,
            "metadata": {"chars": len(analysis)},
        },
    )

    # Write conclusion entry
    conclusion = extract_conclusion(analysis, display)
    if conclusion:
        api_post(
            base,
            {
                "phase": "conclusion",
                "key": "synthesis",
                "content": conclusion,
                "metadata": {"chars": len(conclusion)},
            },
        )

    # Done
    api_patch(f"/api/briefing/daily/{bid}", {"status": "completed"})
    log.info("[%s] COMPLETED", display)
    return {"topic": key, "status": "completed"}


# ─── Main ────────────────────────────────────────────────────────────


def preflight() -> bool:
    env = _cli_env()
    try:
        subprocess.run(
            ["which", "claude"], capture_output=True, env=env, timeout=5
        ).check_returncode()
    except Exception:
        log.error("FATAL: claude not found")
        return False
    log.info("Tool OK: claude")
    return True


def main() -> int:
    log.info("=== Daily Briefing V6 (streaming parallel, Claude-only) ===")
    log.info(
        "Date: %s | Max parallel: %d | Search retries: %d",
        DATE,
        MAX_PARALLEL_TOPICS,
        SEARCH_MAX_RETRIES,
    )

    if not preflight():
        return 1

    topics = load_topics()
    if not topics:
        log.info("No enabled topics")
        return 0
    log.info("Topics (%d): %s", len(topics), ", ".join(t["display_name"] for t in topics))

    # Run all topics in parallel — each topic is fully independent
    results = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_TOPICS) as pool:
        futures = {pool.submit(process_topic, t): t for t in topics}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status_icon = "ok" if result["status"] == "completed" else "FAIL"
            log.info("  %s %s: %s", status_icon, result["topic"], result["status"])

    # Summary
    completed = sum(1 for r in results if r["status"] == "completed")
    failed = len(results) - completed
    log.info("Summary: %d/%d completed, %d failed", completed, len(results), failed)

    if completed > 0:
        log.info("Done: https://workshop.joneshong.com/briefings/%s", DATE)
        notify("Daily Briefing", f"{completed}/{len(results)} topics done: {DATE}")
    else:
        log.error("All topics failed")
        notify("Daily Briefing", f"All failed: {DATE}", sound="Basso")

    log.info("=== Done: %s ===", datetime.now().strftime("%H:%M:%S"))

    try:
        subprocess.run(
            [
                "workshop-report",
                "com.joneshong.scheduler.daily-briefing",
                str(0 if completed > 0 else 1),
                "briefing sent",
            ],
            timeout=10,
            capture_output=True,
        )
    except Exception:
        pass

    return 0 if completed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
