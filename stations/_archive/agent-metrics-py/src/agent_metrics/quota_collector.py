"""LLM Quota Collector — Claude Code, Codex, Gemini (full Python port).

Replaces quota-all.sh with async Python. All three providers are fetched
in parallel with TTL cache. Results are merged into sysmon snapshots
and written to /tmp for tmux consumption.

CC quota strategy (15-min interval):
  1. Anthropic OAuth API (fast, preferred)
  2. Playwright CLI scrape of claude.ai/settings/usage (fallback)
  3. Persisted file from last success (restart resilience)
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import httpx
import redis
import structlog

from agent_metrics.config import settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Redis cache (replaces in-memory _cache / _raw_cache / _cc_raw_result)
# ---------------------------------------------------------------------------
_r: redis.Redis | None = None


def _get_redis() -> redis.Redis | None:
    """Lazy-init Redis client — avoids crash if Redis is down at import time."""
    global _r
    if _r is not None:
        return _r
    try:
        _r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        _r.ping()
        return _r
    except Exception:
        _r = None
        return None


_RKEY_FORMATTED = "agent-metrics:quota:formatted"
_RKEY_RAW = "agent-metrics:quota:raw"
_RKEY_CC_RAW = "agent-metrics:quota:cc_raw"

# Gemini project ID cache (1h TTL, in-memory is fine — token-specific)
_gm_project: str = ""
_gm_project_ts: float = 0.0
_GM_PROJECT_TTL = 3600.0

# CC quota persistence path (disk fallback for restart resilience)
_CC_PERSIST_PATH = Path("/tmp/agent-metrics-cc-quota.json")

# CC-specific result (in-process fallback alongside Redis)
_cc_raw_result: dict = {}
_cc_raw_result_ts: float = 0.0

# Claude quota state (for 429 backoff + fallback visibility)
_cc_last_success: dict = {}
_cc_last_success_ts: float = 0.0
_cc_backoff_until: float = 0.0
_cc_consecutive_failures: int = 0
_cc_last_status_code: int | None = None
_cc_last_error: str | None = None
_cc_last_fetch_mode: str = "init"  # live | camoufox | backoff_fallback | error_fallback | failed

# Browser scrape lock — prevent concurrent camoufox sessions
_cfx_scrape_lock = asyncio.Lock()


def _persist_cc_quota(data: dict, source: str = "api") -> None:
    """Save last successful CC quota to disk for restart resilience."""
    try:
        payload = {"data": data, "ts": time.time(), "source": source}
        _CC_PERSIST_PATH.write_text(json.dumps(payload))
    except OSError:
        pass


def _load_persisted_cc_quota() -> None:
    """Load persisted CC quota on startup — seed Redis if empty."""
    global _cc_last_success, _cc_last_success_ts
    if _cc_last_success:
        return
    # Check Redis first
    r = _get_redis()
    try:
        cached = r.get(_RKEY_CC_RAW) if r else None
        if cached:
            data = json.loads(cached)
            _cc_last_success = data
            _cc_last_success_ts = time.time()
            log.info("cc_quota_loaded_from_redis")
            return
    except Exception:
        pass
    # Fall back to disk
    try:
        if _CC_PERSIST_PATH.exists():
            payload = json.loads(_CC_PERSIST_PATH.read_text())
            data = payload.get("data", {})
            ts = payload.get("ts", 0.0)
            if data and (time.time() - ts) <= settings.CC_QUOTA_STALE_MAX_SECONDS:
                _cc_last_success = data
                _cc_last_success_ts = ts
                # Seed Redis from disk
                if r:
                    r.setex(_RKEY_CC_RAW, settings.CC_QUOTA_FETCH_INTERVAL, json.dumps(data))
                source = payload.get("source", "disk")
                log.info("cc_quota_loaded_from_disk", age_s=int(time.time() - ts), source=source)
    except (OSError, json.JSONDecodeError, KeyError):
        pass


# Load persisted data at import time
_load_persisted_cc_quota()


# ---------------------------------------------------------------------------
# Claude Code — Anthropic OAuth usage API
# ---------------------------------------------------------------------------


async def fetch_cc_quota(client: httpx.AsyncClient) -> dict:
    """Fetch Claude Code quota from Anthropic OAuth API via macOS Keychain."""
    global _cc_last_success, _cc_last_success_ts, _cc_backoff_until, _cc_consecutive_failures
    global _cc_last_status_code, _cc_last_error, _cc_last_fetch_mode

    now = time.time()
    if _cc_backoff_until > now:
        if _cc_last_success:
            _cc_last_fetch_mode = "backoff_fallback"
            return _cc_last_success
        _cc_last_fetch_mode = "failed"
        return {}

    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if not raw:
            return {}

        creds = json.loads(raw)
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if not token:
            return {}

        resp = await client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
            timeout=5,
        )
        if resp.status_code == 429:
            _cc_consecutive_failures += 1
            retry_after = resp.headers.get("retry-after", "")
            try:
                retry_seconds = int(float(retry_after))
            except ValueError:
                retry_seconds = 0
            # Exponential backoff: 1800s, 3600s, 7200s, 14400s, 28800s (cap 8h)
            base_backoff = settings.CC_QUOTA_BACKOFF_SECONDS * (
                2 ** min(_cc_consecutive_failures - 1, 4)
            )
            backoff = max(base_backoff, retry_seconds)
            _cc_backoff_until = now + backoff
            _cc_last_status_code = 429
            _cc_last_error = "rate_limited"
            log.warning(
                "quota_cc_rate_limited",
                retry_after_s=retry_seconds,
                backoff_s=backoff,
                consecutive=_cc_consecutive_failures,
                has_fallback=bool(_cc_last_success),
            )
            if (
                _cc_last_success
                and (now - _cc_last_success_ts) <= settings.CC_QUOTA_STALE_MAX_SECONDS
            ):
                _cc_last_fetch_mode = "backoff_fallback"
                return _cc_last_success
            _cc_last_fetch_mode = "failed"
            return {}

        resp.raise_for_status()
        data = resp.json()
        _cc_last_success = data
        _cc_last_success_ts = now
        _cc_backoff_until = 0.0
        _cc_consecutive_failures = 0
        _cc_last_status_code = resp.status_code
        _cc_last_error = None
        _cc_last_fetch_mode = "live"
        _persist_cc_quota(data)
        try:
            _r.setex(_RKEY_CC_RAW, settings.CC_QUOTA_FETCH_INTERVAL, json.dumps(data))
        except Exception:
            pass
        return data
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else None
        _cc_last_status_code = status
        _cc_last_error = f"http_status_{status}" if status else "http_status_error"
        log.warning("quota_cc_http_status_error", status_code=status)
        if _cc_last_success and (now - _cc_last_success_ts) <= settings.CC_QUOTA_STALE_MAX_SECONDS:
            _cc_last_fetch_mode = "error_fallback"
            return _cc_last_success
        _cc_last_fetch_mode = "failed"
        return {}
    except Exception:
        _cc_last_status_code = None
        _cc_last_error = "fetch_failed"
        if _cc_last_success and (now - _cc_last_success_ts) <= settings.CC_QUOTA_STALE_MAX_SECONDS:
            _cc_last_fetch_mode = "error_fallback"
            return _cc_last_success
        _cc_last_fetch_mode = "failed"
        log.debug("quota_cc_fetch_failed", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Claude Code — camoufox-cli fallback (anti-detect Firefox with persistent cookies)
# ---------------------------------------------------------------------------

_CFX_SESSION = "ccq-scrape"


def _scrape_usage_page() -> dict:
    """Sync: camoufox-cli with persistent profile → open claude.ai/settings/usage → eval → close.

    Uses camoufox-cli with ~/.camoufox-profiles/master (cookies maintained by user).
    No APFS clone needed — camoufox uses persistent Firefox profile directly.

    Returns data in the same shape as the OAuth API: {five_hour: {utilization: N}, ...}
    """
    import time as _time

    usage_url = "https://claude.ai/settings/usage"

    try:
        # 1. Open usage page with persistent profile (cookies handle auth)
        open_result = subprocess.run(
            [
                "camoufox-cli",
                "--session",
                _CFX_SESSION,
                "--persistent",
                "open",
                usage_url,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if open_result.returncode != 0:
            log.warning(
                "cfx_scrape_open_failed",
                rc=open_result.returncode,
                stderr=open_result.stderr[:200],
            )
            return {}

        # 2. Check if SSO redirected away — navigate back to usage page
        _time.sleep(4)

        loc_result = subprocess.run(
            ["camoufox-cli", "--session", _CFX_SESSION, "eval", "window.location.href"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "/settings/usage" not in loc_result.stdout:
            subprocess.run(
                ["camoufox-cli", "--session", _CFX_SESSION, "open", usage_url],
                capture_output=True,
                text=True,
                timeout=15,
            )
            _time.sleep(3)

        # 3. Poll until usage content appears (up to 16s)
        for _ in range(8):
            snap = subprocess.run(
                [
                    "camoufox-cli",
                    "--session",
                    _CFX_SESSION,
                    "eval",
                    "document.body.innerText.substring(0, 500)",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "current session" in snap.stdout.lower():
                break
            _time.sleep(2)

        # 4. Extract full body text
        eval_result = subprocess.run(
            [
                "camoufox-cli",
                "--session",
                _CFX_SESSION,
                "eval",
                "document.body.innerText.substring(0, 4000)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # 5. Close session (profile persists — no cleanup needed)
        subprocess.run(
            ["camoufox-cli", "--session", _CFX_SESSION, "close"],
            capture_output=True,
            timeout=10,
        )

        if eval_result.returncode != 0:
            log.warning(
                "cfx_scrape_eval_failed",
                rc=eval_result.returncode,
                stderr=eval_result.stderr[:200],
            )
            return {}

        # camoufox-cli eval outputs raw text (no JSON wrapping unlike playwright-cli)
        return _parse_usage_page_text(eval_result.stdout)

    except subprocess.TimeoutExpired:
        log.warning("cfx_scrape_timeout")
        return {}
    except Exception:
        log.debug("cfx_scrape_failed", exc_info=True)
        return {}
    finally:
        # Best-effort close if still open
        try:
            subprocess.run(
                ["camoufox-cli", "--session", _CFX_SESSION, "close"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass


def _parse_usage_page_text(text: str) -> dict:
    """Parse body text from claude.ai/settings/usage for usage percentages.

    Page layout (claude.ai Max plan):
      "Current session" → N% used   (= 5-hour window)
      "All models" weekly → N% used (= 7-day window)

    Returns API-compatible dict: {five_hour: {utilization: N}, seven_day: {utilization: N}}
    """
    import re

    if not text or len(text.strip()) < 50:
        return {}

    result: dict = {}
    lines = text.split("\n")

    for i, line in enumerate(lines):
        lower = line.lower().strip()
        # Gather surrounding context (8 lines after — blank lines inflate count)
        ctx = "\n".join(lines[i : min(len(lines), i + 8)])

        # "Current session" = 5h window
        if "current session" in lower:
            pcts = re.findall(r"(\d+(?:\.\d+)?)\s*%", ctx)
            if pcts and "five_hour" not in result:
                result["five_hour"] = {"utilization": float(pcts[0])}

        # "All models" (weekly) = 7d window
        if "all models" in lower:
            pcts = re.findall(r"(\d+(?:\.\d+)?)\s*%", ctx)
            if pcts and "seven_day" not in result:
                result["seven_day"] = {"utilization": float(pcts[0])}

        # "Extra usage" section — "$X.XX spent", "X% used", "$NN limit", balance
        # Wide window (30 lines) to reach "Current balance" past blank lines
        if "extra usage" in lower and "extra_usage" not in result:
            extra_ctx = "\n".join(lines[i : min(len(lines), i + 30)])
            spent_m = re.findall(r"\$(\d+(?:\.\d+)?)\s*spent", extra_ctx)
            pcts = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*used", extra_ctx)
            limit_m = re.search(
                r"\$(\d+(?:\.\d+)?)\s*\n\s*Monthly spend limit",
                extra_ctx,
                re.IGNORECASE,
            )
            balance_m = re.search(
                r"(-?\$\d+(?:\.\d+)?)\s*\n\s*Current balance",
                extra_ctx,
                re.IGNORECASE,
            )
            if pcts or spent_m:
                ex: dict = {"is_enabled": True}
                if spent_m:
                    ex["used_credits"] = int(float(spent_m[0]) * 100)
                if limit_m:
                    ex["monthly_limit"] = int(float(limit_m.group(1)) * 100)
                if pcts:
                    ex["utilization"] = float(pcts[0])
                if balance_m:
                    bal_str = balance_m.group(1).replace("$", "")
                    ex["balance_cents"] = int(float(bal_str) * 100)
                result["extra_usage"] = ex

    if result:
        log.info(
            "cfx_scrape_parsed",
            five_hour=result.get("five_hour"),
            seven_day=result.get("seven_day"),
            extra_usage=result.get("extra_usage"),
        )

    return result


async def _fetch_cc_via_camoufox() -> dict:
    """Async wrapper: run camoufox scrape in executor (with lock to prevent concurrent sessions)."""
    global _cc_last_fetch_mode
    if _cfx_scrape_lock.locked():
        log.debug("cfx_scrape_already_running")
        return {}
    async with _cfx_scrape_lock:
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, _scrape_usage_page)
            if data:
                _cc_last_fetch_mode = "camoufox"
            return data
        except Exception:
            log.debug("cfx_cc_async_failed", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Codex / ChatGPT — wham/usage API
# ---------------------------------------------------------------------------


async def fetch_cx_quota(client: httpx.AsyncClient) -> dict:
    """Fetch Codex/ChatGPT quota from backend API."""
    try:
        auth_path = Path(settings.CODEX_AUTH_PATH).expanduser()
        if not auth_path.exists():
            return {}

        auth = json.loads(auth_path.read_text())
        tokens = auth.get("tokens", {})
        token = tokens.get("access_token", "")
        acct = tokens.get("account_id", "")
        if not token or not acct:
            return {}

        resp = await client.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "ChatGPT-Account-Id": acct,
            },
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.debug("quota_cx_fetch_failed", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Gemini — CodeAssist retrieveUserQuota API
# ---------------------------------------------------------------------------


def _ensure_gemini_token() -> str | None:
    """Ensure Gemini OAuth token is fresh, refresh if needed. Synchronous."""
    oauth_path = Path(settings.GM_OAUTH_PATH).expanduser()
    if not oauth_path.exists():
        return None

    creds = json.loads(oauth_path.read_text())
    token = creds.get("access_token", "")
    expiry = creds.get("expiry_date", 0)
    now_ms = int(time.time() * 1000)

    if expiry > now_ms + 300_000:
        return token

    refresh_token = creds.get("refresh_token", "")
    if not refresh_token:
        return token or None

    try:
        import urllib.parse
        import urllib.request

        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.GM_CLIENT_ID,
                "client_secret": settings.GM_CLIENT_SECRET,
            }
        ).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=body,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        new_token = data.get("access_token", "")
        if new_token:
            creds["access_token"] = new_token
            creds["expiry_date"] = int(time.time() * 1000) + data.get("expires_in", 3600) * 1000
            oauth_path.write_text(json.dumps(creds))
            return new_token
    except Exception:
        log.debug("gemini_token_refresh_failed", exc_info=True)

    return token or None


async def _get_gemini_project(client: httpx.AsyncClient, token: str) -> str:
    """Get Gemini managed project ID (cached 1h)."""
    global _gm_project, _gm_project_ts

    now = time.time()
    if _gm_project and (now - _gm_project_ts) < _GM_PROJECT_TTL:
        return _gm_project

    try:
        resp = await client.post(
            "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
            json={},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        pid = data.get("cloudaicompanionProject", "")
        if pid:
            _gm_project = pid
            _gm_project_ts = now
    except Exception:
        log.debug("gemini_project_fetch_failed", exc_info=True)

    return _gm_project


async def fetch_gm_quota(client: httpx.AsyncClient) -> dict:
    """Fetch Gemini quota from CodeAssist API."""
    try:
        token = _ensure_gemini_token()
        if not token:
            return {}

        project = await _get_gemini_project(client, token)
        if not project:
            return {}

        resp = await client.post(
            "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
            json={"project": f"projects/{project}"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.debug("quota_gm_fetch_failed", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Unified quota fetch
# ---------------------------------------------------------------------------


async def get_quota(force: bool = False) -> dict:
    """Fetch all LLM quotas. CC at 15-min interval, CX/GM at QUOTA_CACHE_TTL."""
    global _cc_raw_result, _cc_raw_result_ts

    # Check Redis cache first
    if not force:
        try:
            cached = _r.get(_RKEY_FORMATTED)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    now = time.time()

    # CC: check Redis for cc_raw freshness
    cc_raw_cached = None
    try:
        cc_raw_cached = _r.get(_RKEY_CC_RAW)
    except Exception:
        pass
    fetch_cc = force or not cc_raw_cached
    cc_raw = {}  # initialize before conditional branches

    # If API is in backoff, skip API entirely and go straight to Playwright
    cc_in_backoff = _cc_backoff_until > now

    async with httpx.AsyncClient() as client:
        coros: list = [fetch_cx_quota(client), fetch_gm_quota(client)]
        if fetch_cc and not cc_in_backoff:
            coros.append(fetch_cc_quota(client))
        results = await asyncio.gather(*coros, return_exceptions=True)

    cx_raw = results[0] if not isinstance(results[0], Exception) else {}
    gm_raw = results[1] if not isinstance(results[1], Exception) else {}

    if fetch_cc:
        if cc_in_backoff:
            # API in backoff — go directly to Playwright
            cc_raw = {}
            log.info(
                "cc_api_in_backoff_using_camoufox",
                backoff_remaining_s=int(_cc_backoff_until - now),
            )
        else:
            cc_raw = results[2] if not isinstance(results[2], Exception) else {}

        # Camoufox fallback if API returned nothing or used stale/fallback cache
        if not cc_raw or _cc_last_fetch_mode in ("backoff_fallback", "error_fallback", "failed"):
            cfx_data = await _fetch_cc_via_camoufox()
            if cfx_data:
                cc_raw = cfx_data
        if cc_raw:
            _cc_raw_result = cc_raw
            _cc_raw_result_ts = now
            _persist_cc_quota(cc_raw, source=_cc_last_fetch_mode)
            try:
                _r.setex(_RKEY_CC_RAW, settings.CC_QUOTA_FETCH_INTERVAL, json.dumps(cc_raw))
            except Exception:
                pass

    # Use fresh or Redis-cached cc_raw
    if not cc_raw and cc_raw_cached:
        cc_raw = json.loads(cc_raw_cached)
    elif _cc_raw_result:
        cc_raw = _cc_raw_result

    raw_cache = {"cc": cc_raw, "cx": cx_raw, "gm": gm_raw}
    result = format_quota(cc_raw, cx_raw, gm_raw)
    try:
        _r.setex(_RKEY_FORMATTED, settings.QUOTA_CACHE_TTL, json.dumps(result))
        _r.setex(_RKEY_RAW, settings.QUOTA_CACHE_TTL, json.dumps(raw_cache))
    except Exception:
        pass
    return result


def get_quota_sync() -> dict:
    """Synchronous cache reader from Redis (never blocks)."""
    try:
        cached = _r.get(_RKEY_FORMATTED)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return {}


def get_raw_cache() -> dict:
    """Return raw API responses from Redis."""
    try:
        cached = _r.get(_RKEY_RAW)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return {}


def reset_cc_backoff() -> None:
    """Reset CC backoff state (for manual retry)."""
    global _cc_backoff_until, _cc_consecutive_failures
    _cc_backoff_until = 0.0
    _cc_consecutive_failures = 0


def get_quota_health() -> dict:
    """Return fetch health metadata for quota collectors."""
    now = time.time()
    # Use Redis TTL for next_fetch countdown
    try:
        ttl = _r.ttl(_RKEY_CC_RAW)
        next_cc_fetch = max(0, ttl) if ttl and ttl > 0 else 0
    except Exception:
        next_cc_fetch = (
            max(0, int(settings.CC_QUOTA_FETCH_INTERVAL - (now - _cc_raw_result_ts)))
            if _cc_raw_result_ts
            else 0
        )
    return {
        "cc": {
            "last_status_code": _cc_last_status_code,
            "last_error": _cc_last_error,
            "last_fetch_mode": _cc_last_fetch_mode,
            "has_last_success": bool(_cc_last_success),
            "has_cached_result": bool(_cc_raw_result),
            "last_success_age_s": int(now - _cc_last_success_ts) if _cc_last_success_ts else None,
            "cached_result_age_s": int(now - _cc_raw_result_ts) if _cc_raw_result_ts else None,
            "next_fetch_in_s": next_cc_fetch,
            "fetch_interval_s": settings.CC_QUOTA_FETCH_INTERVAL,
            "backoff_remaining_s": int(_cc_backoff_until - now) if _cc_backoff_until > now else 0,
            "in_backoff": _cc_backoff_until > now,
            "consecutive_failures": _cc_consecutive_failures,
        }
    }


# ---------------------------------------------------------------------------
# Format quota for tmux / API
# ---------------------------------------------------------------------------


def _unix_to_iso(ts: int | float | None) -> str | None:
    """Convert unix timestamp to ISO8601 UTC string."""
    if not ts:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError, TypeError):
        return None


def _parse_cc(data: dict) -> dict:
    """Parse Claude Code API response."""
    result: dict = {}
    if "five_hour" in data:
        fh = data["five_hour"] or {}
        result["5h"] = f"{round(fh.get('utilization') or 0)}%"
        if fh.get("resets_at"):
            result["5h_resets_at"] = fh["resets_at"]
    if "seven_day" in data:
        sd = data["seven_day"] or {}
        result["7d"] = f"{round(sd.get('utilization') or 0)}%"
        if sd.get("resets_at"):
            result["7d_resets_at"] = sd["resets_at"]
    if "extra_usage" in data:
        ex = data["extra_usage"]
        enabled = bool(ex.get("is_enabled"))
        result["ex_enabled"] = enabled
        if enabled:
            used = (ex.get("used_credits") or 0) / 100
            limit = (ex.get("monthly_limit") or 0) / 100
            util = ex.get("utilization") or 0
            pct = round(util)
            # API omits balance_cents when it can be derived; fall back to limit - used.
            if ex.get("balance_cents") is not None:
                balance = ex["balance_cents"] / 100
            else:
                balance = max(0.0, limit - used)
            if balance <= 0:
                result["ex"] = f"${used:.2f}/${limit:.0f} {pct}% 余$0"
            else:
                result["ex"] = f"${used:.2f}/${limit:.0f} {pct}% 余${balance:.2f}"
            result["ex_used_usd"] = used
            result["ex_limit_usd"] = limit
            result["ex_balance_usd"] = balance
            result["ex_utilization"] = util
        else:
            result["ex"] = "off"
    return result


def _parse_cx(data: dict) -> dict:
    """Parse Codex/ChatGPT API response."""
    result: dict = {}
    rl = data.get("rate_limit", {})
    pw = rl.get("primary_window", {})
    sw = rl.get("secondary_window", {})
    if pw:
        result["5h"] = f"{pw.get('used_percent', 0)}%"
        iso = _unix_to_iso(pw.get("reset_at"))
        if iso:
            result["5h_resets_at"] = iso
    if sw:
        result["7d"] = f"{sw.get('used_percent', 0)}%"
        iso = _unix_to_iso(sw.get("reset_at"))
        if iso:
            result["7d_resets_at"] = iso
    return result


def _parse_gm(data: dict) -> dict:
    """Parse Gemini API response."""
    result: dict = {}
    earliest_reset: str | None = None
    for bucket in data.get("buckets", []):
        if bucket.get("tokenType") != "REQUESTS":
            continue
        model = bucket.get("modelId", "")
        frac = bucket.get("remainingFraction", 1.0)
        used_pct = round((1 - frac) * 100)
        reset_time = bucket.get("resetTime")
        if reset_time and (earliest_reset is None or reset_time < earliest_reset):
            earliest_reset = reset_time
        if "pro" in model and not model.endswith("_vertex"):
            result["pro"] = f"{used_pct}%"
        if "flash" in model and "lite" not in model and not model.endswith("_vertex"):
            if "flash" not in result or used_pct > int(result["flash"].rstrip("%")):
                result["flash"] = f"{used_pct}%"
    if earliest_reset:
        result["daily_resets_at"] = earliest_reset
    return result


def format_quota(cc_raw: dict, cx_raw: dict, gm_raw: dict) -> dict:
    """Generate formatted quota fields for sysmon snapshot + tmux."""
    cc = _parse_cc(cc_raw)
    cx = _parse_cx(cx_raw)
    gm = _parse_gm(gm_raw)

    parts = []
    if cc:
        parts.append(f"CC:{cc.get('5h', '?')}/{cc.get('7d', '?')}")
    if cx:
        parts.append(f"CX:{cx.get('5h', '?')}/{cx.get('7d', '?')}")
    if gm:
        parts.append(f"GM:{gm.get('pro', '?')}")

    return {
        "llm_cc_5h": cc.get("5h", "?"),
        "llm_cc_7d": cc.get("7d", "?"),
        "llm_cc_ex": cc.get("ex", "?"),
        "llm_cx_5h": cx.get("5h", "?"),
        "llm_cx_7d": cx.get("7d", "?"),
        "llm_gm_pro": gm.get("pro", "?"),
        "llm_gm_flash": gm.get("flash", "?"),
        "llm_cc_5h_resets_at": cc.get("5h_resets_at"),
        "llm_cc_7d_resets_at": cc.get("7d_resets_at"),
        "llm_cx_5h_resets_at": cx.get("5h_resets_at"),
        "llm_cx_7d_resets_at": cx.get("7d_resets_at"),
        "llm_gm_daily_resets_at": gm.get("daily_resets_at"),
        "llm_cc_ex_enabled": cc.get("ex_enabled"),
        "llm_cc_ex_used_usd": cc.get("ex_used_usd"),
        "llm_cc_ex_limit_usd": cc.get("ex_limit_usd"),
        "llm_cc_ex_balance_usd": cc.get("ex_balance_usd"),
        "llm_cc_ex_utilization": cc.get("ex_utilization"),
        "llm_display": " ".join(parts) if parts else "?",
        # Parsed percentages for API consumers
        "cc_parsed": cc,
        "cx_parsed": cx,
        "gm_parsed": gm,
    }
