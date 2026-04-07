#!/usr/bin/env python3
"""
ws_memvault_synthesis.py — Daily knowledge graph synthesis

Pipeline (sequential):
  0. Dream Consolidation — LLM reflective pass over recent memories (dry-run report)
  1. synthesis_runner.py — Leiden community detection + LLM summaries (3 levels)
     (also triggers Qdrant auto-indexing for L1/L2 via save_communities/save_summaries)
  2. confidence_decay_pipeline.py — decay stale attitude confidence
  3. attitude_pipeline.py --all   — digest accumulated corrections
  4. Tag sync + domain auto-promotion (threshold >= 10)
  5. Reset triple counter (for threshold-based triggering)

Logs: ~/workshop/outputs/memvault/logs/synthesis.log
      ~/workshop/outputs/memvault/logs/dream.log
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Structured Run ─────────────────────────────────────────────

try:
    import psutil
except ImportError:
    psutil = None

# ── Quota Gate ─────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.quota_gate import request_clearance
from lib.structured_run import structured_run

request_clearance("ws-memvault-synthesis")

# ── Memory Guardian ───────────────────────────────────────────
MEMORY_THRESHOLD = 85  # 記憶體使用率超過 85% 時停止執行


def check_memory_pressure() -> bool:
    """檢查記憶體壓力，超過閾值返回 False"""
    if psutil is None:
        return True  # 沒有 psutil 則預設允許執行
    memory_percent = psutil.virtual_memory().percent
    if memory_percent > MEMORY_THRESHOLD:
        return False
    return True


# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PIPELINES_DIR = HOME / "workshop/mcp/memvault/pipelines"
PYTHON = HOME / ".local/bin/python3"
UV = "/opt/homebrew/bin/uv"
CORE_PROJECT = HOME / "workshop/core"
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "synthesis.log"
CORRECTIONS_DIR = HOME / "workshop/outputs/memvault/corrections"
COUNTER_FILE = HOME / ".memvault-triple-counter"
CORE_API = "http://localhost:10000/api/memvault"
DOMAIN_THRESHOLD = 10

# ── Dream Phase Configuration ──────────────────────────────────
LITELLM_URL = "http://localhost:4000/v1/chat/completions"
DREAM_LOG = LOG_DIR / "dream.log"
DREAM_MODEL = "haiku"  # Via LiteLLM proxy

# Extend PATH
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[synthesis] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_pipeline(script_name: str, extra_args: list[str] | None = None) -> bool:
    """Run a pipeline script, appending output to log file. Returns True on success."""
    cmd = [str(PYTHON), str(PIPELINES_DIR / script_name)]
    if extra_args:
        cmd.extend(extra_args)
    with open(LOG_FILE, "a") as f:
        result = subprocess.run(cmd, stdout=f, stderr=f)
    return result.returncode == 0


def api_get(url: str) -> dict | list | None:
    """Perform a GET request and return parsed JSON, or None on error."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def api_post(url: str, data: dict) -> int | None:
    """Perform a POST request with JSON body. Returns HTTP status code or None on error."""
    try:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except Exception:
        return None


def dream_orient() -> dict:
    """Orient: Fetch recent memories and attitude facts."""
    result = {"attitudes": [], "blocks": [], "triples_count": 0}

    # Recent attitude facts (last 7 days)
    url = f"{CORE_API}/kg/attitudes?space_id=default&page_size=50"
    data = api_get(url)
    if data and isinstance(data, dict):
        result["attitudes"] = data.get("items", [])

    # Recent memory blocks
    url = f"{CORE_API}/blocks?space_id=default&page_size=30&sort=-created_at"
    data = api_get(url)
    if data and isinstance(data, dict):
        result["blocks"] = data.get("items", [])

    # Triple count
    url = f"{CORE_API}/kg/triples?space_id=default&page_size=1"
    data = api_get(url)
    if data and isinstance(data, dict):
        result["triples_count"] = data.get("total", 0)

    return result


def dream_reflect(context: dict) -> str:
    """Reflect: LLM reviews memory state and identifies issues."""
    attitudes_summary = "\n".join(
        f"- [{a.get('category', '')}] {a.get('fact', '')} "
        f"(confidence: {a.get('confidence', 0):.2f})"
        for a in context["attitudes"][:30]
    )
    blocks_summary = "\n".join(
        f"- [{b.get('block_type', '')}] {b.get('topic', 'untitled')}: "
        f"{(b.get('content', ''))[:150]}"
        for b in context["blocks"][:20]
    )

    prompt = f"""You are performing a dream — a reflective pass over memory state.

## Current Memory State
- {len(context["attitudes"])} attitude facts
- {len(context["blocks"])} recent memory blocks
- {context["triples_count"]} total knowledge triples

## Recent Attitude Facts
{attitudes_summary or "(none)"}

## Recent Memory Blocks
{blocks_summary or "(none)"}

## Your Task
Review the above and identify:
1. **Contradictions**: Any facts that contradict each other
2. **Stale entries**: Facts that may no longer be true (old dates, deprecated tools)
3. **Merge candidates**: Multiple entries on the same topic to consolidate
4. **Confidence anomalies**: Scores that seem too high or too low

Output a concise report in markdown. If nothing stands out, say "No issues found."
Keep your response under 500 words. Write in 繁體中文."""

    try:
        payload = json.dumps(
            {
                "model": DREAM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,
                "temperature": 0.3,
            }
        ).encode()

        req = urllib.request.Request(
            LITELLM_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Dream reflection failed: {e}"


def dream_lint_summary() -> str:
    """Quick lint summary for dream log — fast SQL checks only."""
    url = (
        f"{CORE_API}/kg/lint?space_id=default"
        "&checks=stale,orphan_entities,dangling_refs,data_gaps"
    )
    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read())
            summary = data.get("summary", {})
            total = sum(summary.values())
            return f"Lint: {total} findings ({summary})"
    except Exception:
        return "Lint: unavailable"


