"""Maestro dispatch routes — multi-CLI orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from agent_metrics.config import settings
from agent_metrics.db import get_pool
from agent_metrics.engines import maestro as me
from agent_metrics.models import DispatchRequest, PlanRequest

router = APIRouter()


@router.post("/plan")
async def plan_task(body: PlanRequest) -> dict:
    """Analyze a task and return recommended orchestration pattern (no execution)."""
    analysis = me.analyze_task(body.task, body.budget.value)
    if body.pattern:
        analysis.recommended_pattern = body.pattern.value
        if body.pattern.value == "pipeline":
            primary_cat = analysis.categories[0]
            templates = me.get_pipeline_templates()
            analysis.phases = templates.get(
                primary_cat, templates.get("code_generation", [])
            )
    explicit_clis = me.detect_explicit_clis(body.task)
    result = asdict(analysis)
    if explicit_clis:
        result["explicit_clis"] = explicit_clis
    return result


@router.post("/run")
async def run_dispatch(body: DispatchRequest) -> dict:
    """Execute a dispatch — analyze, route, and run CLI agents."""
    pool = await get_pool()
    analysis = me.analyze_task(body.task, body.budget.value)
    if body.pattern:
        analysis.recommended_pattern = body.pattern.value

    run = me.MaestroRun(
        id=me.generate_run_id(),
        name=me.generate_run_name(),
        pattern=analysis.recommended_pattern,
        task=body.task,
        budget=body.budget.value,
        cwd=body.cwd or ".",
        phases=analysis.phases,
        started_at=datetime.now(UTC).isoformat(),
    )
    await me.save_run(pool, run)

    timeout = body.timeout or settings.DEFAULT_TIMEOUT
    cwd = body.cwd or None

    if analysis.recommended_pattern == "solo":
        cli = me.route_to_cli(analysis.categories[0], body.budget.value)
        result = await asyncio.to_thread(
            me.dispatch_agent, cli, body.task, cwd, settings.SKILLS_DIR, timeout=timeout
        )
        run.results = [asdict(result)]
    elif analysis.recommended_pattern == "pipeline":
        for phase in analysis.phases:
            prompt = f"[{phase['role']}] {body.task}"
            result = await asyncio.to_thread(
                me.dispatch_agent,
                phase["cli"],
                prompt,
                cwd,
                settings.SKILLS_DIR,
                timeout=timeout,
            )
            run.results.append(asdict(result))
            if result.status == "failed":
                break
    elif analysis.recommended_pattern == "race":
        clis = ["claude", "codex", "gemini"]
        tasks = [
            asyncio.to_thread(
                me.dispatch_agent, cli, body.task, cwd, settings.SKILLS_DIR, timeout=timeout
            )
            for cli in clis
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                run.results.append({"status": "failed", "output": str(r)})
            else:
                run.results.append(asdict(r))
    else:
        cli = me.route_to_cli(analysis.categories[0], body.budget.value)
        result = await asyncio.to_thread(
            me.dispatch_agent, cli, body.task, cwd, settings.SKILLS_DIR, timeout=timeout
        )
        run.results = [asdict(result)]

    run.completed_at = datetime.now(UTC).isoformat()
    started = datetime.fromisoformat(run.started_at)
    run.duration_s = round(
        (datetime.fromisoformat(run.completed_at) - started).total_seconds(), 1
    )
    run.status = "completed"
    await me.save_run(pool, run)

    # Fire-and-forget hook notification
    asyncio.create_task(
        me.notify_hook(
            "agent-metrics.dispatch.completed",
            {"name": run.name, "pattern": run.pattern, "duration_s": run.duration_s},
        )
    )

    return me.generate_report(run)


@router.get("/runs")
async def list_runs(limit: int = 50) -> list[dict]:
    """List dispatch run history."""
    pool = await get_pool()
    return await me.list_runs(pool, limit)


@router.get("/runs/{name}")
async def get_run(name: str) -> dict:
    """Get details of a specific dispatch run."""
    pool = await get_pool()
    run = await me.load_run(pool, name)
    if run is None:
        raise HTTPException(404, f"Run '{name}' not found")
    return run


@router.get("/routing-table")
async def routing_table() -> dict:
    """Return the current CLI routing configuration."""
    return {
        "routing": me.get_cli_routing(),
        "templates": me.get_pipeline_templates(),
    }
