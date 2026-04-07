#!/usr/bin/env python3
"""
ws_model_freshness_scan.py — Weekly LLM provider model freshness scan

Queries 7 provider model-list APIs, compares against ~/.config/litellm/config.yaml,
generates drift report, stores in Redis + JSON file, sends Bark notification.

Runs weekly via Cronicle (Sunday 16:30).
Logs: ~/workshop/outputs/scheduler/logs/ws-model-freshness-scan.log
"""

import fcntl
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
CONFIG_PATH = HOME / ".config/litellm/config.yaml"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-model-freshness-scan.log"
REDIS_KEY = "agent-metrics:litellm:model_freshness"
REDIS_TTL = 86400 * 14  # 14 days
BARK_URL = "http://127.0.0.1:8090"
BARK_KEY = os.environ.get("BARK_KEY", "")
REQUEST_TIMEOUT = 15  # seconds per API call

os.environ["PATH"] = (
    f"/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:"
    f"/usr/sbin:/sbin:{HOME}/.local/bin:{os.environ.get('PATH', '')}"
)

# Skip these model name patterns when detecting "new" models (non-text)
SKIP_PATTERNS = {"embed", "tts", "speech", "image", "video", "audio", "vision", "moderation"}

# ── Provider API endpoints ─────────────────────────────────────
PROVIDER_APIS = {
    "zhipu": {
        "url": "https://api.z.ai/api/paas/v4/models",
        "response_path": "data",  # response.data[].id
    },
    "moonshot": {
        "url": "https://api.moonshot.ai/v1/models",
        "response_path": "data",
    },
    "minimax": {
        "url": "https://platform.minimax.io/docs/guides/models-intro",
        "scan_method": "camoufox",  # No /models API — scrape docs page
    },
    "deepseek": {
        "url": "https://api.deepseek.com/models",
        "response_path": "data",
    },
    "xai": {
        "url": "https://api.x.ai/v1/models",
        "response_path": "data",
    },
    "dashscope": {
        "url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
        "response_path": "data",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "response_path": "models",  # response.models[].name (prefixed with "models/")
        "auth_method": "query_param",  # use ?key= instead of Bearer
        "id_field": "name",  # field name for model ID
        "id_prefix": "models/",  # strip this prefix from IDs
    },
}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Config parser ──────────────────────────────────────────────


def parse_config() -> list[dict]:
    """Parse config.yaml and return list of model entries with provider info."""
    import yaml

    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    entries = []
    for m in cfg.get("model_list", []):
        params = m.get("litellm_params", {})
        model_str = params.get("model", "")
        api_base = params.get("api_base", "")
        api_key = params.get("api_key", "")
        model_name = m.get("model_name", "")

        # Detect provider
        provider = _detect_provider(model_str, api_base)
        if not provider:
            continue

        # Extract actual model ID (strip litellm prefix)
        parts = model_str.split("/", 1)
        model_id = parts[1] if len(parts) > 1 else model_str

        # Resolve env var references for api_key
        if api_key.startswith("os.environ/"):
            env_var = api_key.split("/", 1)[1]
            api_key = os.environ.get(env_var, "")

        entries.append(
            {
                "model_name": model_name,
                "model_id": model_id,
                "provider": provider,
                "api_key": api_key,
            }
        )

    return entries


def _detect_provider(model_str: str, api_base: str) -> str | None:
    """Map a litellm model string to our provider name. Returns None for skip."""
    prefix = model_str.split("/")[0] if "/" in model_str else ""

    if prefix == "openai":
        if "api.z.ai" in api_base:
            return "zhipu"
        # Skip self-hosted and zen models
        return None

    provider_map = {
        "moonshot": "moonshot",
        "minimax": "minimax",
        "deepseek": "deepseek",
        "xai": "xai",
        "dashscope": "dashscope",
        "gemini": "gemini",
    }
    return provider_map.get(prefix)


# ── API query ──────────────────────────────────────────────────


