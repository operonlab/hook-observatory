"""Quota Gate Authority — centralized job execution authorization.

Jobs consult this authority before executing LLM-dependent tasks.
The gate checks current quota levels and determines if the job is
allowed to run based on a degradation policy.

Degradation Levels:
  L0: Normal    — all jobs run
  L1: Conserve  — defer expensive, non-critical jobs
  L2: Minimal   — only essential extraction pipeline
  L3: Shutdown  — all external LLM jobs paused, only local (oMLX) runs
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Policy: job → max degradation level it can tolerate
# ---------------------------------------------------------------------------

POLICY_PATH = Path(__file__).parent.parent.parent / "quota_gate_policy.json"

# Default policy (used if policy file not found)
_DEFAULT_POLICY: dict[str, dict] = {
    "daily-briefing": {"max_level": 0, "providers": ["gm", "cc"], "desc": "每日情報簡報"},
    "ws-sysmon-weekly": {"max_level": 0, "providers": ["gm"], "desc": "系統監控週報"},
    "ws-sysmon-monthly": {"max_level": 0, "providers": ["gm"], "desc": "系統監控月報"},
    "ws-memvault-synthesis": {"max_level": 1, "providers": ["gm"], "desc": "知識圖譜合成"},
    "ws-memvault-extract": {"max_level": 2, "providers": ["gm"], "desc": "記憶萃取"},
    "ws-intelligence-digest": {"max_level": 1, "providers": ["gm", "cc"], "desc": "情報週報"},
    # Always allowed (local LLM or no LLM)
    "ws-session-archive": {"max_level": 3, "providers": [], "desc": "Session 歸檔 (本地 oMLX)"},
    "ws-skill-lifecycle": {"max_level": 3, "providers": [], "desc": "Skill 生命週期 (無 LLM)"},
}

# Policy cache (hot-reload from file)
_policy_cache: dict[str, dict] = {}
_policy_cache_ts: float = 0.0
_POLICY_RELOAD_INTERVAL = 60.0  # re-read file every 60s


def _load_policy() -> dict[str, dict]:
    """Load policy from JSON file, fallback to defaults."""
    global _policy_cache, _policy_cache_ts

    now = time.time()
    if _policy_cache and (now - _policy_cache_ts) < _POLICY_RELOAD_INTERVAL:
        return _policy_cache

    if POLICY_PATH.exists():
        try:
            data = json.loads(POLICY_PATH.read_text())
            _policy_cache = data.get("jobs", _DEFAULT_POLICY)
            _policy_cache_ts = now
            return _policy_cache
        except (json.JSONDecodeError, KeyError):
            log.warning("quota_gate_policy_parse_error", path=str(POLICY_PATH))

    _policy_cache = _DEFAULT_POLICY
    _policy_cache_ts = now
    return _policy_cache


# ---------------------------------------------------------------------------
# Level computation
# ---------------------------------------------------------------------------

# Thresholds: (level, cc_5h_threshold, gm_pro_threshold)
# Check highest level first — first match wins
LEVEL_THRESHOLDS = [
    (3, 95.0, 95.0),
    (2, 80.0, 85.0),
    (1, 60.0, 70.0),
]


def compute_level(cc_5h: float, gm_pro: float) -> tuple[int, str]:
    """Compute current degradation level from quota percentages."""
    for level, cc_thresh, gm_thresh in LEVEL_THRESHOLDS:
        if cc_5h >= cc_thresh or gm_pro >= gm_thresh:
            return level, f"L{level}: CC_5h={cc_5h:.0f}%≥{cc_thresh:.0f} or GM_Pro={gm_pro:.0f}%≥{gm_thresh:.0f}"
    return 0, f"L0: Normal (CC_5h={cc_5h:.0f}%, GM_Pro={gm_pro:.0f}%)"


def _parse_pct(s: str) -> float:
    """Parse '42%' → 42.0, '?' → 0.0."""
    try:
        return float(str(s).rstrip("%"))
    except (ValueError, AttributeError):
        return 0.0


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


async def evaluate(job_name: str) -> dict:
    """Evaluate whether a job is allowed to run given current quota levels."""
    from agent_metrics.quota_collector import get_quota

    policy = _load_policy()
    job_policy = policy.get(job_name)

    quota = await get_quota()
    cc_5h = _parse_pct(quota.get("llm_cc_5h", "?"))
    gm_pro = _parse_pct(quota.get("llm_gm_pro", "?"))
    level, reason = compute_level(cc_5h, gm_pro)

    if not job_policy:
        # Unknown job — default allow (fail-open for unregistered jobs)
        log.info("quota_gate_unknown_job", job=job_name, level=level)
        return {
            "allowed": True,
            "level": level,
            "max_level": None,
            "reason": f"Unknown job (not in policy) — default allow. {reason}",
            "job": job_name,
            "quotas": {"cc_5h": cc_5h, "gm_pro": gm_pro},
        }

    allowed = level <= job_policy["max_level"]

    log.info(
        "quota_gate_evaluated",
        job=job_name,
        allowed=allowed,
        level=level,
        max_level=job_policy["max_level"],
    )

    return {
        "allowed": allowed,
        "level": level,
        "max_level": job_policy["max_level"],
        "reason": reason,
        "job": job_name,
        "desc": job_policy.get("desc", ""),
        "providers": job_policy.get("providers", []),
        "quotas": {"cc_5h": cc_5h, "gm_pro": gm_pro},
    }


async def evaluate_all() -> dict:
    """Evaluate all registered jobs — returns current level + per-job status."""
    from agent_metrics.quota_collector import get_quota

    policy = _load_policy()
    quota = await get_quota()
    cc_5h = _parse_pct(quota.get("llm_cc_5h", "?"))
    gm_pro = _parse_pct(quota.get("llm_gm_pro", "?"))
    level, reason = compute_level(cc_5h, gm_pro)

    jobs = {}
    for name, p in policy.items():
        allowed = level <= p["max_level"]
        jobs[name] = {
            "allowed": allowed,
            "max_level": p["max_level"],
            "desc": p.get("desc", ""),
            "providers": p.get("providers", []),
        }

    return {
        "level": level,
        "reason": reason,
        "quotas": {"cc_5h": cc_5h, "gm_pro": gm_pro},
        "jobs": jobs,
        "allowed_count": sum(1 for j in jobs.values() if j["allowed"]),
        "denied_count": sum(1 for j in jobs.values() if not j["allowed"]),
    }
