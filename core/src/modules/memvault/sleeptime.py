"""Memvault Sleeptime Reflection Agent (Worker 4 — Phase 1).

Reactive background reflection — every N capture events triggers a lightweight
health-check + hot-snapshot update. Inspired by Letta's sleeptime model.

Flow:
    capture.entry.created  →  maybe_trigger_sleeptime(space_id, count)
                              ├─ if count % SLEEPTIME_INTERVAL != 0 → noop
                              └─ else asyncio.ensure_future(_run_sleeptime(...))
                                       ├─ lint health-check (best-effort)
                                       ├─ update_block(space_id, "project", ...)
                                       │  + ensure persona / human placeholder rows
                                       └─ emit memvault.sleeptime.completed event

Module boundaries:
    - reads capture event payload (space_id only)
    - writes only memvault schema (memory_block table)
    - never imports another module's models.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from src.events.types import CaptureEvents
from src.shared.database import async_session_factory

from .models import MemoryBlock, MemoryBlockSnapshot

logger = logging.getLogger(__name__)

# Trigger interval — every Nth capture event triggers sleeptime
# (Settings layer not yet wired into memvault; constant here is the source of truth
#  until pydantic-settings field is added in Phase 2.)
SLEEPTIME_INTERVAL: int = 5

BLOCK_TYPES: tuple[str, ...] = ("persona", "human", "project")
PROJECT_SUMMARY_RECENT_N: int = 5
PROJECT_SUMMARY_PER_BLOCK_CHARS: int = 30

# Worker 5: persona / human LLM generation throttle.
# Sleeptime fires every SLEEPTIME_INTERVAL captures (~5 events); LLM generation
# is much costlier than placeholder snapshot, so we cap to once per 24h per
# space. Backed by Redis with in-process fallback.
PERSONA_HUMAN_THROTTLE_SECONDS: int = 24 * 60 * 60
PERSONA_HUMAN_RECENT_N: int = 30  # blocks fed to LLM as context
PERSONA_TOKEN_BUDGET: int = 500
HUMAN_TOKEN_BUDGET: int = 500

_background_tasks: set[asyncio.Task] = set()
_inproc_persona_last_run: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def maybe_trigger_sleeptime(space_id: str, capture_count: int) -> bool:
    """Trigger sleeptime reflection iff capture_count aligns with interval.

    Returns True iff a background reflection task was scheduled.
    Fire-and-forget — caller does not await the reflection itself.
    """
    if not space_id:
        return False
    if capture_count <= 0:
        return False
    if capture_count % SLEEPTIME_INTERVAL != 0:
        return False

    task = asyncio.ensure_future(_run_sleeptime(space_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


# ---------------------------------------------------------------------------
# Reflection runner
# ---------------------------------------------------------------------------


async def _run_sleeptime(space_id: str) -> dict:
    """Run a single sleeptime reflection pass for one space.

    Steps:
      1. lint health-check (best-effort — fall back to legacy contradiction check
         until Worker 3 lands run_health_check).
      2. Update `project` hot-snapshot block from recent memory.
      3. Ensure `persona` / `human` placeholder rows exist (Worker 5 fills content).
      4. Emit memvault.sleeptime.completed event (best-effort).

    Resilient — never raises; logs and degrades.
    """
    findings: list = []
    blocks_updated: list[str] = []

    try:
        # 1. Health-check — best-effort. Worker 3 will land run_health_check; until
        #    then fall back to existing contradiction check. Both are optional.
        findings = await _safe_health_check(space_id)

        # 2 + 3. Update multi-block hot snapshot
        async with async_session_factory() as db:
            project_summary = await _summarize_recent(db, space_id)

            await _ensure_block(db, space_id, "project", project_summary)
            blocks_updated.append("project")

            # Worker 5: persona / human content via LLM, throttled to 24h.
            persona_human_updated = await _maybe_update_persona_human(db, space_id)
            blocks_updated.extend(persona_human_updated)
            # Always ensure rows exist (idempotent) so downstream readers don't
            # NPE — content stays whatever the last LLM run produced (or None
            # on first ever run if throttle blocks).
            await _ensure_block_if_missing(db, space_id, "persona")
            await _ensure_block_if_missing(db, space_id, "human")

            await db.commit()

        # 4. Emit event (best-effort)
        await _emit_sleeptime_completed(
            space_id=space_id,
            findings_count=len(findings),
            blocks_updated=blocks_updated,
        )

        logger.info(
            "memvault.sleeptime: space_id=%s findings=%d blocks_updated=%s",
            space_id,
            len(findings),
            blocks_updated,
        )
    except Exception:
        logger.warning("memvault.sleeptime failed: space_id=%s", space_id, exc_info=True)

    return {
        "space_id": space_id,
        "findings_count": len(findings),
        "blocks_updated": blocks_updated,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _safe_health_check(space_id: str) -> list:
    """Best-effort health-check.

    Worker 3 will provide `lint.run_health_check(space_id) -> list[Finding]`. Until
    then, fall back to existing `lint.check_contradictions(space_id)` if available.
    Any failure → return [] and continue.
    """
    try:
        from . import lint  # local import — avoid circular at module-load time
    except Exception:
        logger.debug("memvault.sleeptime: lint module unavailable")
        return []

    fn = getattr(lint, "run_health_check", None)
    if fn is None:
        fn = getattr(lint, "check_contradictions", None)
        # TODO(worker-3): switch to lint.run_health_check once it lands.
    if fn is None:
        return []

    try:
        result = fn(space_id)
        if asyncio.iscoroutine(result):
            result = await result
        return list(result or [])
    except Exception:
        logger.warning(
            "memvault.sleeptime: health-check failed for space_id=%s",
            space_id,
            exc_info=True,
        )
        return []


async def _summarize_recent(db, space_id: str) -> str:
    """Placeholder summary: concat first N chars of N most-recent blocks.

    Worker 5 will replace this with a proper LLM-driven summary.
    """
    # M2: sleeptime summary should reflect only currently-valid memory.
    from .bitemporal_filters import active_block_filters

    stmt = (
        select(MemoryBlock)
        .where(MemoryBlock.space_id == space_id, *active_block_filters())
        .order_by(MemoryBlock.created_at.desc())
        .limit(PROJECT_SUMMARY_RECENT_N)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return ""

    # Defensive Python-side cap — SQL `.limit(N)` already constrains this,
    # but we keep an explicit slice so the contract holds even if the upstream
    # query is mutated to drop the limit (and to make the unit test deterministic
    # against fake sessions that don't honor SQL LIMIT).
    rows = rows[:PROJECT_SUMMARY_RECENT_N]

    parts: list[str] = []
    for row in rows:
        text_ = (row.content or "").strip().replace("\n", " ")
        if not text_:
            continue
        parts.append(text_[:PROJECT_SUMMARY_PER_BLOCK_CHARS])
    return " | ".join(parts)


async def _ensure_block(
    db,
    space_id: str,
    block_type: str,
    content: str | None,
) -> MemoryBlockSnapshot:
    """Upsert a (space_id, block_type) snapshot row. Bumps version on content change."""
    stmt = (
        select(MemoryBlockSnapshot)
        .where(MemoryBlockSnapshot.space_id == space_id)
        .where(MemoryBlockSnapshot.block_type == block_type)
        .where(MemoryBlockSnapshot.deleted_at.is_(None))
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    word_count = len((content or "").split()) if content else 0

    if existing is None:
        # `id` defaults to uuid7().hex via TimestampMixin
        block = MemoryBlockSnapshot(
            space_id=space_id,
            block_type=block_type,
            content=content,
            word_count=word_count,
            block_version=1,
        )
        db.add(block)
        return block

    if (existing.content or "") != (content or ""):
        existing.content = content
        existing.word_count = word_count
        existing.block_version = (existing.block_version or 1) + 1
        existing.updated_at = datetime.now(UTC)
    return existing


async def _ensure_block_if_missing(db, space_id: str, block_type: str) -> None:
    """Ensure a placeholder row exists; do NOT touch existing content."""
    stmt = (
        select(MemoryBlockSnapshot)
        .where(MemoryBlockSnapshot.space_id == space_id)
        .where(MemoryBlockSnapshot.block_type == block_type)
        .where(MemoryBlockSnapshot.deleted_at.is_(None))
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        db.add(
            MemoryBlockSnapshot(
                space_id=space_id,
                block_type=block_type,
                content=None,
                word_count=0,
                block_version=1,
            )
        )


# ---------------------------------------------------------------------------
# Worker 5: persona / human LLM content generation (24h throttled)
# ---------------------------------------------------------------------------


async def _maybe_update_persona_human(db, space_id: str) -> list[str]:
    """Generate persona + human blocks via LLM if 24h throttle elapsed.

    Returns the list of block types updated (empty when throttled or LLM
    unavailable). Best-effort — failures degrade silently and the throttle
    is still bumped to avoid hot-loop retries against a broken LLM.
    """
    if not await _persona_throttle_should_run(space_id):
        return []

    try:
        from .bitemporal_filters import active_block_filters

        stmt = (
            select(MemoryBlock)
            .where(MemoryBlock.space_id == space_id, *active_block_filters())
            .order_by(MemoryBlock.created_at.desc())
            .limit(PERSONA_HUMAN_RECENT_N)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            await _persona_throttle_bump(space_id)
            return []
        snippets = [
            (r.content or "").strip().replace("\n", " ")[:300]
            for r in rows
            if (r.content or "").strip()
        ]
        if not snippets:
            await _persona_throttle_bump(space_id)
            return []
        joined = "\n- ".join(snippets[:PERSONA_HUMAN_RECENT_N])

        persona_text, human_text = await _llm_persona_human(joined)

        updated: list[str] = []
        if persona_text:
            await _ensure_block(db, space_id, "persona", persona_text)
            updated.append("persona")
        if human_text:
            await _ensure_block(db, space_id, "human", human_text)
            updated.append("human")
        await _persona_throttle_bump(space_id)
        return updated
    except Exception:
        logger.warning(
            "memvault.sleeptime.persona_human failed: space_id=%s",
            space_id,
            exc_info=True,
        )
        # Bump throttle even on failure — avoids hammering a broken LLM.
        await _persona_throttle_bump(space_id)
        return []


async def _persona_throttle_should_run(space_id: str) -> bool:
    """Return True iff PERSONA_HUMAN_THROTTLE_SECONDS has elapsed since last run."""
    import time as _time

    key = f"memvault:sleeptime:persona:last_run:{space_id}"
    try:
        from src.shared.cache import get_redis  # type: ignore

        redis_client = get_redis()
        if redis_client is not None:
            raw = await redis_client.get(key)
            if raw is None:
                return True
            try:
                last = float(raw)
            except (TypeError, ValueError):
                last = 0.0
            return (_time.time() - last) >= PERSONA_HUMAN_THROTTLE_SECONDS
    except Exception:
        logger.debug("persona throttle: redis unavailable, in-proc fallback", exc_info=True)

    last = _inproc_persona_last_run.get(space_id, 0.0)
    return (_time.time() - last) >= PERSONA_HUMAN_THROTTLE_SECONDS


async def _persona_throttle_bump(space_id: str) -> None:
    import time as _time

    now = _time.time()
    key = f"memvault:sleeptime:persona:last_run:{space_id}"
    try:
        from src.shared.cache import get_redis  # type: ignore

        redis_client = get_redis()
        if redis_client is not None:
            # 2x TTL so we keep history briefly for debugging without leaking forever.
            await redis_client.set(key, str(now), ex=PERSONA_HUMAN_THROTTLE_SECONDS * 2)
            return
    except Exception:
        logger.debug("persona throttle bump: redis unavailable", exc_info=True)
    _inproc_persona_last_run[space_id] = now


async def _llm_persona_human(joined_snippets: str) -> tuple[str | None, str | None]:
    """Call LLM twice (persona + human) in parallel. Returns (persona, human).

    Returns (None, None) on any failure — the caller treats this as "skip
    update this round, throttle bump still occurs".
    """
    try:
        from pydantic_ai import Agent

        from .llm_config import get_litellm_model
    except Exception:
        return (None, None)

    persona_prompt = (
        "你是少爺記憶系統的內省層。請根據以下最近的記憶片段，"
        "用第一人稱寫一段不超過 500 tokens 的 persona 摘要：「我是誰、"
        "我關心什麼、我目前的工作焦點」。聚焦穩定面向，不要列瑣碎事項。\n\n"
        f"最近記憶：\n- {joined_snippets}"
    )
    human_prompt = (
        "你是少爺記憶系統的對外觀察層。請根據以下最近的記憶片段，"
        "從「對話對象視角」寫一段不超過 500 tokens 的 human 摘要："
        "「對方似乎是個怎樣的人、有什麼特徵、需要注意什麼」。"
        "聚焦行為模式與互動風格，不要重述事件。\n\n"
        f"最近記憶：\n- {joined_snippets}"
    )

    try:
        model = await get_litellm_model()
    except Exception:
        return (None, None)

    async def _one(prompt: str) -> str | None:
        try:
            agent = Agent(model=model, system_prompt="繁體中文輸出。簡潔。")
            result = await agent.run(prompt)
            text = (getattr(result, "output", None) or getattr(result, "data", "")) or ""
            return text.strip() or None
        except Exception:
            logger.debug("persona/human LLM call failed", exc_info=True)
            return None

    persona, human = await asyncio.gather(_one(persona_prompt), _one(human_prompt))
    return (persona, human)


async def _emit_sleeptime_completed(
    *,
    space_id: str,
    findings_count: int,
    blocks_updated: list[str],
) -> None:
    """Publish memvault.sleeptime.completed (best-effort, never raises)."""
    try:
        from src.events.bus import event_bus

        payload = {
            "space_id": space_id,
            "findings_count": findings_count,
            "blocks_updated": list(blocks_updated),
        }
        publish = getattr(event_bus, "publish", None)
        if publish is None:
            return

        result = publish("memvault.sleeptime.completed", payload)
        if asyncio.iscoroutine(result):
            # Fire-and-forget — never block sleeptime on event delivery.
            # Keep a reference so the task is not GC'd mid-flight.
            task = asyncio.ensure_future(result)
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
    except Exception:
        logger.debug("memvault.sleeptime: emit completed event failed", exc_info=True)


# ---------------------------------------------------------------------------
# Capture event subscription
# ---------------------------------------------------------------------------


async def _on_capture_entry_created(event) -> None:
    """Subscriber wired to `capture.created` (CaptureEvents.CREATED).

    Increments a per-space Redis counter and triggers sleeptime when aligned.
    Falls back to in-process counter if Redis is unavailable.

    Payload shape (from capture.services._create): includes `space_id`,
    `capture_id`, `module`, `entity_type`, `raw_input`, `completeness`.
    """
    data = getattr(event, "data", None) or {}
    space_id = data.get("space_id") or getattr(event, "space_id", None)
    if not space_id:
        return

    count = await _incr_capture_count(space_id)
    await maybe_trigger_sleeptime(space_id, count)


# In-process fallback counter (per-process; resets on restart)
_inproc_counts: dict[str, int] = {}


async def _incr_capture_count(space_id: str) -> int:
    """Increment per-space capture counter. Redis primary, in-proc fallback."""
    key = f"memvault:capture_count:{space_id}"
    try:
        from src.shared.cache import get_redis  # type: ignore

        redis_client = get_redis()
        if redis_client is not None:
            value = await redis_client.incr(key)
            return int(value)
    except Exception:
        logger.debug("memvault.sleeptime: redis counter unavailable", exc_info=True)

    _inproc_counts[space_id] = _inproc_counts.get(space_id, 0) + 1
    return _inproc_counts[space_id]


def _wire_capture_subscription() -> None:
    """Subscribe to CaptureEvents.CREATED ("capture.created") if event_bus is available.

    Idempotent — safe to call multiple times during module import (events.py).
    Best-effort — never raises (test envs may stub event_bus).
    """
    try:
        from src.events.bus import event_bus

        channel_fn = getattr(event_bus, "channel", None)
        if channel_fn is not None:
            ch = channel_fn(CaptureEvents.CREATED)
            sub = getattr(ch, "subscribe_handler", None) or getattr(ch, "subscribe", None)
            if sub is not None:
                sub(_on_capture_entry_created)
                return

        # Fallback shapes
        sub_fn = getattr(event_bus, "subscribe", None)
        if sub_fn is not None:
            sub_fn(CaptureEvents.CREATED, _on_capture_entry_created)
    except Exception:
        logger.debug("memvault.sleeptime: capture subscription wiring skipped", exc_info=True)


__all__ = [
    "BLOCK_TYPES",
    "SLEEPTIME_INTERVAL",
    "_ensure_block",
    "_on_capture_entry_created",
    "_run_sleeptime",
    "_summarize_recent",
    "_wire_capture_subscription",
    "maybe_trigger_sleeptime",
]