def _query_camoufox(provider: str, url: str) -> list[str] | None:
    """Scrape a docs page with camoufox-cli to extract model names."""
    import re
    import subprocess

    session = f"freshness-{provider}"
    try:
        # Open page
        r = subprocess.run(
            [
                "camoufox-cli",
                "--session",
                session,
                "--persistent",
                str(HOME / ".camoufox-profiles/master"),
                "open",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode != 0:
            log(f"  [{provider}] camoufox open failed: {r.stderr[:100]}")
            return None

        time.sleep(5)

        # Extract body text
        r = subprocess.run(
            [
                "camoufox-cli",
                "--session",
                session,
                "eval",
                "document.body.innerText.substring(0, 10000)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        text = r.stdout if r.returncode == 0 else ""

        # Parse MiniMax text model IDs from docs page
        # Pattern: "MiniMax-M2.7", "MiniMax-M2.5", "M2-her" etc in the Text table
        models = []
        for m in re.finditer(r"(MiniMax-M[\d.]+(?:-highspeed)?|M\d+-\w+)", text):
            raw = m.group(1).lower().replace("minimax-", "minimax-")
            # Normalize to API format: MiniMax-M2.7 → minimax-m2.7
            if raw.startswith("minimax-"):
                models.append(raw)
            elif raw.startswith("m2-"):
                models.append(raw)
        return list(dict.fromkeys(models))  # deduplicate preserving order

    except subprocess.TimeoutExpired:
        log(f"  [{provider}] camoufox timeout")
        return None
    except Exception as e:
        log(f"  [{provider}] camoufox error: {e}")
        return None
    finally:
        try:
            subprocess.run(
                ["camoufox-cli", "--session", session, "close"],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass


def query_models(provider: str, api_key: str) -> list[str] | None:
    """Query a provider's model listing API. Returns list of model IDs or None on failure."""
    cfg = PROVIDER_APIS.get(provider)
    if not cfg:
        return None

    # Camoufox scraping for providers without /models API
    if cfg.get("scan_method") == "camoufox":
        return _query_camoufox(provider, cfg["url"])

    url = cfg["url"]
    auth_method = cfg.get("auth_method", "bearer")
    response_path = cfg.get("response_path", "data")
    id_field = cfg.get("id_field", "id")
    id_prefix = cfg.get("id_prefix", "")

    # Build request
    if auth_method == "query_param":
        url = f"{url}?key={api_key}&pageSize=100"
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")

    req.add_header("Accept", "application/json")

    # SSL context (some providers need it)
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        log(f"  [{provider}] HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        log(f"  [{provider}] request failed: {e}")
        return None

    # Extract model IDs from response
    items = body.get(response_path, [])
    if not isinstance(items, list):
        log(f"  [{provider}] unexpected response structure")
        return None

    model_ids = []
    for item in items:
        mid = item.get(id_field, "") if isinstance(item, dict) else str(item)
        if id_prefix and mid.startswith(id_prefix):
            mid = mid[len(id_prefix) :]
        model_ids.append(mid)

    return model_ids


def _is_text_model(model_id: str) -> bool:
    """Filter out non-text models (embedding, TTS, image, etc.)."""
    lower = model_id.lower()
    return not any(pat in lower for pat in SKIP_PATTERNS)


# ── Comparison ─────────────────────────────────────────────────


def scan_provider(provider: str, configured: list[dict], api_key: str) -> dict:
    """Scan one provider. Returns result dict."""
    configured_ids = {e["model_id"] for e in configured}
    configured_names = {e["model_id"]: e["model_name"] for e in configured}

    available = query_models(provider, api_key)
    if available is None:
        return {
            "provider": provider,
            "status": "api_failed",
            "configured_count": len(configured_ids),
            "deprecated": [],
            "new_available": [],
        }

    available_set = set(available)
    available_text = {m for m in available if _is_text_model(m)}

    # Configured but not in API → possibly deprecated
    deprecated = []
    for mid in configured_ids:
        if mid not in available_set:
            deprecated.append(
                {
                    "model_name": configured_names.get(mid, mid),
                    "configured_id": mid,
                    "status": "not_found_in_api",
                }
            )

    # In API but not configured (text models only, capped at 20)
    new_available = sorted(available_text - configured_ids)
    if len(new_available) > 20:
        new_available = new_available[:20]  # cap noise for providers with 100+ models

    return {
        "provider": provider,
        "status": "ok",
        "configured_count": len(configured_ids),
        "available_count": len(available),
        "available_text_count": len(available_text),
        "deprecated": deprecated,
        "new_available": new_available,
    }


# ── Notification ───────────────────────────────────────────────


def bark_notify(title: str, body: str) -> None:
    if not BARK_KEY:
        log("BARK_KEY not set, skip notification")
        return
    encoded_title = urllib.parse.quote(title)
    encoded_body = urllib.parse.quote(body)
    url = f"{BARK_URL}/{BARK_KEY}/{encoded_title}/{encoded_body}?group=litellm&sound=minuet"
    try:
        urllib.request.urlopen(url, timeout=10)
        log(f"Bark notification sent: {title}")
    except Exception as e:
        log(f"Bark notification failed: {e}")


# ── Storage ────────────────────────────────────────────────────


def store_report(report: dict) -> None:
    """Store report to Redis + JSON file."""
    # JSON file
    date_str = datetime.now().strftime("%Y%m%d")
    report_path = LOG_DIR / f"model-freshness-{date_str}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    log(f"Report saved to {report_path}")

    # Redis
    try:
        import redis

        r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
        r.setex(REDIS_KEY, REDIS_TTL, json.dumps(report, ensure_ascii=False))
        log("Report stored in Redis")
    except Exception as e:
        log(f"Redis store failed (non-fatal): {e}")


# ── Main ───────────────────────────────────────────────────────


def main() -> int:
    log("=== Model Freshness Scan Start ===")

    # Parse config
    try:
        entries = parse_config()
    except Exception as e:
        log(f"ERROR: Failed to parse config.yaml: {e}")
        return 1

    # Group by provider
    by_provider: dict[str, list[dict]] = {}
    api_keys: dict[str, str] = {}
    for e in entries:
        prov = e["provider"]
        by_provider.setdefault(prov, []).append(e)
        if e["api_key"]:
            api_keys[prov] = e["api_key"]  # all models share key per provider

    log(f"Config: {len(entries)} models across {len(by_provider)} providers")

    # Scan each provider
    results = []
    total_deprecated = 0
    total_new = 0
    providers_failed = []

    for provider in sorted(PROVIDER_APIS.keys()):
        configured = by_provider.get(provider, [])
        key = api_keys.get(provider, "")

        if not configured:
            log(f"  [{provider}] no configured models, skipping")
            continue

        if not key:
            log(f"  [{provider}] no API key found, skipping")
            providers_failed.append(provider)
            continue

        log(f"  [{provider}] scanning ({len(configured)} configured)...")
        result = scan_provider(provider, configured, key)
        results.append(result)

        if result["status"] == "api_failed":
            providers_failed.append(provider)
            log(f"  [{provider}] API query failed")
        else:
            n_dep = len(result["deprecated"])
            n_new = len(result["new_available"])
            total_deprecated += n_dep
            total_new += n_new
            log(
                f"  [{provider}] OK: {n_dep} deprecated, {n_new} new, {result['available_text_count']} text models available"
            )

    # Build report
    action_needed = total_deprecated > 0 or total_new > 0
    report = {
        "scanned_at": datetime.now(UTC).isoformat(),
        "providers_checked": len(results),
        "providers_failed": providers_failed,
        "configured_models": len(entries),
        "total_deprecated": total_deprecated,
        "total_new_available": total_new,
        "action_needed": action_needed,
        "results": results,
    }

    # Store
    store_report(report)

    # Notify
    if action_needed:
        parts = []
        if total_deprecated:
            parts.append(f"{total_deprecated} deprecated")
        if total_new:
            parts.append(f"{total_new} new")
        bark_notify("LiteLLM Model Drift", ", ".join(parts))
    else:
        log("No drift detected, skipping notification")

    log(
        f"=== Model Freshness Scan Done: {len(results)} providers, action_needed={action_needed} ==="
    )
    return 0


if __name__ == "__main__":
    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    sys.exit(main())
