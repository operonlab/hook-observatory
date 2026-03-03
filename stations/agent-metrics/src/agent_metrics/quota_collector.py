"""LLM Quota Collector — Claude Code, Codex, Gemini (full Python port).

Replaces quota-all.sh with async Python. All three providers are fetched
in parallel with 60s TTL cache. Results are merged into sysmon snapshots
and written to /tmp for tmux consumption.
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
# Internal cache (60s TTL)
# ---------------------------------------------------------------------------
_cache: dict = {}
_cache_ts: float = 0.0

# Raw API response cache (for compat output)
_raw_cache: dict = {}

# Gemini project ID cache (1h TTL)
_gm_project: str = ""
_gm_project_ts: float = 0.0
_GM_PROJECT_TTL = 3600.0


# ---------------------------------------------------------------------------
# Claude Code — Anthropic OAuth usage API
# ---------------------------------------------------------------------------

async def fetch_cc_quota(client: httpx.AsyncClient) -> dict:
    """Fetch Claude Code quota from Anthropic OAuth API via macOS Keychain."""
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5,
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
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.debug("quota_cc_fetch_failed", exc_info=True)
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

        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.GM_CLIENT_ID,
            "client_secret": settings.GM_CLIENT_SECRET,
        }).encode()
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
    """Fetch all LLM quotas with 60s cache. Returns formatted dict."""
    global _cache, _cache_ts, _raw_cache

    now = time.time()
    if not force and _cache and (now - _cache_ts) < settings.QUOTA_CACHE_TTL:
        return _cache

    async with httpx.AsyncClient() as client:
        cc_raw, cx_raw, gm_raw = await asyncio.gather(
            fetch_cc_quota(client),
            fetch_cx_quota(client),
            fetch_gm_quota(client),
            return_exceptions=True,
        )

    # Treat exceptions as empty
    if isinstance(cc_raw, Exception):
        cc_raw = {}
    if isinstance(cx_raw, Exception):
        cx_raw = {}
    if isinstance(gm_raw, Exception):
        gm_raw = {}

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


# ---------------------------------------------------------------------------
# Format quota for tmux / API
# ---------------------------------------------------------------------------

def _parse_cc(data: dict) -> dict:
    """Parse Claude Code API response."""
    result: dict = {}
    if "five_hour" in data:
        result["5h"] = f"{round(data['five_hour'].get('utilization', 0))}%"
    if "seven_day" in data:
        result["7d"] = f"{round(data['seven_day'].get('utilization', 0))}%"
    if "extra_usage" in data:
        ex = data["extra_usage"]
        if ex.get("is_enabled"):
            used = ex.get("used_credits", 0) / 100
            limit = ex.get("monthly_limit", 0) / 100
            pct = round(ex.get("utilization", 0))
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
