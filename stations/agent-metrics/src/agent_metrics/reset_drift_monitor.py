"""Reset drift monitor — detect sudden shifts in quota window reset_at.

Normal rolling window drift between samples is near-zero. If the stored
reset_at for a CLI window moves by more than DRIFT_THRESHOLD_HOURS between
consecutive samples, fire DRIFT_BARK_COUNT Bark notifications so the user
can decide whether to enable boost-3 + team agents to burn the fresh window.

Redis keys:
  agent-metrics:drift:last:{cli}:{window}      — last observed resets_at (ISO)
  agent-metrics:drift:cooldown:{cli}:{window}  — cooldown guard (TTL)
"""

from __future__ import annotations

import threading
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Iterable

import redis
import structlog

from agent_metrics.config import settings

log = structlog.get_logger()

_r: redis.Redis | None = None


def _get_redis() -> redis.Redis | None:
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


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_local(dt: datetime) -> str:
    return dt.astimezone().strftime("%m-%d %H:%M %Z")


def _send_bark_once(title: str, body: str, *, group: str, level: str, url: str) -> bool:
    """Synchronous Bark HTTP GET. Returns True on HTTP 200."""
    base = settings.BARK_SERVER_URL.rstrip("/")
    key = settings.BARK_DEVICE_KEY
    if not base or not key:
        return False
    bark_url = f"{base}/{key}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
    params = {"group": group, "level": level}
    if url:
        params["url"] = url
    bark_url = f"{bark_url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(bark_url, timeout=5) as resp:  # noqa: S310
            return resp.status == 200
    except Exception:
        log.debug("bark_send_failed", exc_info=True)
        return False


def _send_bark_sequence(messages: Iterable[tuple[str, str]], *, group: str) -> None:
    """Send each (title, body) in order on a background thread."""
    msg_list = list(messages)

    def _run() -> None:
        for title, body in msg_list:
            _send_bark_once(
                title,
                body,
                group=group,
                level="timeSensitive",
                url=settings.DRIFT_STATION_URL,
            )

    threading.Thread(target=_run, daemon=True).start()


def _build_messages(
    cli_label: str,
    window_label: str,
    old_dt: datetime,
    new_dt: datetime,
    delta_hours: float,
    extra: dict,
) -> list[tuple[str, str]]:
    usage_5h = extra.get("5h") or "?"
    usage_7d = extra.get("7d") or "?"
    old_local = _format_local(old_dt)
    new_local = _format_local(new_dt)
    direction = "往後" if delta_hours >= 0 else "往前"
    abs_hours = abs(delta_hours)
    count = max(1, int(settings.DRIFT_BARK_COUNT))
    base: list[tuple[str, str]] = [
        (
            f"⚠️ {cli_label} {window_label} reset 漂移",
            f"reset 時間無預警變動 {direction} {abs_hours:.1f} 小時",
        ),
        (
            f"{cli_label} {window_label}：舊 → 新",
            f"{old_local} → {new_local}",
        ),
        (
            f"{cli_label} 當前使用率",
            f"5h {usage_5h} · 7d {usage_7d}",
        ),
        (
            "要啟用 boost-3 + team agent？",
            "趁新週期空窗期用滿；回覆少爺即可觸發",
        ),
        (
            "詳細資訊",
            "打開 agent-metrics 查看 reset 卡片",
        ),
    ]
    if len(base) >= count:
        return base[:count]
    # Pad if DRIFT_BARK_COUNT > 5
    extras = [
        (
            f"{cli_label} 漂移提醒 #{i + 6}",
            f"{window_label} reset 仍在 {new_local}",
        )
        for i in range(count - len(base))
    ]
    return base + extras


def check_and_notify(
    cli: str,
    cli_label: str,
    window: str,
    window_label: str,
    new_resets_at: str | None,
    *,
    extra: dict | None = None,
) -> dict:
    """Compare new resets_at against the last observed value for (cli, window).

    Returns a status dict (for telemetry). Non-raising; swallows errors.
    """
    result = {
        "cli": cli,
        "window": window,
        "new_resets_at": new_resets_at,
        "drift_detected": False,
        "delta_hours": None,
        "notified": False,
        "reason": "",
    }
    if not new_resets_at:
        result["reason"] = "no_new_resets_at"
        return result

    r = _get_redis()
    if r is None:
        result["reason"] = "no_redis"
        return result

    last_key = f"agent-metrics:drift:last:{cli}:{window}"
    cooldown_key = f"agent-metrics:drift:cooldown:{cli}:{window}"

    try:
        prev = r.get(last_key)
    except Exception:
        prev = None

    new_dt = _parse_iso(new_resets_at)
    prev_dt = _parse_iso(prev) if prev else None

    # Always refresh the last known value so next comparison uses latest baseline
    try:
        if new_dt is not None:
            r.set(last_key, new_resets_at)
    except Exception:
        pass

    if prev_dt is None or new_dt is None:
        result["reason"] = "no_prev_or_invalid"
        return result

    delta = (new_dt - prev_dt).total_seconds() / 3600.0
    result["delta_hours"] = round(delta, 2)
    threshold = float(settings.DRIFT_THRESHOLD_HOURS)
    if abs(delta) < threshold:
        result["reason"] = "within_threshold"
        return result

    result["drift_detected"] = True

    # Cooldown check
    try:
        if r.exists(cooldown_key):
            result["reason"] = "cooldown_active"
            return result
        r.setex(cooldown_key, int(settings.DRIFT_COOLDOWN_HOURS * 3600), "1")
    except Exception:
        pass

    messages = _build_messages(
        cli_label, window_label, prev_dt, new_dt, delta, extra or {}
    )
    _send_bark_sequence(messages, group=f"reset-drift-{cli}")
    result["notified"] = True
    result["reason"] = "notified"
    log.warning(
        "reset_drift_detected",
        cli=cli,
        window=window,
        prev=prev,
        new=new_resets_at,
        delta_hours=result["delta_hours"],
    )
    return result


# ---------------------------------------------------------------------------
# High-level entry — called from quota_sidecar after each successful fetch
# ---------------------------------------------------------------------------


def check_all_windows(parsed: dict) -> list[dict]:
    """Walk the formatted quota dict and run drift check on every weekly window.

    Weekly (7-day) windows are the primary target — 5h windows legitimately
    drift every few hours so alerting on them is noisy. Daily (Gemini) is
    treated like weekly for symmetry but uses a looser semantic label.
    """
    cc = parsed.get("cc_parsed", {}) or {}
    cx = parsed.get("cx_parsed", {}) or {}
    gm = parsed.get("gm_parsed", {}) or {}

    jobs: list[tuple[str, str, str, str, str | None, dict]] = [
        (
            "cc",
            "Claude Code",
            "7d",
            "7-day 週期",
            cc.get("7d_resets_at"),
            {"5h": cc.get("5h"), "7d": cc.get("7d")},
        ),
        (
            "cx",
            "Codex CLI",
            "7d",
            "7-day 週期",
            cx.get("7d_resets_at"),
            {"5h": cx.get("5h"), "7d": cx.get("7d")},
        ),
        (
            "gm",
            "Gemini CLI",
            "daily",
            "每日週期",
            gm.get("daily_resets_at"),
            {"5h": gm.get("pro") or "?", "7d": gm.get("flash") or "?"},
        ),
    ]
    results: list[dict] = []
    for cli, cli_label, window, window_label, resets_at, extra in jobs:
        results.append(
            check_and_notify(
                cli, cli_label, window, window_label, resets_at, extra=extra
            )
        )
    return results
