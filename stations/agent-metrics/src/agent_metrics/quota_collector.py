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
import structlog

from agent_metrics.config import settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Internal cache (general TTL for CX/GM)
# ---------------------------------------------------------------------------
_cache: dict = {}
_cache_ts: float = 0.0

# Raw API response cache (for compat output)
_raw_cache: dict = {}

# CC-specific result cache (15-min interval, separate from CX/GM)
_cc_raw_result: dict = {}
_cc_raw_result_ts: float = 0.0

# Gemini project ID cache (1h TTL)
_gm_project: str = ""
_gm_project_ts: float = 0.0
_GM_PROJECT_TTL = 3600.0

# CC quota persistence path
_CC_PERSIST_PATH = Path("/tmp/agent-metrics-cc-quota.json")

# Claude quota state (for 429 backoff + fallback visibility)
_cc_last_success: dict = {}
_cc_last_success_ts: float = 0.0
_cc_backoff_until: float = 0.0
_cc_consecutive_failures: int = 0
_cc_last_status_code: int | None = None
_cc_last_error: str | None = None
_cc_last_fetch_mode: str = "init"  # live | playwright | backoff_fallback | error_fallback | failed

# Playwright scrape lock — prevent concurrent browser sessions
_pw_scrape_lock = asyncio.Lock()


def _persist_cc_quota(data: dict, source: str = "api") -> None:
    """Save last successful CC quota to disk for restart resilience."""
    try:
        payload = {"data": data, "ts": time.time(), "source": source}
        _CC_PERSIST_PATH.write_text(json.dumps(payload))
    except OSError:
        pass


