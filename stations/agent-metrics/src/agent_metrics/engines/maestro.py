"""Maestro engine — Intelligent multi-CLI orchestration dispatcher.

Analyzes tasks, selects orchestration patterns, and dispatches work
to Claude Code, Codex CLI, and Gemini CLI via headless wrappers.

Refactored from V1 orchestrator into asyncpg-backed station.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import asyncpg
import structlog
import yaml

from agent_metrics.config import settings

log = structlog.get_logger()

# ── Routing Table (loaded from YAML) ─────────────────────────────

_routing_cache: dict | None = None


def load_routing_table() -> dict:
    """Load CLI routing table from YAML config."""
    global _routing_cache
    if _routing_cache is not None:
        return _routing_cache

    path = Path(settings.ROUTING_TABLE_PATH)
    if path.exists():
        with open(path) as f:
            _routing_cache = yaml.safe_load(f)
    else:
        _routing_cache = {}
    return _routing_cache


def get_cli_routing() -> dict[str, dict[str, str]]:
    return load_routing_table().get("cli_routing", {})


def get_pipeline_templates() -> dict[str, list[dict[str, str]]]:
    return load_routing_table().get("pipeline_templates", {})


def get_category_keywords() -> dict[str, list[str]]:
    return load_routing_table().get("category_keywords", {})


CLI_NAME_ALIASES: dict[str, str] = {
    "claude": "claude",
    "claude code": "claude",
    "claude-code": "claude",
    "codex": "codex",
    "codex cli": "codex",
    "codex-cli": "codex",
    "openai codex": "codex",
    "openai": "codex",
    "gemini": "gemini",
    "gemini cli": "gemini",
    "gemini-cli": "gemini",
    "google gemini": "gemini",
}


# ── Data Classes ──────────────────────────────────────────────────


@dataclass
class TaskAnalysis:
    description: str
    complexity: str = "simple"
    decomposability: str = "atomic"
    categories: list[str] = field(default_factory=list)
    recommended_pattern: str = "solo"
    recommended_tier: str = "headless"
    phases: list[dict] = field(default_factory=list)


@dataclass
class AgentResult:
    task_id: str
    cli: str
    status: str
    duration_s: float
    output: str = ""


@dataclass
class MaestroRun:
    id: str
    name: str
    pattern: str
    task: str
    budget: str
    cwd: str
    tier: str = "headless"
    status: str = "running"
    phases: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    duration_s: float = 0


# ── Analysis ──────────────────────────────────────────────────────


def _is_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))


def _word_match(pattern: str, text: str) -> bool:
    if _is_cjk(pattern):
        return pattern in text
    return bool(re.search(r"\b" + re.escape(pattern) + r"\b", text, re.IGNORECASE))


def _effective_word_count(description: str) -> int:
    words = len(description.split())
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", description))
    if cjk_chars > 5:
        words += cjk_chars // 2
    return words


def detect_explicit_clis(description: str) -> list[str]:
    desc_lower = description.lower()
    found: dict[str, int] = {}
    for alias in sorted(CLI_NAME_ALIASES, key=len, reverse=True):
        pos = desc_lower.find(alias)
        if pos >= 0:
            canon = CLI_NAME_ALIASES[alias]
            if canon not in found:
                found[canon] = pos
    return [cli for cli, _ in sorted(found.items(), key=lambda x: x[1])]


def analyze_task(description: str, budget: str = "balanced") -> TaskAnalysis:
    desc_lower = description.lower()
    analysis = TaskAnalysis(description=description)
    keywords = get_category_keywords()

    scores: dict[str, int] = {}
    for cat, kw_list in keywords.items():
        score = sum(1 for kw in kw_list if _word_match(kw, desc_lower))
        if score > 0:
            scores[cat] = score
    analysis.categories = (
        sorted(scores, key=scores.get, reverse=True) if scores else ["code_generation"]
    )

    word_count = _effective_word_count(description)
    multi_signal_words = [
        "and", "then", "also", "plus", "with", "including",
        "並且", "然後", "還有", "以及", "同時",
    ]
    multi_signals = 0
    for w in multi_signal_words:
        if _is_cjk(w):
            multi_signals += desc_lower.count(w)
        else:
            multi_signals += len(
                re.findall(r"\b" + re.escape(w) + r"\b", desc_lower, re.IGNORECASE)
            )

    if word_count > 30 or multi_signals >= 2:
        analysis.complexity = "complex"
    elif word_count > 12 or multi_signals >= 1:
        analysis.complexity = "moderate"

    seq_signals = any(
        _word_match(p, desc_lower)
        for p in ["first", "then", "after that", "finally", "step 1", "phase"]
    ) or any(p in desc_lower for p in ["先", "然後", "接著", "最後"])
    par_signals = desc_lower.count(" and ") >= 2 or desc_lower.count("、") >= 2

    if seq_signals:
        analysis.decomposability = "sequential"
    elif par_signals and analysis.complexity != "simple":
        analysis.decomposability = "parallel"
    elif len(analysis.categories) >= 2 and analysis.complexity == "complex":
        analysis.decomposability = "parallel"

    analysis.recommended_pattern = select_pattern(analysis, budget)

    if analysis.recommended_pattern == "pipeline":
        primary_cat = analysis.categories[0]
        templates = get_pipeline_templates()
        analysis.phases = templates.get(primary_cat, templates.get("code_generation", []))

    return analysis


def select_pattern(analysis: TaskAnalysis, budget: str) -> str:
    if budget == "minimize":
        return "escalation"
    if analysis.decomposability == "sequential":
        return "pipeline"
    if analysis.decomposability == "parallel" and analysis.complexity in ("complex", "moderate"):
        return "swarm"
    if analysis.complexity == "simple":
        return "solo"
    return "solo"


def route_to_cli(category: str, budget: str = "balanced") -> str:
    tier_map = {"minimize": "budget", "balanced": "primary", "maximize_quality": "power"}
    tier = tier_map.get(budget, "primary")
    routing = get_cli_routing()
    cat_routing = routing.get(category, routing.get("code_generation", {}))
    return cat_routing.get(tier, "claude")


# ── Tier Routing (headless / relay / fleet) ──────────────────────


def get_tier_routing() -> dict:
    return load_routing_table().get("tier_routing", {})


def get_tier_keywords() -> dict[str, list[str]]:
    return load_routing_table().get("tier_keywords", {})


def select_tier(analysis: TaskAnalysis, tier_override: str | None = None) -> str:
    """Select execution tier based on task analysis or explicit override."""
    if tier_override and tier_override in ("headless", "relay", "fleet"):
        return tier_override

    tier_kw = get_tier_keywords()
    task_lower = analysis.description.lower()

    # Signal-based detection (highest priority)
    signals = get_tier_routing().get("signals", {})
    for signal, tier in signals.items():
        keywords = tier_kw.get(signal, [])
        if any(kw.lower() in task_lower for kw in keywords):
            return tier

    # Category-based default
    defaults = get_tier_routing().get("defaults", {})
    primary_cat = analysis.categories[0] if analysis.categories else "code_generation"
    return defaults.get(primary_cat, "headless")


def _tier_fallback_chain(tier: str) -> list[str]:
    """Return fallback tiers when preferred tier is unavailable."""
    fallback = get_tier_routing().get("fallback", {})
    return fallback.get(tier, [])


async def _check_tier_available(tier: str) -> bool:
    """Check if a tier backend is reachable."""
    if tier == "headless":
        return True
    if tier == "relay":
        try:
            from workshop.clients.tmux_relay import TmuxRelayClient
            relay = TmuxRelayClient()
            panes = relay.list_panes()
            return panes is not None
        except Exception:
            return False
    if tier == "fleet":
        try:
            from workshop.clients.fleet import FleetClient
            fleet = FleetClient()
            health = fleet.health()
            return health.get("status") == "healthy"
        except Exception:
            return False
    return False


async def resolve_tier(analysis: TaskAnalysis, tier_override: str | None = None) -> str:
    """Select tier with fallback if preferred tier is unavailable."""
    preferred = select_tier(analysis, tier_override)
    if await _check_tier_available(preferred):
        return preferred
    for fallback in _tier_fallback_chain(preferred):
        if await _check_tier_available(fallback):
            log.warning("tier_fallback", preferred=preferred, fallback=fallback)
            return fallback
    return "headless"


async def dispatch_relay(
    prompt: str, cwd: str | None, *, timeout: int = 300
) -> AgentResult:
    """Tier 2: Dispatch via tmux-relay pane pool (full MCP/skill access)."""
    from workshop.clients.tmux_relay import TmuxRelayClient

    task_id = f"relay-{int(time.time())}"
    start = time.time()
    try:
        relay = TmuxRelayClient()
        result = await asyncio.to_thread(relay.run, prompt, cwd=cwd, timeout=timeout)
        elapsed = round(time.time() - start, 1)
        return AgentResult(
            task_id=task_id,
            cli="claude",
            status="done" if result.status == "completed" else "failed",
            duration_s=elapsed,
            output=(result.output or "")[:5000],
        )
    except Exception as e:
        return AgentResult(
            task_id=task_id, cli="claude", status="failed",
            duration_s=round(time.time() - start, 1), output=f"Relay error: {e}",
        )


async def dispatch_fleet(
    prompt: str, *, mode: str = "code", node: str | None = None, timeout: int = 600
) -> AgentResult:
    """Tier 3: Dispatch via Fleet station (remote node execution)."""
    from workshop.clients.fleet import FleetClient

    task_id_local = f"fleet-{int(time.time())}"
    start = time.time()
    try:
        fleet = FleetClient()
        task = fleet.dispatch(prompt, mode=mode, node=node, timeout=timeout)
        fleet_task_id = task["id"]

        # Poll for completion (exponential backoff: 5s → 10s → 20s → cap 30s)
        interval = 5
        while time.time() - start < timeout:
            status = fleet.task_status(fleet_task_id)
            if status["status"] in ("completed", "failed", "timeout", "cancelled"):
                output = fleet.task_output(fleet_task_id).get("output", "")
                return AgentResult(
                    task_id=f"fleet-{fleet_task_id}",
                    cli="claude",
                    status="done" if status["status"] == "completed" else status["status"],
                    duration_s=round(time.time() - start, 1),
                    output=output[:5000],
                )
            await asyncio.sleep(interval)
            interval = min(interval * 2, 30)

        return AgentResult(
            task_id=task_id_local, cli="claude",
            status="timeout", duration_s=timeout, output="Fleet task timed out",
        )
    except Exception as e:
        return AgentResult(
            task_id=task_id_local, cli="claude", status="failed",
            duration_s=round(time.time() - start, 1), output=f"Fleet error: {e}",
        )


async def dispatch_by_tier(
    tier: str,
    cli: str,
    prompt: str,
    cwd: str | None,
    skills_dir: str,
    *,
    timeout: int = 300,
) -> AgentResult:
    """Unified dispatch router — select backend by tier."""
    if tier == "fleet":
        return await dispatch_fleet(prompt, timeout=timeout)
    elif tier == "relay":
        return await dispatch_relay(prompt, cwd, timeout=timeout)
    else:
        return await asyncio.to_thread(
            dispatch_agent, cli, prompt, cwd, skills_dir, timeout=timeout
        )


# ── Project Management ────────────────────────────────────────────


def generate_run_id() -> str:
    return str(uuid4())[:8]


def generate_run_name() -> str:
    return f"maestro-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


def _parse_dt(value: str) -> datetime | None:
    """Parse ISO datetime string to datetime object for asyncpg TIMESTAMPTZ."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def save_run(pool: asyncpg.Pool, run: MaestroRun) -> None:
    detail = json.dumps(
        {"phases": run.phases, "results": run.results},
        ensure_ascii=False,
    )
    started_at = _parse_dt(run.started_at) or datetime.now(UTC)
    completed_at = _parse_dt(run.completed_at)
    await pool.execute(
        """
        INSERT INTO dispatch_runs (id, name, pattern, budget, task_summary, cwd,
                                   status, started_at, completed_at, duration_s, detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (name) DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = EXCLUDED.completed_at,
            duration_s = EXCLUDED.duration_s,
            detail = EXCLUDED.detail
        """,
        run.id,
        run.name,
        run.pattern,
        run.budget,
        run.task,
        run.cwd,
        run.status,
        started_at,
        completed_at,
        run.duration_s or None,
        detail,
    )


