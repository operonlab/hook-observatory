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


class QAGenerationOp:
    """Generate QA pairs from chunks + entities at ingest time."""

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
