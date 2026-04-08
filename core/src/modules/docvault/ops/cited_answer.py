"""CitedAnswerOp — generate answer with inline citations via LLM.

Default SynthSlot implementation for factual QA.
Produces an answer where every claim cites a source chunk.

Operator protocol:
  input_keys: ("question", "evidence_chunks")
  output_keys: ("answer", "citations", "confidence")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic_ai import Agent

from ..llm_config import get_model
from ..llm_models import SynthResult, VerifyResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a document QA assistant. Answer ONLY from evidence chunks. Cite with [N]. \
Answer in the same language as the question.

EXAMPLES of correct behavior:

Example 1 — Term NOT in document (reject premise):
Q: "What are the three types of X?"
Evidence mentions "use case categories" but never "three types of X."
→ {"answer": "The document does not use the term 'three types of X.' It instead \
organizes by 'use case categories' [1].", "citations_used": [1], \
"terminology_match": false, "confidence": 0.1}

Example 2 — Term in document, with analogy:
Q: "Difference between A and B?"
Evidence: "Think of it like a restaurant. A means... B means..."
→ {"answer": "The guide uses a restaurant analogy: [quote] [2]. \
A means [definition]. B means [definition] [2].", "citations_used": [2], \
"terminology_match": true, "confidence": 0.9}

Example 3 — Term in document, answer via concrete example:
Q: "What are the steps in pattern X?"
Evidence: "Pattern X. Example — Task Y: Step 1 do A. Step 2 do B. Key techniques: ..."
→ {"answer": "The guide illustrates Pattern X with a 'Task Y' example [3]: \
Step 1 do A, Step 2 do B. Key techniques: ... [3]", "citations_used": [3], \
"terminology_match": true, "confidence": 0.9}

Output format (strict JSON, no markdown fences):
{"answer": "...", "citations_used": [1, 2], "terminology_match": true, "confidence": 0.85}
"""


_VERIFY_PROMPT = """\
You will receive a Question and numbered evidence chunks. \
Do TWO things:

1. MISSED CONTENT: Scan ALL evidence chunks for important facts, examples, \
good/bad comparisons, or practical advice that directly answer the question \
but might be overlooked. Quote them verbatim with chunk number. \
Only include content RELEVANT to the question. Max 3 items.

2. ANALOGIES: Find analogies or metaphors RELEVANT to the question's topic. \
Only extract what ALREADY EXISTS in evidence. If none relevant, empty list.

Output (strict JSON, no markdown fences):
{
  "missed": [{"text": "verbatim quote of missed content", "chunk": 5}],
  "analogies": [{"text": "verbatim analogy text", "chunk": 2}]
}

If nothing missed and no analogies: {"missed": [], "analogies": []}
"""


_synth_agent = Agent(
    output_type=SynthResult,
    system_prompt=_SYSTEM_PROMPT,
    retries=2,
)

_verify_agent = Agent(
    output_type=VerifyResult,
    system_prompt=_VERIFY_PROMPT,
    retries=2,
)


def _build_user_message(question: str, chunks: list[dict[str, Any]]) -> str:
    parts = [f"Question: {question}\n\nEvidence chunks:\n"]
    for i, chunk in enumerate(chunks, 1):
        section = chunk.get("section_path", "")
        page = chunk.get("page_range", "")
        meta_parts = []
        if section:
            meta_parts.append(f"section={section}")
        if page:
            meta_parts.append(f"page={page}")
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
        content = chunk.get("content", "")[:3000]
        parts.append(f"[{i}]{meta}:\n{content}\n")
    return "\n".join(parts)


