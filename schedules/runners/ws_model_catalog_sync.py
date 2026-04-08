#!/usr/bin/env python3
"""
ws_model_catalog_sync.py — Sync notable unconfigured models from LLM leaderboards

Scrapes LMSYS Chatbot Arena and other leaderboards to find high-ranked models
that are NOT from the "Big 3" (Anthropic/OpenAI/Google) and NOT already in LiteLLM config.

Stores results in Redis for agent-metrics consumption.

Schedule: Weekly (Cronicle)
Logs: ~/workshop/outputs/scheduler/logs/ws-model-catalog-sync.log
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-model-catalog-sync.log"
LITELLM_CONFIG = HOME / ".config/litellm/config.yaml"
REDIS_KEY = "agent-metrics:model-catalog:notable"
REDIS_TTL = 86400 * 8  # 8 days (weekly sync + buffer)
CFX_SESSION = "catalog-sync"

# Big 3 providers to exclude
BIG3_KEYWORDS = {"anthropic", "claude", "openai", "gpt", "google", "gemini"}

os.environ["PATH"] = (
    f"/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:"
    f"/usr/sbin:/sbin:{HOME}/.local/bin:{os.environ.get('PATH', '')}"
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_configured_providers() -> set[str]:
    """Read LiteLLM config and extract configured provider keywords."""
    providers = set()
    try:
        with open(LITELLM_CONFIG) as f:
            config = yaml.safe_load(f)
        for model in config.get("model_list", []):
            name = model.get("model_name", "").lower()
            # Extract provider keywords from model names
            for kw in ("glm", "kimi", "minimax", "deepseek", "qwen", "grok", "gemini"):
                if kw in name:
                    providers.add(kw)
    except Exception as e:
        log(f"WARN: Could not read LiteLLM config: {e}")
        # Fallback known providers
        providers = {"glm", "kimi", "minimax", "deepseek", "qwen", "grok", "gemini"}
    return providers


def _cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["camoufox-cli", "--session", CFX_SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def scrape_arena_leaderboard() -> str:
    """Scrape LMSYS Chatbot Arena leaderboard page."""
    url = "https://lmarena.ai/?leaderboard"
    try:
        open_r = _cfx("--persistent", "open", url)
        if open_r.returncode != 0:
            log(f"ERROR: cfx open failed: {open_r.stderr[:200]}")
            return ""
        time.sleep(8)  # Wait for SPA to render
        eval_r = _cfx("eval", "document.body.innerText.substring(0, 15000)", timeout=20)
        return eval_r.stdout if eval_r.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        log("ERROR: arena scrape timeout")
        return ""
    finally:
        try:
            _cfx("close", timeout=10)
        except Exception:
            pass


def parse_arena_models(text: str, configured: set[str]) -> list[dict]:
    """Extract models from Arena text, filtering out Big 3 and configured providers."""
    if not text:
        return []

    exclude = BIG3_KEYWORDS | configured
    models = []

    # Pattern: model name followed by Elo score
    # Arena format varies, try multiple patterns
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try to find Elo scores (4-digit numbers around 1100-1600)
        elo_match = re.search(r"(\d{4})", line)
        if not elo_match:
            continue
        elo = int(elo_match.group(1))
        if elo < 1100 or elo > 1600:
            continue

        # Check if this line has a model name
        lower = line.lower()

        # Skip if it's a Big 3 or already configured model
        skip = False
        for kw in exclude:
            if kw in lower:
                skip = True
                break
        if skip:
            continue

        # Try to extract model name (before the Elo number)
        name_part = line[: elo_match.start()].strip().rstrip("-").strip()
        if len(name_part) < 3 or len(name_part) > 60:
            continue

        # Deduplicate by name
        if any(m["name"].lower() == name_part.lower() for m in models):
            continue

        models.append(
            {
                "name": name_part,
                "score": f"{elo} Elo",
                "elo": elo,
            }
        )

    # Sort by Elo descending, take top 8
    models.sort(key=lambda m: m["elo"], reverse=True)
    return models[:8]


def enrich_models(models: list[dict]) -> list[dict]:
    """Add provider, pricing, and access info to parsed models."""
    provider_map = {
        "mistral": ("Mistral AI", "Mistral API / OpenRouter", "$2.00/$6.00"),
        "llama": ("Meta（開源）", "Fireworks / Together.ai", "$0.80~1.50/M"),
        "reka": ("Reka AI", "Reka API + SDK", "~$2~3/M"),
        "doubao": ("ByteDance", "豆包 API（中國區）", "低於 Qwen/GLM"),
        "command": ("Cohere", "Cohere API", "$2.50/$10.00"),
        "nemo": ("Mistral AI", "Fireworks / Together.ai", "$0.10/$0.20"),
        "yi": ("01.AI", "01.AI API / OpenRouter", "~$1.00/$3.00"),
        "step": ("StepFun 階躍", "Step API（中國區）", "~¥0.05/千 tokens"),
        "baichuan": ("百川", "Baichuan API（中國區）", "低價"),
        "phi": ("Microsoft", "Azure / HuggingFace", "開源免費"),
        "dbrx": ("Databricks", "Databricks API", "~$0.75/$2.25"),
        "jamba": ("AI21 Labs", "AI21 API", "~$0.50/$0.70"),
        "intern": ("上海 AI Lab", "OpenRouter / HuggingFace", "開源"),
    }

    enriched = []
    for m in models:
        name_lower = m["name"].lower()
        provider, access, price = "Unknown", "未知", "—"
        strengths = ""

        for key, (prov, acc, pr) in provider_map.items():
            if key in name_lower:
                provider, access, price = prov, acc, pr
                break

        if provider == "Unknown":
            # Try to infer from name
            provider = m["name"].split("-")[0].split(" ")[0] if "-" in m["name"] else "Unknown"
            access = "待查"
            price = "—"

        enriched.append(
            {
                "name": m["name"],
                "provider": provider,
                "score": m["score"],
                "strengths": strengths or f"Arena {m['score']}",
                "access": access,
                "price": price,
            }
        )

    return enriched


def store_to_redis(models: list[dict]) -> bool:
    """Store notable models to Redis."""
    try:
        import redis

        r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
        data = {
            "models": models,
            "synced_at": datetime.now(UTC).isoformat(),
            "source": "lmsys_arena_scrape",
        }
        r.setex(REDIS_KEY, REDIS_TTL, json.dumps(data))
        log(f"Stored {len(models)} models to Redis")
        return True
    except Exception as e:
        log(f"ERROR: Redis store failed: {e}")
        return False


def main() -> int:
    log("=== Model Catalog Sync Start ===")

    configured = get_configured_providers()
    log(f"Configured providers: {sorted(configured)}")
    log(f"Excluded (Big 3 + configured): {sorted(BIG3_KEYWORDS | configured)}")

    text = scrape_arena_leaderboard()
    if not text:
        log("ERROR: No data from Arena leaderboard")
        # Save raw for debugging
        return 1

    # Save raw
    raw_dir = LOG_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "arena_raw.txt").write_text(text)
    log(f"Raw text: {len(text)} chars")

    models = parse_arena_models(text, configured)
    log(f"Parsed {len(models)} candidate models")

    if not models:
        log("WARN: No new models found after filtering")
        return 0

    enriched = enrich_models(models)
    for m in enriched:
        log(f"  {m['name']:30s} {m['score']:>10s} ({m['provider']})")

    store_to_redis(enriched)

    # Fallback JSON
    Path("/tmp/agent-metrics-model-catalog.json").write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False)
    )

    log(f"=== Model Catalog Sync Done: {len(enriched)} models ===")
    return 0


if __name__ == "__main__":
    import fcntl

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    sys.exit(main())
