"""KG Auto-Evolution — Graphiti-style real-time triple extraction (P5).

When new MemoryBlocks are stored, automatically extract and upsert triples.
Subscribes to MemvaultEvents.MEMORY_STORED and runs triple extraction via
local LLM (oMLX), then feeds results into the existing TripleService pipeline.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import MemvaultEvents

from .kg_config import PREDICATE_VOCABULARY, VALID_PREDICATES, normalize_predicate
from .kg_schemas import TripleBatchCreate, TripleCreate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LLM_URL = "http://localhost:8000/v1/chat/completions"
_LLM_TIMEOUT = 8.0  # seconds — quick extraction, fall back on timeout
_MIN_CONTENT_LENGTH = 50
_SKIP_BLOCK_TYPES = {"general"}  # too noisy for auto-extraction

# Predicate hint text per block_type
_PREDICATE_HINTS: dict[str, str] = {
    "attitude": (
        "Focus on predicates that reveal user preferences and beliefs: "
        "should, should_NOT, chosen_over, reason_for, pattern_is."
    ),
    "skill": (
        "Focus on predicates that reveal capability and tooling: "
        "uses, requires, implemented_as, configured_with, enables."
    ),
    "knowledge": ("Use all available predicates as appropriate for the content."),
}
_DEFAULT_PREDICATE_HINT = "Use all available predicates as appropriate for the content."


def _build_predicate_list() -> str:
    """Build a human-readable predicate list for the LLM prompt."""
    lines = []
    for category, predicates in PREDICATE_VOCABULARY.items():
        lines.append(f"  [{category}]: {', '.join(predicates)}")
    return "\n".join(lines)


_PREDICATE_LIST_TEXT = _build_predicate_list()


# ---------------------------------------------------------------------------
# Triple extraction
# ---------------------------------------------------------------------------


async def extract_triples_from_content(
    content: str,
    block_type: str,
) -> list[dict[str, str]]:
    """Extract subject-predicate-object triples from memory content via oMLX.

    Uses the local LLM at port 8000 with a constrained predicate vocabulary.
    Returns a list of dicts: [{"subject": ..., "predicate": ..., "object": ..., "topic": ...}].
    Falls back to empty list on timeout or parse failure.

    Args:
        content: Raw text content of the memory block.
        block_type: Type hint — "attitude", "skill", "knowledge", or other.

    Returns:
        List of extracted triple dicts (may be empty on failure).
    """
    predicate_hint = _PREDICATE_HINTS.get(block_type, _DEFAULT_PREDICATE_HINT)

    system_prompt = (
        "You are a knowledge graph triple extractor. "
        "Extract factual subject-predicate-object triples from the given text. "
        "ONLY use predicates from the approved vocabulary below — do not invent new ones.\n\n"
        f"APPROVED PREDICATES:\n{_PREDICATE_LIST_TEXT}\n\n"
        f"EXTRACTION GUIDANCE: {predicate_hint}\n\n"
        "Return ONLY a JSON array. Each element must have exactly these keys: "
        '"subject", "predicate", "object", "topic". '
        "topic should be a short phrase (≤5 words) categorising the triple. "
        "Extract 1-5 high-quality triples. Do not hallucinate — only extract facts clearly "
        "stated or strongly implied by the text."
    )

    user_prompt = f"TEXT:\n{content}\n\nExtract triples as JSON array:"

    payload = {
        "model": "default",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }

    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            response = await client.post(_LLM_URL, json=payload)
            response.raise_for_status()

        result = response.json()
        raw_text: str = result["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        triples_raw: list[dict[str, Any]] = json.loads(raw_text)

        # Validate and filter
        valid_triples: list[dict[str, str]] = []
        for t in triples_raw:
            if not isinstance(t, dict):
                continue
            subj = str(t.get("subject", "")).strip()
            pred = str(t.get("predicate", "")).strip()
            obj = str(t.get("object", "")).strip()
            topic = str(t.get("topic", "")).strip() or None

            if not (subj and pred and obj):
                continue

            # Normalize predicate and reject if not in vocabulary
            canonical = normalize_predicate(pred)
            if canonical not in VALID_PREDICATES:
                logger.debug("Skipping unknown predicate %r (normalized: %r)", pred, canonical)
                continue

            valid_triples.append(
                {
                    "subject": subj,
                    "predicate": canonical,
                    "object": obj,
                    "topic": topic,
                }
            )

        logger.debug(
            "extract_triples_from_content: %d valid / %d raw (block_type=%s)",
            len(valid_triples),
            len(triples_raw),
            block_type,
        )
        return valid_triples

    except httpx.TimeoutException:
        logger.warning(
            "Triple extraction timed out after %.1fs (block_type=%s)", _LLM_TIMEOUT, block_type
        )
        return []
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Triple extraction parse error: %s", exc)
        return []
    except Exception:
        logger.warning("Triple extraction failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# KG evolution orchestration
# ---------------------------------------------------------------------------


async def auto_evolve_kg(
    memory_id: str,
    content: str,
    block_type: str,
    space_id: str,
    source_session: str | None,
    db: AsyncSession,
) -> dict[str, int]:
    """Extract triples from a new MemoryBlock and feed them into TripleService.

    Calls extract_triples_from_content, then feeds valid triples through the
    existing batch_ingest pipeline (entity resolution + contradiction detection).
    Best-effort: exceptions are logged, not raised.

    Args:
        memory_id: ID of the newly stored MemoryBlock (for logging).
        content: Text content of the MemoryBlock.
        block_type: Block type tag influencing predicate bias.
        space_id: Space the memory belongs to.
        source_session: Optional session ID to tag triples with.
        db: Active async database session.

    Returns:
        Stats dict: {"triples_extracted": N, "triples_stored": M, "contradictions_resolved": K}
    """
    # Lazy import to avoid circular dependencies at module load time
    from .kg_services import TripleService

    stats = {"triples_extracted": 0, "triples_stored": 0, "contradictions_resolved": 0}

    try:
        raw_triples = await extract_triples_from_content(content, block_type)
        stats["triples_extracted"] = len(raw_triples)

        if not raw_triples:
            return stats

        session_id = source_session or f"auto_evolve:{memory_id}"

        batch = TripleBatchCreate(
            session_id=session_id,
            topic=block_type,
            triples=[
                TripleCreate(
                    subject=t["subject"],
                    predicate=t["predicate"],
                    object=t["object"],
                    topic=t.get("topic"),
                )
                for t in raw_triples
            ],
        )

        service = TripleService()
        created = await service.batch_ingest(db=db, space_id=space_id, batch=batch)
        await db.commit()

        stats["triples_stored"] = len(created)
        # contradictions_resolved is implicit in batch_ingest (invalidated_count not exposed);
        # we report 0 here — the invalidation events are still fired by batch_ingest internally.

        logger.info(
            "KG auto-evolve: memory=%s block_type=%s extracted=%d stored=%d",
            memory_id,
            block_type,
            stats["triples_extracted"],
            stats["triples_stored"],
        )

    except Exception:
        logger.warning(
            "KG auto-evolve failed for memory=%s (best-effort, continuing)",
            memory_id,
            exc_info=True,
        )

    return stats


# ---------------------------------------------------------------------------
# Event handler registration
# ---------------------------------------------------------------------------


def register_auto_evolve_handler() -> None:
    """Subscribe to MEMORY_STORED events to trigger automatic KG evolution.

    Call this once during app startup (e.g., in the lifespan function or
    module __init__ after DB and event bus are ready).
    The handler is fire-and-forget — it never blocks the publishing coroutine.
    """

    async def _on_memory_stored(event: Event) -> None:
        data = event.data
        block_type: str = data.get("block_type", "general")
        content: str = data.get("content", "")
        memory_id: str = data.get("block_id") or data.get("id", "unknown")
        space_id: str = data.get("space_id", "")
        source_session: str | None = data.get("source_session")

        # Guard: skip noisy block types and very short content
        if block_type in _SKIP_BLOCK_TYPES:
            logger.debug(
                "KG auto-evolve: skipping block_type=%s (memory=%s)", block_type, memory_id
            )
            return
        if len(content) < _MIN_CONTENT_LENGTH:
            logger.debug(
                "KG auto-evolve: skipping short content len=%d (memory=%s)", len(content), memory_id
            )
            return
        if not space_id:
            logger.warning("KG auto-evolve: missing space_id in MEMORY_STORED event, skipping")
            return

        # Obtain a fresh DB session for this background task
        try:
            from src.shared.database import async_session_factory

            async with async_session_factory() as db:
                await auto_evolve_kg(
                    memory_id=memory_id,
                    content=content,
                    block_type=block_type,
                    space_id=space_id,
                    source_session=source_session,
                    db=db,
                )
        except Exception:
            logger.warning("KG auto-evolve session error (memory=%s)", memory_id, exc_info=True)

    def _handler(event: Event) -> None:
        """Sync wrapper that schedules the async handler as fire-and-forget."""
        asyncio.ensure_future(_on_memory_stored(event))  # noqa: RUF006

    event_bus.subscribe(MemvaultEvents.MEMORY_STORED, _handler)
    logger.info("KG auto-evolve handler registered for %s", MemvaultEvents.MEMORY_STORED)