def _load_persisted_cc_quota() -> None:
    """Load persisted CC quota on startup as fallback seed."""
    global _cc_last_success, _cc_last_success_ts, _cc_raw_result, _cc_raw_result_ts
    if _cc_last_success:
        return
    try:
        if _CC_PERSIST_PATH.exists():
            payload = json.loads(_CC_PERSIST_PATH.read_text())
            data = payload.get("data", {})
            ts = payload.get("ts", 0.0)
            if data and (time.time() - ts) <= settings.CC_QUOTA_STALE_MAX_SECONDS:
                _cc_last_success = data
                _cc_last_success_ts = ts
                _cc_raw_result = data
                _cc_raw_result_ts = ts
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
            # Exponential backoff: 600s, 1200s, 2400s... capped at 1h
            base_backoff = settings.CC_QUOTA_BACKOFF_SECONDS * (
                2 ** min(_cc_consecutive_failures - 1, 3)
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
# Claude Code — Playwright CLI fallback
# ---------------------------------------------------------------------------


def _scrape_usage_page() -> dict:
    """Sync: pw_session clone → open claude.ai → Google SSO → goto usage → eval → cleanup.

    Uses pw_session.py to APFS-clone ~/.playwright-profiles/master (has Google auth),
    then opens a headed browser. Google SSO auto-redirects to /new, so we do a second
    goto to /settings/usage. Extracts body text via `eval` and parses percentages.

    Returns data in the same shape as the OAuth API: {five_hour: {utilization: N}, ...}
    """
    import shutil

    _PYTHON = str(Path.home() / ".local" / "bin" / "python3")
    pw_session = Path(settings.PW_SESSION_SCRIPT)
    if not pw_session.exists():
        log.debug("pw_scrape_skip_no_script", path=str(pw_session))
        return {}

    profile_dir = None
    sid = None

    try:
        # 1. Init session (APFS clone of master profile via pw_session.py)
        init_result = subprocess.run(
            [_PYTHON, str(pw_session), "init"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in init_result.stdout.splitlines():
            if line.startswith("export PW_PROFILE="):
                profile_dir = line.split("=", 1)[1].strip().strip("'\"")
            elif line.startswith("export SID="):
                sid = line.split("=", 1)[1].strip().strip("'\"")

        if not profile_dir or not sid:
            log.warning("pw_scrape_init_failed", stdout=init_result.stdout[:200])
            return {}

        session_id = f"{sid}-ccq"
        usage_url = "https://claude.ai/settings/usage"

        # 2. Open browser (headed — Cloudflare blocks headless)
        open_result = subprocess.run(
            [
                "npx",
                "@playwright/cli",
                f"-s={session_id}",
                "open",
                "--headed",
                "--profile",
                profile_dir,
                usage_url,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if open_result.returncode != 0:
            log.warning(
                "pw_scrape_open_failed", rc=open_result.returncode, stderr=open_result.stderr[:200]
            )
            return {}

        # 3. Wait for Google SSO redirect, then goto usage page
        import time as _time

        _time.sleep(5)

        # Check if we landed on /new (SSO redirect) — need second goto
        loc_result = subprocess.run(
            ["npx", "@playwright/cli", f"-s={session_id}", "eval", "window.location.href"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "/settings/usage" not in loc_result.stdout:
            subprocess.run(
                ["npx", "@playwright/cli", f"-s={session_id}", "goto", usage_url],
                capture_output=True,
                text=True,
                timeout=15,
            )
            _time.sleep(3)

        # 4. Poll until usage content appears (up to 16s)
        for _ in range(8):
            snap = subprocess.run(
                [
                    "npx",
                    "@playwright/cli",
                    f"-s={session_id}",
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

        # 5. Extract full body text via eval
        eval_result = subprocess.run(
            [
                "npx",
                "@playwright/cli",
                f"-s={session_id}",
                "eval",
                "document.body.innerText.substring(0, 4000)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # 6. Close session + cleanup clone
        subprocess.run(
            ["npx", "@playwright/cli", f"-s={session_id}", "close"],
            capture_output=True,
            timeout=10,
        )
        subprocess.run(
            [_PYTHON, str(pw_session), "cleanup", profile_dir],
            capture_output=True,
            timeout=10,
        )
        profile_dir = None  # prevent double cleanup

        # 7. Parse output
        if eval_result.returncode != 0:
            log.warning(
                "pw_scrape_eval_failed", rc=eval_result.returncode, stderr=eval_result.stderr[:200]
            )
            return {}

        return _parse_usage_page_text(eval_result.stdout)

    except subprocess.TimeoutExpired:
        log.warning("pw_scrape_timeout")
        return {}
    except Exception:
        log.debug("pw_scrape_failed", exc_info=True)
        return {}
    finally:
        if profile_dir and sid:
            try:
                subprocess.run(
                    ["npx", "@playwright/cli", f"-s={sid}-ccq", "close"],
                    capture_output=True,
                    timeout=10,
                )
                subprocess.run(
                    [_PYTHON, str(pw_session), "cleanup", profile_dir],
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                shutil.rmtree(profile_dir, ignore_errors=True)


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

    if result:
        log.info(
            "pw_scrape_parsed", five_hour=result.get("five_hour"), seven_day=result.get("seven_day")
        )

    return result


async def _fetch_cc_via_playwright() -> dict:
    """Async wrapper: run Playwright scrape in executor (with lock to prevent concurrent sessions)."""
    global _cc_last_fetch_mode
    if _pw_scrape_lock.locked():
        log.debug("pw_scrape_already_running")
        return {}
    async with _pw_scrape_lock:
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, _scrape_usage_page)
            if data:
                _cc_last_fetch_mode = "playwright"
            return data
        except Exception:
            log.debug("pw_cc_async_failed", exc_info=True)
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
    global _cache, _cache_ts, _raw_cache, _cc_raw_result, _cc_raw_result_ts

    now = time.time()
    if not force and _cache and (now - _cache_ts) < settings.QUOTA_CACHE_TTL:
        return _cache

    # CC: 15-min interval with API → Playwright fallback chain
    fetch_cc = (
        force or not _cc_raw_result or (now - _cc_raw_result_ts) >= settings.CC_QUOTA_FETCH_INTERVAL
    )

    async with httpx.AsyncClient() as client:
        coros: list = [fetch_cx_quota(client), fetch_gm_quota(client)]
        if fetch_cc:
            coros.append(fetch_cc_quota(client))
        results = await asyncio.gather(*coros, return_exceptions=True)

    cx_raw = results[0] if not isinstance(results[0], Exception) else {}
    gm_raw = results[1] if not isinstance(results[1], Exception) else {}

    if fetch_cc:
        cc_raw = results[2] if not isinstance(results[2], Exception) else {}
        # Playwright fallback if API returned nothing
        if not cc_raw:
            cc_raw = await _fetch_cc_via_playwright()
        if cc_raw:
            _cc_raw_result = cc_raw
            _cc_raw_result_ts = now
            _persist_cc_quota(cc_raw, source=_cc_last_fetch_mode)

    cc_raw = _cc_raw_result

    _raw_cache = {"cc": cc_raw, "cx": cx_raw, "gm": gm_raw}
    result = format_quota(cc_raw, cx_raw, gm_raw)
    _cache = result
    _cache_ts = now
    return result


def get_quota_sync() -> dict:
    """Synchronous cache reader (returns last cached value, never blocks)."""
    return _cache


def get_raw_cache() -> dict:
    """Return raw API responses (for compat output)."""
    return _raw_cache


def reset_cc_backoff() -> None:
    """Reset CC backoff state (for manual retry)."""
    global _cc_backoff_until, _cc_consecutive_failures
    _cc_backoff_until = 0.0
    _cc_consecutive_failures = 0


def get_quota_health() -> dict:
    """Return fetch health metadata for quota collectors."""
    now = time.time()
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


def _parse_cc(data: dict) -> dict:
    """Parse Claude Code API response."""
    result: dict = {}
    if "five_hour" in data:
        result["5h"] = f"{round(data['five_hour'].get('utilization') or 0)}%"
    if "seven_day" in data:
        result["7d"] = f"{round(data['seven_day'].get('utilization') or 0)}%"
    if "extra_usage" in data:
        ex = data["extra_usage"]
        if ex.get("is_enabled"):
            used = (ex.get("used_credits") or 0) / 100
            limit = (ex.get("monthly_limit") or 0) / 100
            pct = round(ex.get("utilization") or 0)
            result["ex"] = f"${used:.2f}/${limit:.0f} {pct}%"
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
    if sw:
        result["7d"] = f"{sw.get('used_percent', 0)}%"
    return result


def _parse_gm(data: dict) -> dict:
    """Parse Gemini API response."""
    result: dict = {}
    for bucket in data.get("buckets", []):
        if bucket.get("tokenType") != "REQUESTS":
            continue
        model = bucket.get("modelId", "")
        frac = bucket.get("remainingFraction", 1.0)
        used_pct = round((1 - frac) * 100)
        if "pro" in model and not model.endswith("_vertex"):
            result["pro"] = f"{used_pct}%"
        if "flash" in model and "lite" not in model and not model.endswith("_vertex"):
            if "flash" not in result or used_pct > int(result["flash"].rstrip("%")):
                result["flash"] = f"{used_pct}%"
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
        "llm_display": " ".join(parts) if parts else "?",
        # Parsed percentages for API consumers
        "cc_parsed": cc,
        "cx_parsed": cx,
        "gm_parsed": gm,
    }