async def load_run(pool: asyncpg.Pool, name: str) -> dict | None:
    row = await pool.fetchrow("SELECT * FROM dispatch_runs WHERE name = $1", name)
    if row is None:
        row = await pool.fetchrow(
            "SELECT * FROM dispatch_runs WHERE name LIKE $1 ORDER BY name DESC LIMIT 1",
            f"{name}%",
        )
    if row is None:
        return None
    result = dict(row)
    if result.get("detail"):
        result["detail"] = json.loads(result["detail"]) if isinstance(result["detail"], str) else result["detail"]
    return result


async def list_runs(pool: asyncpg.Pool, limit: int = 50) -> list[dict]:
    rows = await pool.fetch(
        "SELECT name, pattern, task_summary, status, started_at, duration_s "
        "FROM dispatch_runs ORDER BY started_at DESC LIMIT $1",
        limit,
    )
    return [dict(r) for r in rows]


# ── CLI Dispatch ──────────────────────────────────────────────────


def build_headless_paths(skills_dir: str) -> dict[str, str]:
    sd = Path(skills_dir)
    return {
        "claude": str(sd / "claude-code-headless" / "scripts" / "claude_headless.py"),
        "codex": str(sd / "codex-cli-headless" / "scripts" / "codex_headless.py"),
        "gemini": str(sd / "gemini-cli-headless" / "scripts" / "gemini_headless.py"),
    }