async def _llm_synthesize(
    question: str, chunks: list[dict[str, Any]]
) -> tuple[str, list[int], float]:
    """Two-pass parallel synthesis via PydanticAI agents.

    Pass 1 (verify/analogy extraction) and Pass 2 (cited answer) run concurrently.
    If Pass 1 finds analogies, they are woven into the final answer.
    """
    user_msg = _build_user_message(question, chunks)
    model = await get_model()

    # ── Parallel: verify+analogy extraction + factual synthesis ──
    async def _verify_and_extract() -> VerifyResult:
        try:
            result = await _verify_agent.run(
                user_msg,
                model=model,
                model_settings={"temperature": 0.1},
            )
            return result.output
        except Exception:
            logger.debug("Verify pass failed, skipping")
            return VerifyResult()

    async def _synthesize() -> SynthResult:
        result = await _synth_agent.run(
            user_msg,
            model=model,
            model_settings={"temperature": 0.2},
        )
        return result.output

    verify_result, synth_result = await asyncio.gather(
        _verify_and_extract(), _synthesize()
    )

    answer = synth_result.answer or ""
    citations_used = list(synth_result.citations_used)
    confidence = max(0.0, min(1.0, synth_result.confidence))

    # Hard cap: if LLM reports terminology mismatch, enforce confidence ≤ 0.2
    if not synth_result.terminology_match:
        confidence = min(confidence, 0.2)

    # If answer is empty, return refusal
    if not answer.strip():
        refusal_msg = synth_result.reason or "文件中未找到足夠相關的內容來回答此問題。"
        return refusal_msg, [], 0.0

    # ── Dedup helper ──
    def _dedup_items(
        items: list[Any],
    ) -> list[Any]:
        seen: set[str] = set()
        unique: list[Any] = []
        for item in items:
            key = item.text[:60]
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    # ── Merge missed content (append to answer) ──
    missed = _dedup_items(verify_result.missed)
    novel_missed = [m for m in missed if m.text[:40] not in answer]
    if novel_missed:
        supplement_lines = []
        for m in novel_missed[:3]:
            chunk_ref = f"[{m.chunk}]" if m.chunk else ""
            supplement_lines.append(f"- {m.text} {chunk_ref}")
            if m.chunk and m.chunk not in citations_used:
                citations_used.append(m.chunk)
        answer = f"{answer}\n\nAdditional relevant details from the document:\n" + "\n".join(
            supplement_lines
        )

    # ── Merge analogies (prepend to answer) ──
    analogies = _dedup_items(verify_result.analogies)
    novel_analogies = [a for a in analogies if a.text[:40] not in answer]
    if novel_analogies:
        analogy_lines = []
        for a in novel_analogies[:2]:
            chunk_ref = f"[{a.chunk}]" if a.chunk else ""
            analogy_lines.append(f"{a.text} {chunk_ref}")
            if a.chunk and a.chunk not in citations_used:
                citations_used.append(a.chunk)
        answer = " ".join(analogy_lines) + "\n\n" + answer

    return answer, citations_used, confidence


def _build_fallback_answer(
    question: str, chunks: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], float]:
    """Fallback: concatenate chunks when LLM is unavailable."""
    if not chunks:
        return "No evidence found to answer this question.", [], 0.0

    parts = [f"Based on {len(chunks)} relevant document sections:"]
    citations: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks[:6], 1):
        section = chunk.get("section_path", "Unknown section")
        page = chunk.get("page_range", "")
        page_info = f" (p.{page})" if page else ""
        excerpt = chunk.get("content", "")[:200].strip()
        parts.append(f"\n[{i}] ({section}{page_info}): {excerpt}...")
        citations.append(
            {
                "index": i,
                "document_id": chunk.get("document_id", ""),
                "chunk_id": chunk.get("id", ""),
                "section": section,
                "page": page,
                "quote": chunk.get("content", "")[:200],
            }
        )

    parts.append("\n(LLM synthesis unavailable — showing raw evidence)")
    base_confidence = min(1.0, 0.3 + 0.05 * len(chunks))
    return "\n".join(parts), citations, base_confidence


class CitedAnswerOp:
    """Default synthesis: generate answer with inline citations via LLM.

    Operator protocol:
      input_keys: ("question", "evidence_chunks")
      output_keys: ("answer", "citations", "confidence")
    """

    @property
    def name(self) -> str:
        return "cited_answer"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("question", "evidence_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("answer", "citations", "confidence")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        question: str = ctx.get("question", "")
        chunks: list[dict[str, Any]] = ctx.get("evidence_chunks", [])

        try:
            answer, citations_used, confidence = await _llm_synthesize(question, chunks)

            # Build structured citations from the indices the LLM referenced
            citations: list[dict[str, Any]] = []
            for idx in citations_used:
                if 1 <= idx <= len(chunks):
                    chunk = chunks[idx - 1]
                    citations.append(
                        {
                            "index": idx,
                            "document_id": chunk.get("document_id", ""),
                            "chunk_id": chunk.get("id", ""),
                            "section": chunk.get("section_path", ""),
                            "page": chunk.get("page_range", ""),
                            "quote": chunk.get("content", "")[:200],
                        }
                    )

            logger.info(
                "CitedAnswerOp: LLM synthesis OK — %d chunks → %d citations, confidence=%.2f",
                len(chunks),
                len(citations),
                confidence,
            )

        except Exception:
            logger.warning("CitedAnswerOp: LLM call failed, using fallback", exc_info=True)
            answer, citations, confidence = _build_fallback_answer(question, chunks)

        ctx["answer"] = answer
        ctx["citations"] = citations
        ctx["confidence"] = confidence
        return ctx
