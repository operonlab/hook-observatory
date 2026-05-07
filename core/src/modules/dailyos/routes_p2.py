"""Daily OS P2 routes — Workflows, Pilot Method, Snippets, SmartLists, Rituals.

Prefix: /api/dailyos (mounted in main.py alongside router)
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission

from .schemas_p2 import (
    EveningRitualResponse,
    MorningRitualResponse,
    PilotDecisionRequest,
    PilotDecisionResponse,
    PilotRatchetResponse,
    PilotStateResponse,
    PilotStateUpdate,
    RitualStatusResponse,
    SmartListCreate,
    SmartListExecuteResponse,
    SmartListPresetItem,
    SmartListResponse,
    SmartListUpdate,
    SnippetActivateResponse,
    SnippetCreate,
    SnippetResponse,
    SnippetUpdate,
    WorkflowActivateResponse,
    WorkflowCreate,
    WorkflowRateRequest,
    WorkflowResponse,
    WorkflowUpdate,
)
from .services_p2 import (
    pilot_service,
    ritual_service,
    smart_list_service,
    snippet_service,
    workflow_service,
)

router_p2 = APIRouter(tags=["dailyos-p2"])


# ======================== P2a: Workflows ========================


@router_p2.get("/workflows", response_model=list[WorkflowResponse])
async def list_workflows(
    space_id: str = Query("default"),
    include_presets: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """List all workflows (presets + custom)."""
    return await workflow_service.list_workflows(db, space_id, include_presets=include_presets)


@router_p2.post("/workflows", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    data: WorkflowCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Create a custom workflow strategy bundle."""
    result = await workflow_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.put("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    data: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Update a custom workflow."""
    result = await workflow_service.update(db, workflow_id, data, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Soft delete a workflow."""
    await workflow_service.delete(db, workflow_id, user_id=user.get("id"))
    await db.commit()


@router_p2.post("/workflows/{workflow_id}/activate", response_model=WorkflowActivateResponse)
async def activate_workflow(
    workflow_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Activate a workflow — applies its method_ids, toggle_overrides, snippet_ids."""
    result = await workflow_service.activate(db, workflow_id, space_id, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.post("/workflows/{workflow_id}/rate", response_model=WorkflowResponse)
async def rate_workflow(
    workflow_id: str,
    data: WorkflowRateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Rate a workflow (1-5 stars)."""
    result = await workflow_service.rate(db, workflow_id, data.rating)
    await db.commit()
    return result


# ======================== P2b: Pilot Method ========================


@router_p2.get("/pilot/today", response_model=PilotStateResponse)
async def get_pilot_today(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get or create today's pilot state."""
    state = await pilot_service.get_or_create_today(db, space_id, user_id=user.get("id"))
    await db.commit()
    return pilot_service._to_response(state)


@router_p2.put("/pilot/today", response_model=PilotStateResponse)
async def update_pilot_today(
    data: PilotStateUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Update today's pilot state (flight_mode, fuel_spent, time_spent, etc.)."""
    state = await pilot_service.update_today(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return pilot_service._to_response(state)


@router_p2.post("/pilot/decision", response_model=PilotDecisionResponse)
async def record_pilot_decision(
    data: PilotDecisionRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Record a decision — increments decision count, updates fatigue score."""
    result = await pilot_service.record_decision(
        db,
        space_id,
        description=data.description,
        fuel_cost=data.fuel_cost,
        user_id=user.get("id"),
    )
    await db.commit()
    return result


@router_p2.get("/pilot/history", response_model=list[PilotStateResponse])
async def get_pilot_history(
    space_id: str = Query("default"),
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get pilot state history for a date range."""
    return await pilot_service.get_history(db, space_id, date_from, date_to)


@router_p2.get("/pilot/ratchet-level", response_model=PilotRatchetResponse)
async def get_pilot_ratchet_level(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Calculate current verify_level based on cognitive fuel ratio."""
    return await pilot_service.calculate_ratchet(db, space_id)


# ======================== P2c: Snippets ========================


@router_p2.get("/snippets", response_model=list[SnippetResponse])
async def list_snippets(
    space_id: str = Query("default"),
    include_presets: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """List all snippets."""
    return await snippet_service.list_snippets(db, space_id, include_presets=include_presets)


@router_p2.post("/snippets", response_model=SnippetResponse, status_code=201)
async def create_snippet(
    data: SnippetCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Create a custom snippet."""
    result = await snippet_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.put("/snippets/{snippet_id}", response_model=SnippetResponse)
async def update_snippet(
    snippet_id: str,
    data: SnippetUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Update a custom snippet."""
    result = await snippet_service.update(db, snippet_id, data, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.delete("/snippets/{snippet_id}", status_code=204)
async def delete_snippet(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Soft delete a snippet."""
    await snippet_service.delete(db, snippet_id, user_id=user.get("id"))
    await db.commit()


@router_p2.post("/snippets/{snippet_id}/activate", response_model=SnippetActivateResponse)
async def activate_snippet(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Activate a snippet — apply its toggle_keys and config_patch."""
    result = await snippet_service.activate(db, snippet_id, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.post("/snippets/{snippet_id}/deactivate", response_model=SnippetResponse)
async def deactivate_snippet(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Deactivate a snippet."""
    result = await snippet_service.deactivate(db, snippet_id, user_id=user.get("id"))
    await db.commit()
    return result


# ======================== P2d: Smart Lists ========================


@router_p2.get("/smart-lists/presets", response_model=list[SmartListPresetItem])
async def list_smart_list_presets(
    user: dict = require_permission("dailyos.read"),
):
    """List preset smart lists (Eisenhower quadrants, next-actions, etc.)."""
    return smart_list_service.get_presets()


@router_p2.get("/smart-lists", response_model=list[SmartListResponse])
async def list_smart_lists(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """List all user-defined smart lists."""
    return await smart_list_service.list_smart_lists(db, space_id)


@router_p2.post("/smart-lists", response_model=SmartListResponse, status_code=201)
async def create_smart_list(
    data: SmartListCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Create a custom smart list with RPN filter expression."""
    result = await smart_list_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.put("/smart-lists/{smart_list_id}", response_model=SmartListResponse)
async def update_smart_list(
    smart_list_id: str,
    data: SmartListUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Update a smart list."""
    result = await smart_list_service.update(db, smart_list_id, data, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.delete("/smart-lists/{smart_list_id}", status_code=204)
async def delete_smart_list(
    smart_list_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Soft delete a smart list."""
    await smart_list_service.delete(db, smart_list_id, user_id=user.get("id"))
    await db.commit()


@router_p2.post("/smart-lists/{smart_list_id}/execute", response_model=SmartListExecuteResponse)
async def execute_smart_list(
    smart_list_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Run the smart list filter and return matching backlog items."""
    return await smart_list_service.execute(db, smart_list_id, space_id)


# ======================== P2e: Guided Daily Ritual ========================


@router_p2.post("/ritual/morning", response_model=MorningRitualResponse)
async def execute_morning_ritual(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Execute morning ritual steps — returns checklist + suggestions."""
    result = await ritual_service.morning_ritual(db, space_id, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.post("/ritual/evening", response_model=EveningRitualResponse)
async def execute_evening_ritual(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Execute evening ritual steps — returns review data + carry-forward suggestions."""
    result = await ritual_service.evening_ritual(db, space_id, user_id=user.get("id"))
    await db.commit()
    return result


@router_p2.get("/ritual/status", response_model=RitualStatusResponse)
async def get_ritual_status(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get today's ritual completion status."""
    return await ritual_service.get_ritual_status(db, space_id)


@router_p2.post("/ritual/morning/complete", response_model=RitualStatusResponse)
async def complete_morning_ritual(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Mark today's morning ritual as completed (write side of the ritual state).

    Closes the read/write asymmetry from the audit: get_ritual_status had no
    counterpart that actually wrote completion, so the status would never
    advance even when the user finished the ritual.
    """
    result = await ritual_service.complete_morning_ritual(
        db, space_id, user_id=user.get("id")
    )
    await db.commit()
    return result


@router_p2.post("/ritual/evening/complete", response_model=RitualStatusResponse)
async def complete_evening_ritual(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Mark today's evening ritual as completed."""
    result = await ritual_service.complete_evening_ritual(
        db, space_id, user_id=user.get("id")
    )
    await db.commit()
    return result
