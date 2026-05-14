#!/usr/bin/env python3
"""
ws_model_catalog_sync.py — Weekly model catalog sync from LLM leaderboards

[DEPRECATED 2026-04-20] Replaced by Rust implementation.
  Active runner: stations/agent-metrics/src/collectors/model_catalog.rs
  Cronicle command: agent-metrics model-catalog-sync (Mon 19:00)

This Python module is kept for 30-day rollback only. To re-enable:
  1. Edit schedules/manifest.json → restore command:
     "~/.local/bin/python3 ~/workshop/schedules/runners/ws_model_catalog_sync.py"
  2. Run: ~/.local/bin/python3 ~/workshop/schedules/scheduler.py remove ws-model-catalog-sync
          ~/.local/bin/python3 ~/workshop/schedules/sync.py
After 2026-05-20 with no rollback this file may be deleted.

──── Original docstring ────────────────────────────────────────
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


# ── Multi-Source Scraping (Consensus Ranking) ─────────────────
#
# 4 independent sources to prevent single-source bias:
#   1. LMSYS Chatbot Arena — crowd blind-test Elo
#   2. LiveBench — auto-updated monthly benchmark
#   3. ArtificialAnalysis.ai — speed + quality + price
#   4. OpenRouter rankings — real market usage
#
LEADERBOARD_SOURCES = [
    {
        "name": "arena",
        "url": "https://lmarena.ai/?leaderboard",
        "label": "LMSYS Chatbot Arena",
        "wait": 8,
    },
    {
        "name": "livebench",
        "url": "https://livebench.ai/",
        "label": "LiveBench",
        "wait": 6,
    },
    {
        "name": "artificialanalysis",
        "url": "https://artificialanalysis.ai/leaderboards/models",
        "label": "ArtificialAnalysis.ai",
        "wait": 6,
    },
    {
        "name": "openrouter",
        "url": "https://openrouter.ai/rankings",
        "label": "OpenRouter Rankings",
        "wait": 5,
    },
]


def _cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["camoufox-cli", "--session", CFX_SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def scrape_all_sources() -> dict[str, str]:
    """Scrape all leaderboard sources sequentially with one browser session."""
    results: dict[str, str] = {}
    try:
        first = LEADERBOARD_SOURCES[0]
        open_r = _cfx("--persistent", "open", first["url"])
        if open_r.returncode != 0:
            log(f"ERROR: cfx open failed: {open_r.stderr[:200]}")
            return {}
        time.sleep(first["wait"])
        eval_r = _cfx("eval", "document.body.innerText.substring(0, 20000)", timeout=20)
        results[first["name"]] = eval_r.stdout if eval_r.returncode == 0 else ""
        log(f"  [{first['name']}] scraped {len(results[first['name']])} chars")

        for src in LEADERBOARD_SOURCES[1:]:
            _cfx("open", src["url"], timeout=20)
            time.sleep(src["wait"])
            eval_r = _cfx("eval", "document.body.innerText.substring(0, 20000)", timeout=20)
            results[src["name"]] = eval_r.stdout if eval_r.returncode == 0 else ""
            log(f"  [{src['name']}] scraped {len(results.get(src['name'], ''))} chars")

    except subprocess.TimeoutExpired:
        log("ERROR: scrape timeout")
    except Exception as e:
        log(f"ERROR: scrape failed: {e}")
    finally:
        try:
            _cfx("close", timeout=10)
        except Exception:
            pass
    return results


def _parse_scores_from_text(text: str) -> list[dict]:
    """Extract model name + numeric score pairs from leaderboard text."""
    if not text:
        return []
    models = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Look for 4-digit scores (Elo range 1100-1600) or percentage scores
        elo_match = re.search(r"(\d{4})", line)
        if elo_match:
            score = int(elo_match.group(1))
            if 1100 <= score <= 1600:
                name = line[: elo_match.start()].strip().rstrip("-").strip()
                if 3 <= len(name) <= 60:
                    models.append({"name": name, "score": score})
        # Also try percentage scores (e.g., "85.3%")
        pct_match = re.search(r"([\d.]+)%", line)
        if pct_match and not elo_match:
            score = float(pct_match.group(1))
            if 30 <= score <= 100:
                name = line[: pct_match.start()].strip().rstrip("-").strip()
                if 3 <= len(name) <= 60:
                    models.append({"name": name, "score": score})
    return models


def merge_multi_source_rankings(raw_texts: dict[str, str]) -> list[dict]:
    """Merge rankings from multiple sources into consensus scores.

    Uses Borda count: each source ranks models, position → points.
    Models appearing in more sources get a bonus.
    """
    # Parse each source
    source_rankings: dict[str, list[dict]] = {}
    for source_name, text in raw_texts.items():
        if not text:
            continue
        models = _parse_scores_from_text(text)
        # Deduplicate by name (keep highest score)
        seen = {}
        for m in models:
            key = m["name"].lower()
            if key not in seen or m["score"] > seen[key]["score"]:
                seen[key] = m
        source_rankings[source_name] = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    if not source_rankings:
        return []

    # Borda count: rank position → points (1st = 100, 2nd = 99, ...)
    model_points: dict[
        str, dict
    ] = {}  # name_lower → {name, total_points, source_count, best_score}
    for _source_name, ranked in source_rankings.items():
        for rank, m in enumerate(ranked[:100]):  # Top 100 per source
            key = m["name"].lower()
            points = 100 - rank
            if key not in model_points:
                model_points[key] = {
                    "name": m["name"],
                    "total_points": 0,
                    "source_count": 0,
                    "best_score": 0,
                    "sources": [],
                }
            model_points[key]["total_points"] += points
            model_points[key]["source_count"] += 1
            model_points[key]["sources"].append(_source_name)
            if m["score"] > model_points[key]["best_score"]:
                model_points[key]["best_score"] = m["score"]
                model_points[key]["name"] = m["name"]  # Keep best-scoring variant's name

    # Multi-source bonus: models in 3+ sources get 50% bonus
    for info in model_points.values():
        if info["source_count"] >= 3:
            info["total_points"] = int(info["total_points"] * 1.5)
        elif info["source_count"] >= 2:
            info["total_points"] = int(info["total_points"] * 1.2)

    # Sort by total points
    merged = sorted(model_points.values(), key=lambda x: x["total_points"], reverse=True)

    return [
        {
            "name": m["name"],
            "elo": int(m["best_score"]) if m["best_score"] >= 1000 else 0,
            "consensus_score": m["total_points"],
            "source_count": m["source_count"],
        }
        for m in merged
    ]


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
    log("=== Model Catalog Full Sync Start (Multi-Source) ===")

    # 1. Parse LiteLLM config
    config_data = parse_litellm_config()
    configured = config_data["configured_providers"]
    log(f"Configured providers: {sorted(configured)}")
    log(f"Models in config: {len(config_data['models'])}")

    # 2. Scrape 4 leaderboard sources
    raw_texts = scrape_all_sources()
    sources_ok = [k for k, v in raw_texts.items() if v]
    log(f"Sources scraped: {len(sources_ok)}/{len(LEADERBOARD_SOURCES)} ({', '.join(sources_ok)})")

    if not sources_ok:
        log("ERROR: No data from any source")
        return 1

    # Save raw texts for debugging
    raw_dir = LOG_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, text in raw_texts.items():
        if text:
            (raw_dir / f"{name}_raw.txt").write_text(text)

    # 3. Merge into consensus ranking
    arena_models = merge_multi_source_rankings(raw_texts)
    log(f"Consensus ranking: {len(arena_models)} models (from {len(sources_ok)} sources)")
    for m in arena_models[:10]:
        log(
            f"  #{arena_models.index(m) + 1:2d}  {m['name']:30s}  score={m['consensus_score']:>4d}  sources={m['source_count']}"
        )

    # 4. Generate all 4 sections
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

    # 5. Store
    full_catalog = {
        "highlights_benchmark": benchmark,
        "scenarios": scenarios,
        "highlights_subjective": subjective,
        "notable_unconfigured": notable,
        "synced_at": ts,
        "sources_used": sources_ok,
        "source_count": len(sources_ok),
        "consensus_model_count": len(arena_models),
    }

    store_full_catalog(full_catalog)

    # Fallback JSON
    Path("/tmp/agent-metrics-model-catalog-full.json").write_text(
        json.dumps(full_catalog, indent=2, ensure_ascii=False)
    )

    log(f"=== Model Catalog Full Sync Done ({len(sources_ok)} sources) ===")
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