def dispatch_agent(
    cli: str,
    prompt: str,
    cwd: str | None,
    skills_dir: str,
    *,
    timeout: int = 300,
) -> AgentResult:
    headless = build_headless_paths(skills_dir)
    script = headless.get(cli)
    if not script:
        raise ValueError(f"Unknown CLI: {cli}")

    cmd = [sys.executable, script]
    if cli == "claude":
        cmd += ["-p", prompt, "--output-format", "json", "--allowedTools", "Read,Edit,Bash"]
        if cwd:
            cmd += ["--cwd", cwd]
    elif cli == "codex":
        cmd += ["--full-auto"]
        if cwd:
            cmd += ["--cd", cwd]
        cmd.append(prompt)
    elif cli == "gemini":
        cmd += ["-p", prompt, "--approval-mode", "yolo"]
        if cwd:
            cmd += ["--cwd", cwd]

    task_id = f"{cli}-{int(time.time())}"
    start = time.time()

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - start
        output = proc.stdout.strip()

        if cli == "claude" and output:
            try:
                clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
                json_start = clean.find("{")
                if json_start >= 0:
                    clean = clean[json_start:]
                data = json.loads(clean)
                output = data.get("result", output)
            except (json.JSONDecodeError, TypeError):
                pass

        return AgentResult(
            task_id=task_id,
            cli=cli,
            status="done" if proc.returncode == 0 else "failed",
            duration_s=round(elapsed, 1),
            output=output[:5000],
        )
    except subprocess.TimeoutExpired:
        return AgentResult(
            task_id=task_id, cli=cli, status="timeout",
            duration_s=timeout, output="Agent timed out",
        )
    except Exception as e:
        return AgentResult(
            task_id=task_id, cli=cli, status="failed",
            duration_s=round(time.time() - start, 1),
            output=f"Dispatch error: {e}",
        )


def quality_check(output: str) -> bool:
    if not output or len(output.strip()) < 50:
        return False
    error_signals = ["error:", "traceback", "exception", "failed", "could not"]
    lower = output.lower()
    return not any(sig in lower for sig in error_signals)


# ── Report ────────────────────────────────────────────────────────


def generate_report(run: MaestroRun) -> dict:
    done_count = sum(1 for r in run.results if r.get("status") == "done")
    return {
        "name": run.name,
        "pattern": run.pattern,
        "task": run.task,
        "budget": run.budget,
        "duration_s": run.duration_s,
        "agents_completed": done_count,
        "agents_total": len(run.results),
        "results": run.results,
    }


# ── Hook Notification ─────────────────────────────────────────────


async def notify_hook(event_type: str, data: dict) -> None:
    """Fire-and-forget notification to hook-observatory."""
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            await client.post(
                settings.HOOK_URL,
                json={"event_type": event_type, "data": data},
                timeout=2,
            )
    except Exception:
        pass  # fire-and-forget