def dream_phase() -> bool:
    """Execute the dream consolidation phase (dry-run: report only, no mutations)."""
    log("Step 0/5: Dream Consolidation (dry-run)")

    # Orient
    context = dream_orient()
    if not context["attitudes"] and not context["blocks"]:
        log("  Dream: No recent memories to review, skipping")
        return True

    log(
        f"  Orient: {len(context['attitudes'])} attitudes, "
        f"{len(context['blocks'])} blocks, "
        f"{context['triples_count']} triples"
    )

    # Reflect
    report = dream_reflect(context)

    # Lint summary (lightweight SQL checks)
    lint_line = dream_lint_summary()
    log(f"  {lint_line}")

    # Report — write to dream log (dry-run, no mutations)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dream_entry = f"\n{'=' * 60}\n[Dream] {timestamp}\n{'=' * 60}\n{report}\n\n{lint_line}\n"

    try:
        with open(DREAM_LOG, "a") as f:
            f.write(dream_entry)
        log(f"  Dream report written to {DREAM_LOG}")
    except Exception as e:
        log(f"  Dream log write failed: {e}")

    log("Step 0 OK (dry-run — report only)")
    return True


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Memory pressure check
    if not check_memory_pressure():
        mem_percent = psutil.virtual_memory().percent if psutil else "unknown"
        log(
            f"ABORT: Memory pressure too high "
            f"({mem_percent}% > {MEMORY_THRESHOLD}%), skipping synthesis"
        )
        sys.exit(0)

    log("========== Daily synthesis started ==========")

    # Step 0: Dream Consolidation (dry-run — report only, no mutations)
    dream_phase()

    # Step 1: Leiden community detection + LLM summaries (synthesis_runner.py)
    # This also triggers Qdrant auto-indexing for L1 communities and L2 summaries
    log("Step 1/5: synthesis_runner.py (Leiden + summaries)")
    step1 = structured_run(
        [
            str(UV),
            "run",
            "--project",
            str(CORE_PROJECT),
            str(PIPELINES_DIR / "synthesis_runner.py"),
        ],
        label="memvault-synthesis",
        timeout=2400,  # 3 levels × 600s + Leiden ~120s + margin
    )
    # 將 stdout 同時輸出到 log file（保持原本的記錄行為）
    if step1.stdout:
        with open(LOG_FILE, "a") as f:
            f.write(step1.stdout)
        print(step1.stdout, end="", flush=True)
    if step1.stderr:
        with open(LOG_FILE, "a") as f:
            f.write(step1.stderr)
    if step1.success:
        log(f"Step 1 OK ({step1.duration_seconds:.1f}s)")
    else:
        log(f"Step 1 FAILED (exit {step1.returncode}) — continuing anyway")

    # Step 2: Confidence decay (independent of communities)
    log("Step 2/5: confidence_decay_pipeline.py")
    if run_pipeline("confidence_decay_pipeline.py"):
        log("Step 2 OK")
    else:
        log("Step 2 FAILED — continuing anyway")

    # Step 3: Attitude pipeline — digest all accumulated corrections
    log("Step 3/5: attitude_pipeline.py --all")
    if CORRECTIONS_DIR.is_dir():
        if run_pipeline("attitude_pipeline.py", ["--input", str(CORRECTIONS_DIR), "--all"]):
            log("Step 3 OK")
        else:
            log("Step 3 FAILED — continuing anyway")
    else:
        log("Step 3 SKIP — no corrections directory")

    # Step 4: Tag sync + domain auto-promotion
    log("Step 4/5: Tag sync + domain promotion")

    # Tag sync via POST
    try:
        req = urllib.request.Request(
            f"{CORE_API}/tags/sync?space_id=default",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            sync_result = resp.read().decode()
        log(f"  Tags synced: {sync_result}")
    except Exception as e:
        log(f"  Tag sync failed (API unreachable? {e})")

    # Auto-promote tags with usage >= threshold to knowledge domains
    promoted = 0
    tags_data = api_get(f"{CORE_API}/tags?space_id=default")
    domains_data = api_get(f"{CORE_API}/domains?space_id=default&page_size=200")

    if tags_data is not None and domains_data is not None:
        existing_domains = {d["name"] for d in domains_data.get("items", [])}
        tags = tags_data if isinstance(tags_data, list) else tags_data.get("items", [])
        new_tags = [
            t
            for t in tags
            if t.get("usage_count", 0) >= DOMAIN_THRESHOLD and t["name"] not in existing_domains
        ]
        for t in new_tags:
            status = api_post(
                f"{CORE_API}/domains?space_id=default",
                {
                    "name": t["name"],
                    "description": f"Auto-promoted (usage: {t['usage_count']})",
                },
            )
            if status == 201:
                promoted += 1

    log(f"  Domains promoted: {promoted} new (threshold >= {DOMAIN_THRESHOLD})")
    log("Step 4 OK")

    # Step 5: Reset triple counter
    log("Step 5/5: Reset triple counter")
    COUNTER_FILE.write_text("0\n")
    log("Triple counter reset to 0")

    log("========== Daily synthesis complete ==========")


if __name__ == "__main__":
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()
