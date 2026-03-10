"""Daily OS event handlers."""

import structlog

from src.events.bus import Event, event_bus
from src.events.types import DailyosEvents
from src.shared.database import async_session_factory

logger = structlog.get_logger()


@event_bus.on(DailyosEvents.PLAN_COMPLETED)
async def on_plan_completed(event: Event) -> None:
    """Handle plan completion — extract behavioral patterns to Memvault.

    Idempotent: skips if a block for this plan already exists in Memvault.
    Writes an 'attitude' block summarising daily completion behaviour.
    """
    # Lazy import to avoid circular dependencies at module load time
    from src.modules.memvault.schemas import MemoryBlockCreate
    from src.modules.memvault.services import memory_block_service

    data = event.data
    plan_id = data.get("plan_id")
    space_id = data.get("space_id", "default")

    if not plan_id:
        logger.warning("dailyos.plan.completed event missing plan_id")
        return

    source_session = f"dailyos:plan:{plan_id}"

    async with async_session_factory() as db:
        try:
            # Idempotent guard: skip if already extracted for this plan
            existing = await memory_block_service.find_by_source_session(
                db, space_id=space_id, source_session=source_session
            )
            if existing:
                logger.debug(
                    "dailyos_plan_already_extracted",
                    plan_id=plan_id,
                    block_id=existing.id,
                )
                return

            content = _synthesize_behavioral_summary(data)
            if not content:
                logger.debug("dailyos_plan_no_behavioral_data", plan_id=plan_id)
                return

            block_data = MemoryBlockCreate(
                content=content,
                block_type="attitude",
                tags=["dailyos", "behavioral-pattern", "auto-extracted"],
                source_session=source_session,
            )

            await memory_block_service.create(db, space_id, block_data)
            await db.commit()
            logger.info("dailyos_behavioral_pattern_extracted", plan_id=plan_id)

        except Exception:
            await db.rollback()
            logger.exception("dailyos_plan_extraction_failed", plan_id=plan_id)


def _synthesize_behavioral_summary(data: dict) -> str | None:
    """Synthesize natural language behavioral summary from plan completion data."""
    plan_date = data.get("plan_date", "unknown")
    total = data.get("total_items", 0)
    completed = data.get("completed_count", 0)
    carry = data.get("carry_count", 0)
    score = data.get("completion_score", 0)
    frog_completed = data.get("frog_completed", False)
    frog_title = data.get("frog_title")
    reflection = data.get("reflection")

    if total == 0:
        return None

    parts = []
    parts.append(f"[{plan_date}] 日計畫完成度 {score:.0%}（{completed}/{total} 項完成")  # noqa: RUF001
    if carry > 0:
        parts[-1] += f"，{carry} 項遞延"  # noqa: RUF001
    parts[-1] += "）"  # noqa: RUF001

    if frog_title:
        status = "已完成" if frog_completed else "未完成"
        parts.append(f"青蛙任務「{frog_title}」{status}")

    if reflection:
        parts.append(f"反思：{reflection}")  # noqa: RUF001

    return "。".join(parts) + "。"
