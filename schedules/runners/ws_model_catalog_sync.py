#!/usr/bin/env python3
"""
ws_model_catalog_sync.py — Weekly model catalog sync from LLM leaderboards

Scrapes LMSYS Chatbot Arena → cross-references with LiteLLM config → generates:
  1. highlights_benchmark: 6 categories (overall, coding, reasoning, chinese, speed, cost)
  2. scenarios: 7 task-based recommendations
  3. highlights_subjective: 4 picks from config annotations (Smart/Fast/Value/Free)
  4. notable_unconfigured: hidden gems not from Big 3 or configured providers

All stored in Redis as one key for agent-metrics consumption.

Schedule: Weekly Monday 19:00 (Cronicle)
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
REDIS_KEY = "agent-metrics:model-catalog:full"
REDIS_KEY_NOTABLE = "agent-metrics:model-catalog:notable"
REDIS_TTL = 86400 * 8  # 8 days (weekly + buffer)
CFX_SESSION = "catalog-sync"

BIG3_KEYWORDS = {"anthropic", "claude", "openai", "gpt", "google", "gemini"}

# Known provider → keyword mapping for config parsing
PROVIDER_KEYWORDS = ("glm", "kimi", "minimax", "deepseek", "qwen", "grok", "gemini")

# Config annotation patterns: "Smart: xxx | Fast: xxx | Value: xxx"
ANNOTATION_RE = re.compile(r"Smart:\s*(\S+).*?Fast:\s*(\S+).*?Value:\s*(\S+)", re.IGNORECASE)

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


# ── LiteLLM Config Parsing ────────────────────────────────────


def parse_litellm_config() -> dict:
    """Parse LiteLLM config for model list, providers, and annotations."""
    result = {
        "configured_providers": set(),
        "models": [],
        "annotations": {},  # provider → {smart, fast, value}
    }
    try:
        with open(LITELLM_CONFIG) as f:
            raw = f.read()
        config = yaml.safe_load(raw)

        for model in config.get("model_list", []):
            name = model.get("model_name", "")
            params = model.get("litellm_params", {})
            result["models"].append(
                {
                    "name": name,
                    "litellm_model": params.get("model", ""),
                    "set_by": params.get("set_by", name),
                }
            )
            name_lower = name.lower()
            for kw in PROVIDER_KEYWORDS:
                if kw in name_lower:
                    result["configured_providers"].add(kw)

        # Parse comment annotations (Smart/Fast/Value per provider section)
        for line in raw.split("\n"):
            m = ANNOTATION_RE.search(line)
            if m:
                # Find provider from same line
                provider_match = re.search(r"──\s*(\w[\w\s]*?)\s*(?:—|──)", line)
                if provider_match:
                    provider = provider_match.group(1).strip()
                    result["annotations"][provider] = {
                        "smart": m.group(1),
                        "fast": m.group(2),
                        "value": m.group(3),
                    }

    except Exception as e:
        log(f"WARN: Config parse error: {e}")
        result["configured_providers"] = set(PROVIDER_KEYWORDS)
    return result


# ── Arena Scraping ────────────────────────────────────────────


def _cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["camoufox-cli", "--session", CFX_SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def scrape_arena() -> str:
    """Scrape LMSYS Chatbot Arena leaderboard."""
    url = "https://lmarena.ai/?leaderboard"
    try:
        open_r = _cfx("--persistent", "open", url)
        if open_r.returncode != 0:
            log(f"ERROR: cfx open failed: {open_r.stderr[:200]}")
            return ""
        time.sleep(8)
        eval_r = _cfx("eval", "document.body.innerText.substring(0, 20000)", timeout=20)
        return eval_r.stdout if eval_r.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        log("ERROR: arena scrape timeout")
        return ""
    finally:
        try:
            _cfx("close", timeout=10)
        except Exception:
            pass


def parse_all_arena_models(text: str) -> list[dict]:
    """Parse ALL models with Elo scores from Arena text."""
    if not text:
        return []
    models = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        elo_match = re.search(r"(\d{4})", line)
        if not elo_match:
            continue
        elo = int(elo_match.group(1))
        if elo < 1100 or elo > 1600:
            continue
        name_part = line[: elo_match.start()].strip().rstrip("-").strip()
        if len(name_part) < 3 or len(name_part) > 60:
            continue
        if any(m["name"].lower() == name_part.lower() for m in models):
            continue
        models.append({"name": name_part, "elo": elo})
    models.sort(key=lambda m: m["elo"], reverse=True)
    return models


# ── Catalog Generation ────────────────────────────────────────


def find_model_elo(arena_models: list[dict], keyword: str) -> int | None:
    """Find best Elo for a model keyword in arena data."""
    for m in arena_models:
        if keyword.lower() in m["name"].lower():
            return m["elo"]
    return None


def generate_benchmark_highlights(arena_models: list[dict], configured: set[str]) -> dict:
    """Generate 6 benchmark highlight categories from arena data."""
    # Find best configured model (overall)
    configured_with_elo = []
    for m in arena_models:
        name_lower = m["name"].lower()
        # Check if this model's provider is in our configured set
        is_configured = any(kw in name_lower for kw in configured)
        is_big3 = any(kw in name_lower for kw in BIG3_KEYWORDS)
        if is_configured and not is_big3:
            configured_with_elo.append(m)

    best_configured = configured_with_elo[0] if configured_with_elo else None

    # Map known model strengths (keyword → category specialization)
    category_keywords = {
        "coding": ["grok", "gemini"],  # SWE-Bench leaders
        "reasoning": ["kimi", "deepseek-r"],  # AIME leaders
        "chinese": ["glm", "kimi", "qwen"],  # Chinese Arena
        "speed": ["flash", "lite", "turbo"],  # Speed-optimized
        "cost": ["deepseek-v3", "qwen3.5-flash"],  # Cheapest
    }

    highlights = {}

    # Overall: best configured model by Elo
    if best_configured:
        highlights["overall"] = {
            "name": best_configured["name"],
            "provider": _infer_provider(best_configured["name"]),
            "score": f"{best_configured['elo']} Elo",
            "note": f"LiteLLM 最強（Arena 排名 #{arena_models.index(best_configured) + 1}）",
            "configured": True,
        }

    # Find best for each category among configured models
    for cat, keywords in category_keywords.items():
        best = None
        for m in configured_with_elo:
            name_lower = m["name"].lower()
            if any(kw in name_lower for kw in keywords):
                if best is None or m["elo"] > best["elo"]:
                    best = m
        if best:
            highlights[cat] = {
                "name": best["name"],
                "provider": _infer_provider(best["name"]),
                "score": f"{best['elo']} Elo",
                "note": _category_note(cat, best),
                "configured": True,
            }

    return highlights


def generate_scenarios(arena_models: list[dict], configured: set[str]) -> list[dict]:
    """Generate task-based scenario recommendations from arena data."""

    # Build lookup: keyword → best configured model
    def best_for(keywords: list[str]) -> tuple[str, int]:
        for m in arena_models:
            name_lower = m["name"].lower()
            is_big3 = any(kw in name_lower for kw in BIG3_KEYWORDS)
            is_configured = any(kw in name_lower for kw in configured)
            if is_configured and not is_big3:
                if any(kw in name_lower for kw in keywords):
                    return m["name"], m["elo"]
        return "", 0

    scenarios = []
    tasks = [
        ("寫程式", ["grok"], ["gemini"], "SWE-Bench"),
        ("中文內容", ["glm"], ["kimi"], "Arena Chinese"),
        ("數學推理", ["kimi"], ["deepseek-r"], "AIME"),
        ("研究分析", ["gemini"], ["grok"], "Intelligence"),
        ("快速草稿", ["flash", "qwen3.5-flash"], ["lite"], "速度+成本"),
        ("Agent 任務", ["kimi"], ["minimax"], "BrowseComp"),
        ("省錢至上", ["deepseek-v3"], ["qwen3.5-flash"], "$/M tokens"),
    ]

    for task, best_kw, alt_kw, reason_prefix in tasks:
        best_name, best_elo = best_for(best_kw)
        alt_name, alt_elo = best_for(alt_kw)
        if not best_name:
            continue
        elo_str = f"{best_elo} Elo" if best_elo else ""
        scenarios.append(
            {
                "task": task,
                "best": best_name,
                "alt": alt_name or "—",
                "reason": f"{reason_prefix} {elo_str}".strip(),
            }
        )

    return scenarios


def generate_notable_unconfigured(arena_models: list[dict], configured: set[str]) -> list[dict]:
    """Find high-ranked models NOT from Big 3 or configured providers."""
    exclude = BIG3_KEYWORDS | configured
    notable = []

    provider_enrichment = {
        "mistral": ("Mistral AI", "Mistral API / OpenRouter", "$2.00/$6.00"),
        "llama": ("Meta（開源）", "Fireworks / Together.ai", "$0.80~1.50/M"),
        "reka": ("Reka AI", "Reka API + SDK", "~$2~3/M"),
        "doubao": ("ByteDance", "豆包 API（中國區）", "~¥0.008/千 tokens"),
        "command": ("Cohere", "Cohere API", "$2.50/$10.00"),
        "nemo": ("Mistral AI", "Fireworks / Together.ai", "$0.10/$0.20"),
        "yi": ("01.AI", "01.AI API / OpenRouter", "~$1.00/$3.00"),
        "step": ("StepFun 階躍", "Step API（中國區）", "~¥0.05/千 tokens"),
        "phi": ("Microsoft", "Azure / HuggingFace", "開源免費"),
        "jamba": ("AI21 Labs", "AI21 API", "~$0.50/$0.70"),
        "intern": ("上海 AI Lab", "OpenRouter / HuggingFace", "開源"),
    }

    for m in arena_models:
        name_lower = m["name"].lower()
        if any(kw in name_lower for kw in exclude):
            continue

        provider, access, price = "Unknown", "待查", "—"
        for key, (prov, acc, pr) in provider_enrichment.items():
            if key in name_lower:
                provider, access, price = prov, acc, pr
                break

        if provider == "Unknown":
            provider = m["name"].split("-")[0].split(" ")[0]

        notable.append(
            {
                "name": m["name"],
                "provider": provider,
                "score": f"{m['elo']} Elo",
                "strengths": f"Arena {m['elo']} Elo",
                "access": access,
                "price": price,
            }
        )

        if len(notable) >= 6:
            break

    return notable


def generate_subjective(config_data: dict) -> dict:
    """Parse subjective picks from LiteLLM config annotations."""
    models = config_data["models"]

    # Find models by annotation keywords in config comments
    # Smart/Fast/Value/Free mapping from config
    def find_model(keyword: str) -> dict | None:
        for m in models:
            if keyword.lower() in m["name"].lower():
                return m
        return None

    # Determine picks from configured models' pricing and annotations
    # Use simple heuristics: most expensive = smart, cheapest fast = fast, etc.
    picks = {}

    # Smart: highest-tier model (grok-4.20 is typically the most expensive)
    smart_candidates = [
        ("grok-4.20", "xAI", "2M context 旗艦，config 標註最強"),
        ("gemini-3.1-pro", "Google", "旗艦推理"),
        ("qwen3-max", "Qwen", "最強推理"),
    ]
    for name, provider, note in smart_candidates:
        if find_model(name):
            picks["smart"] = {"name": name, "provider": provider, "note": note}
            break

    # Fast: fastest/cheapest input
    fast_candidates = [
        ("qwen3.5-flash", "Qwen", "$0.10/$0.40 全場最低 input 價"),
        ("grok-4.1-fast", "xAI", "$0.20/$0.50 非推理極速"),
        ("gemini-3.1-flash-lite", "Google", "$0.25/$1.50 極速"),
    ]
    for name, provider, note in fast_candidates:
        if find_model(name):
            picks["fast"] = {"name": name, "provider": provider, "note": note}
            break

    # Value: best cost/performance
    value_candidates = [
        ("deepseek-v3", "DeepSeek", "$0.28/$0.42 地板價"),
        ("glm-4.5-air", "Z.AI", "$0.20/$1.10 便宜好用"),
    ]
    for name, provider, note in value_candidates:
        if find_model(name):
            picks["value"] = {"name": name, "provider": provider, "note": note}
            break

    # Free
    free_candidates = [
        ("gemini-2.5-flash", "Google", "仍免費，但 2025/12 速率限制砍半"),
    ]
    for name, provider, note in free_candidates:
        if find_model(name):
            picks["free"] = {"name": name, "provider": provider, "note": note}
            break

    return picks


# ── Helpers ───────────────────────────────────────────────────


def _infer_provider(name: str) -> str:
    mapping = {
        "grok": "xAI",
        "glm": "Z.AI",
        "kimi": "Moonshot",
        "minimax": "MiniMax",
        "deepseek": "DeepSeek",
        "qwen": "Qwen",
        "gemini": "Google",
    }
    for kw, prov in mapping.items():
        if kw in name.lower():
            return prov
    return name.split("-")[0]


def _category_note(cat: str, model: dict) -> str:
    notes = {
        "coding": "SWE-Bench 領先",
        "reasoning": "數學推理強",
        "chinese": "中文 Arena 排名最高",
        "speed": "出字速度最快",
        "cost": "品質/價格比最高",
    }
    return notes.get(cat, "")


# ── Redis Storage ─────────────────────────────────────────────


def store_full_catalog(data: dict) -> bool:
    """Store complete catalog to Redis."""
    try:
        import redis

        r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
        r.setex(REDIS_KEY, REDIS_TTL, json.dumps(data, ensure_ascii=False))
        # Also store notable separately for backward compat
        notable_data = {
            "models": data.get("notable_unconfigured", []),
            "synced_at": data.get("synced_at"),
        }
        r.setex(REDIS_KEY_NOTABLE, REDIS_TTL, json.dumps(notable_data, ensure_ascii=False))
        log(f"Stored full catalog to Redis ({len(json.dumps(data))} bytes)")
        return True
    except Exception as e:
        log(f"ERROR: Redis store failed: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────


def main() -> int:
    log("=== Model Catalog Full Sync Start ===")

    # 1. Parse LiteLLM config
    config_data = parse_litellm_config()
    configured = config_data["configured_providers"]
    log(f"Configured providers: {sorted(configured)}")
    log(f"Models in config: {len(config_data['models'])}")

    # 2. Scrape Arena
    arena_text = scrape_arena()
    if not arena_text:
        log("ERROR: No data from Arena — using fallback")
        return 1

    raw_dir = LOG_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "arena_raw.txt").write_text(arena_text)

    arena_models = parse_all_arena_models(arena_text)
    log(f"Arena: parsed {len(arena_models)} models total")

    # 3. Generate all 4 sections
    ts = datetime.now(UTC).isoformat()

    benchmark = generate_benchmark_highlights(arena_models, configured)
    log(f"Benchmark highlights: {list(benchmark.keys())}")

    scenarios = generate_scenarios(arena_models, configured)
    log(f"Scenarios: {len(scenarios)} tasks")

    subjective = generate_subjective(config_data)
    log(f"Subjective picks: {list(subjective.keys())}")

    notable = generate_notable_unconfigured(arena_models, configured)
    log(f"Notable unconfigured: {len(notable)} models")
    for m in notable:
        log(f"  {m['name']:30s} {m['score']:>10s} ({m['provider']})")

    # 4. Store
    full_catalog = {
        "highlights_benchmark": benchmark,
        "scenarios": scenarios,
        "highlights_subjective": subjective,
        "notable_unconfigured": notable,
        "synced_at": ts,
        "source": "lmsys_arena + litellm_config",
        "arena_model_count": len(arena_models),
    }

    store_full_catalog(full_catalog)

    # Fallback JSON
    Path("/tmp/agent-metrics-model-catalog-full.json").write_text(
        json.dumps(full_catalog, indent=2, ensure_ascii=False)
    )

    log("=== Model Catalog Full Sync Done ===")
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
