"""CitedAnswerOp — synthesize answer with inline citations.

SynthSlot: question + reranked_chunks → answer + citations.
Uses LLM to generate a grounded answer with page/section references.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a document QA assistant. Answer the question "
    "based ONLY on the provided evidence chunks. "
    "For each claim, cite the source using "
    "[doc_id:chunk_index] format. "
    "If the evidence is insufficient, say so explicitly. "
    "Never fabricate information."
)

ANSWER_TEMPLATE = """Question: {question}

Evidence:
{evidence}

Answer the question with inline citations [doc_id:chunk_index]. Be concise and factual."""


class CitedAnswerOp:
    """SynthSlot: generate cited answer from reranked chunks."""

    @property
    def name(self) -> str:
        return "cited_answer"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("query", "reranked_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("answer", "citations", "answer_confidence")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        query: str = ctx["query"]
        chunks: list[dict] = ctx["reranked_chunks"]

        if not chunks:
            ctx["answer"] = "No relevant documents found to answer this question."
            ctx["citations"] = []
            ctx["answer_confidence"] = 0.0
            return ctx

        # Build evidence block
        evidence_lines = []
        citations = []
        for i, chunk in enumerate(chunks):
            meta = chunk.get("metadata", {})
            doc_id = meta.get("document_id", "unknown")
            chunk_idx = meta.get("chunk_index", i)
            section = meta.get("section_path", "")
            page = meta.get("page_range", "")

            evidence_lines.append(
                f"[{doc_id}:{chunk_idx}] (section: {section}, page: {page})\n{chunk['content']}"
            )
            citations.append(
                {
                    "document_id": doc_id,
                    "chunk_id": chunk.get("entity_id", ""),
                    "chunk_index": chunk_idx,
                    "section": section,
                    "page": page,
                    "quote": chunk["content"][:200],
                    "score": chunk.get("rerank_score", chunk.get("score", 0.0)),
                }
            )

        evidence_text = "\n\n".join(evidence_lines)
        prompt = ANSWER_TEMPLATE.format(question=query, evidence=evidence_text)

        # LLM call — uses litellm via shared infrastructure
        answer = await self._generate_answer(prompt)

        # Confidence heuristic: average rerank score of top chunks
        scores = [c.get("score", 0.0) for c in citations[:3]]
        confidence = sum(scores) / len(scores) if scores else 0.0

        ctx["answer"] = answer
        ctx["citations"] = citations
        ctx["answer_confidence"] = confidence
        logger.info(
            "CitedAnswer: %d citations, confidence=%.2f",
            len(citations),
            confidence,
        )
        return ctx

    async def _generate_answer(self, prompt: str) -> str:
        """Generate answer via LLM. Falls back to evidence summary on failure."""
        try:
            from src.shared.llm import acompletion

            response = await acompletion(
                model="haiku",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
                temperature=0.1,
            )
            return response.choices[0].message.content
        except Exception:
            logger.exception("LLM answer generation failed, returning evidence summary")
            return "Unable to generate answer. Please review the cited evidence directly."
