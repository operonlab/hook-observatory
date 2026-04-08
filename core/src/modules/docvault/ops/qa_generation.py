"""QAGenerationOp — Generate QA pairs from document chunks at ingest time.

Toggle: DOCVAULT_QA_GENERATION=1 (off by default).
Runs as best-effort post-ingest step.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic_ai import Agent

from ..llm_config import get_model
from ..llm_models import QAGenerationResult

logger = logging.getLogger(__name__)

QA_GENERATION_ENABLED = os.environ.get("DOCVAULT_QA_GENERATION", "0") == "1"

_QA_GEN_PROMPT = """\
You are a QA pair generator for a document knowledge base. Given document chunks, \
generate diverse question-answer pairs that test understanding of the content.

Rules:
- Generate questions that can be answered SOLELY from the provided chunks.
- Include the chunk indices that support each answer in source_chunk_indices.
- Mix question types: factual (direct fact), definitional (what is X), \
comparative (compare X and Y), procedural (how to do X).
- Answers must be concise and factual — cite specific numbers, names, and details.
- Do NOT generate questions about information not present in the chunks.
- Generate questions in the SAME LANGUAGE as the document content.
"""

_gen_agent: Agent[None, QAGenerationResult] | None = None


def _get_agent() -> Agent[None, QAGenerationResult]:
    global _gen_agent
    if _gen_agent is None:
        _gen_agent = Agent(
            "openai:placeholder",
            output_type=QAGenerationResult,
            system_prompt=_QA_GEN_PROMPT,
            retries=2,
        )
    return _gen_agent


def _decide_qa_count(chunk_count: int) -> int:
    """Adaptive QA count based on document size."""
    if chunk_count < 10:
        return 10
    if chunk_count < 30:
        return 20
    return 40


async def _get_existing_qa(db: Any, document_id: str) -> list:
    """Fetch existing pre-generated QA for a document (for incremental update)."""
    try:
        from sqlalchemy import select

        from ..models import PreGeneratedQA

        result = await db.execute(
            select(PreGeneratedQA).where(
                PreGeneratedQA.document_id == document_id,
                PreGeneratedQA.status.in_(["pending", "validated"]),
                PreGeneratedQA.deleted_at == None,  # noqa: E711
            )
        )
        return list(result.scalars().all())
    except Exception:
        return []


async def _deprecate_stale_qa(db: Any, document_id: str, old_version_id: str) -> int:
    """Mark QA pairs from old version as deprecated. Returns count."""
    try:
        from sqlalchemy import update

        from ..models import PreGeneratedQA

        result = await db.execute(
            update(PreGeneratedQA)
            .where(
                PreGeneratedQA.document_id == document_id,
                PreGeneratedQA.version_id == old_version_id,
                PreGeneratedQA.status.in_(["pending", "validated"]),
            )
            .values(status="deprecated")
        )
        return result.rowcount
    except Exception:
        return 0


async def _cleanup_deprecated_from_qdrant(document_id: str) -> None:
    """Remove deprecated QA entries from Qdrant cache."""
    try:
        from qdrant_client.http.models import (
            FieldCondition,
            Filter,
            MatchValue,
        )

        from src.shared import qdrant_client as qclient
        from src.shared.qdrant_search import COLLECTION_NAME

        client = await qclient.get_client()
        if not client:
            return

        await client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="service_id",
                        match=MatchValue(value="docvault-qa-cache"),
                    ),
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    ),
                ]
            ),
        )
    except Exception:
        logger.debug("Qdrant cleanup for deprecated QA failed")


class QAGenerationOp:
    """Generate QA pairs from chunks + entities at ingest time.

    Incremental update strategy:
    - If document already has QA pairs from an older version:
      1. Deprecate old version's QA pairs in DB
      2. Remove old entries from Qdrant cache
      3. Generate fresh QA for the new version
    - If no existing QA: full generation from scratch
    """

    name = "QAGenerationOp"
    input_keys = ("chunks", "document_id", "version_id", "space_id", "db")
    output_keys = ("generated_qa_pairs", "qa_generation_count")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not QA_GENERATION_ENABLED:
            ctx["generated_qa_pairs"] = []
            ctx["qa_generation_count"] = 0
            return ctx

        chunks = ctx.get("chunks", [])
        document_id = ctx["document_id"]
        version_id = ctx["version_id"]
        db = ctx["db"]

        # ── Incremental update: handle existing QA from prior versions ──
        existing_qa = await _get_existing_qa(db, document_id)
        if existing_qa:
            old_versions = {q.version_id for q in existing_qa if q.version_id != version_id}
            if old_versions:
                for old_ver in old_versions:
                    deprecated = await _deprecate_stale_qa(db, document_id, old_ver)
                    logger.info(
                        "Deprecated %d stale QA pairs (version %s)",
                        deprecated,
                        old_ver[:12],
                    )
                await _cleanup_deprecated_from_qdrant(document_id)

            # If current version already has QA, skip regeneration
            current_qa = [q for q in existing_qa if q.version_id == version_id]
            if current_qa:
                logger.info(
                    "Document %s already has %d QA pairs for current version",
                    document_id[:12],
                    len(current_qa),
                )
                ctx["generated_qa_pairs"] = []
                ctx["qa_generation_count"] = 0
                return ctx

        # ── Fresh generation for new version ──
        target_count = _decide_qa_count(len(chunks))
        agent = _get_agent()
        model = await get_model()

        all_pairs = []

        # Process chunks in groups of 5-8
        group_size = 6
        for i in range(0, len(chunks), group_size):
            group = chunks[i : i + group_size]
            chunk_text = "\n\n".join(
                f"[Chunk {i + j}] {c.get('content', c) if isinstance(c, dict) else str(c)}"
                for j, c in enumerate(group)
            )

            pairs_needed = min(
                target_count - len(all_pairs),
                max(2, target_count // max(1, len(chunks) // group_size)),
            )
            if pairs_needed <= 0:
                break

            try:
                result = await agent.run(
                    f"Generate {pairs_needed} QA pairs from these chunks:\n\n{chunk_text}",
                    model=model,
                )
                all_pairs.extend(result.output.pairs)
            except Exception:
                logger.warning("QA generation failed for chunk group %d", i)
                continue

        # Persist to DB
        from ..models import PreGeneratedQA

        for pair in all_pairs[:target_count]:
            qa_record = PreGeneratedQA(
                space_id=ctx.get("space_id", "default"),
                document_id=document_id,
                version_id=version_id,
                question=pair.question,
                answer=pair.answer,
                question_type=pair.question_type,
                source_chunks={"indices": pair.source_chunk_indices},
                confidence=0.0,
                status="pending",
            )
            db.add(qa_record)

        ctx["generated_qa_pairs"] = all_pairs[:target_count]
        ctx["qa_generation_count"] = len(all_pairs[:target_count])
        logger.info(
            "Generated %d QA pairs for document %s",
            ctx["qa_generation_count"],
            document_id[:12],
        )
        return ctx
