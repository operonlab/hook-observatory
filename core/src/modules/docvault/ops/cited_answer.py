"""CitedAnswerOp — generate answer with inline citations via LLM.

Default SynthSlot implementation for factual QA.
Produces an answer where every claim cites a source chunk.
Three-tier groundedness verification prevents hallucination.

Operator protocol:
  input_keys: ("question", "evidence_chunks")
  output_keys: ("answer", "citations", "confidence")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic_ai import Agent

from ..llm_config import cache_settings, get_model
from ..llm_models import SynthResult, VerifyResult
from .groundedness import self_consistency_check, validate_spans, verify_claims

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a document QA assistant. Answer ONLY from evidence chunks. Cite with [N]. \
Answer in the same language as the question.

CRITICAL RULES:
1. Even when the exact term from the question is NOT in the document, \
you MUST still provide the closest relevant content. Correct the premise, then answer \
with what the document DOES say.
2. NEVER invent specific numbers, measurements, or limits that do not appear \
verbatim in the evidence chunks. If the evidence says "up to 1024 characters", \
do NOT rephrase as "5000 words" or any other number.
3. When quoting a specific fact (number, limit, name), use the EXACT wording from \
the evidence chunk.
4. SOURCE-ROLE PRIORITY. Each evidence chunk may carry a source_role label. \
When chunks disagree, prefer the higher-authority role: \
invariant > open-decision > decision-rationale > reference > fallback > raw-note. \
A `fallback` chunk describes a "what if PoC fails" plan, NOT the current decision. \
If your answer's main claim relies on a `fallback` chunk while `invariant` or \
`open-decision` chunks contradict it, you MUST: (a) lead with the invariant/decision \
content, (b) describe the fallback content as a contingency, and (c) cap your \
self-rated confidence at 0.5.

EXAMPLES of correct behavior:

Example 1 — Term NOT in document (correct premise + provide related content):
Q: "What are the three types of X?"
Evidence mentions "use case categories" and "two design approaches" but never "three types of X."
→ {"answer": "The document does not use the term 'three types of X.' \
However, it describes two design approaches: Approach A, where [explanation] [1], \
and Approach B, where [explanation] [2]. It also organizes by 'use case categories' [1].", \
"citations_used": [1, 2], "terminology_match": false, "confidence": 0.4}

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

Example 4 — Nothing relevant at all (true refusal):
Q: "What is the recommended database for production?"
Evidence discusses UI components but nothing about databases.
→ {"answer": null, "citations_used": [], "terminology_match": false, \
"confidence": 0.0, "reason": "Evidence contains no information about databases."}

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


def _build_user_message(
    question: str,
    chunks: list[dict[str, Any]],
    conversation_history: list[dict] | None = None,
) -> str:
    # Cache-friendly prefix order: stable parts first, volatile question last.
    # [history] → [evidence chunks] → [question]
    # Same chunks across self-consistency / verify pass / multi-turn QA on the
    # same document hit the same prefix-cache prefix.
    parts = []
    if conversation_history:
        parts.append("Conversation context (for reference only, do NOT cite these):\n")
        for h in conversation_history:
            parts.append(
                f"[Turn {h.get('turn', '?')}] User: {h.get('question', '')} "
                f"Assistant: {h.get('answer', '')[:200]}\n"
            )
        parts.append("\n")
    parts.append("Evidence chunks:\n")
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
    parts.append(f"\nQuestion: {question}")
    return "\n".join(parts)


async def _llm_synthesize(
    question: str,
    chunks: list[dict[str, Any]],
    conversation_history: list[dict] | None = None,
) -> tuple[str, list[int], float]:
    """Three-pass parallel synthesis with groundedness verification.

    Pass 1 (verify/analogy extraction) and Pass 2 (cited answer) run concurrently.
    Then Tier 1-3 groundedness checks validate the answer.
    """
    user_msg = _build_user_message(question, chunks, conversation_history)
    model = await get_model()
    synth_settings = cache_settings(chunks, temperature=0.2)
    verify_settings = cache_settings(chunks, temperature=0.1)

    # ── Phase A: Parallel synthesis + verify ──
    async def _verify_and_extract() -> VerifyResult:
        try:
            result = await _verify_agent.run(
                user_msg,
                model=model,
                model_settings=verify_settings,
            )
            return result.output
        except Exception:
            logger.debug("Verify pass failed, skipping")
            return VerifyResult()

    async def _synthesize() -> SynthResult:
        result = await _synth_agent.run(
            user_msg,
            model=model,
            model_settings=synth_settings,
        )
        return result.output

    verify_result, synth_result = await asyncio.gather(
        _verify_and_extract(), _synthesize()
    )

    # ── Phase B: Tier 3 — Self-consistency (if enabled) ──
    synth_result = await self_consistency_check(
        _synth_agent, user_msg, chunks, synth_result
    )

    answer = synth_result.answer or ""
    citations_used = list(synth_result.citations_used)
    confidence = max(0.0, min(1.0, synth_result.confidence))

    # Soft cap: terminology mismatch → confidence ≤ 0.5
    if not synth_result.terminology_match:
        confidence = min(confidence, 0.5)

    # If answer is empty, return refusal
    if not answer.strip():
        refusal_msg = synth_result.reason or "文件中未找到足夠相關的內容來回答此問題。"
        return refusal_msg, [], 0.0

    # ── Dedup helper ──
    def _dedup_items(items: list[Any]) -> list[Any]:
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

    # ── Phase C: Tier 1 — Span validation (numbers check) ──
    flagged_spans = validate_spans(answer, chunks)
    if flagged_spans:
        logger.warning(
            "Groundedness T1: %d unsupported numbers in answer: %s",
            len(flagged_spans),
            flagged_spans,
        )
        # Penalize confidence for each unsupported number
        penalty = min(0.15 * len(flagged_spans), 0.5)
        confidence = max(0.0, confidence - penalty)

    # ── Phase D: Tier 2 — NLI claim verification ──
    groundedness = await verify_claims(answer, chunks)
    if groundedness.flagged_claims:
        logger.warning(
            "Groundedness T2: %d unsupported claims: %s",
            len(groundedness.flagged_claims),
            groundedness.flagged_claims[:3],
        )
        # Add warning to answer
        flags = "; ".join(groundedness.flagged_claims[:3])
        answer += f"\n\n[!] 以下內容未被文件直接支持, 請人工驗證: {flags}"
        # Penalize confidence
        penalty = min(0.1 * len(groundedness.flagged_claims), 0.4)
        confidence = max(0.0, confidence - penalty)

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
                "source_role": chunk.get("source_role"),
                "doc_weight": chunk.get("doc_weight"),
            }
        )

    parts.append("\n(LLM synthesis unavailable — showing raw evidence)")
    base_confidence = min(1.0, 0.3 + 0.05 * len(chunks))
    return "\n".join(parts), citations, base_confidence


class CitedAnswerOp:
    """Default synthesis: generate answer with inline citations via LLM.

    Three-tier groundedness verification:
      Tier 1: Span validation — numbers/measurements must exist in chunks
      Tier 2: NLI claim verification — LLM-based entailment check
      Tier 3: Self-consistency — majority vote (DOCVAULT_SELF_CONSISTENCY=1)

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
            conversation_history = ctx.get("conversation_history")
            answer, citations_used, confidence = await _llm_synthesize(
                question, chunks, conversation_history
            )

            # Build structured citations from the indices the LLM referenced
            citations: list[dict[str, Any]] = []
            cited_chunks = [
                chunks[i - 1] for i in citations_used if 1 <= i <= len(chunks)
            ]
            # P2.3: fallback-as-primary detection. If the LLM's first
            # citation is a fallback chunk AND any authoritative role was
            # available among all evidence (cited or not), flag it.
            authoritative_seen = any(
                c.get("source_role") in ("invariant", "open-decision")
                for c in chunks
            )
            first_is_fallback = bool(
                cited_chunks and cited_chunks[0].get("source_role") == "fallback"
            )
            role_warning = first_is_fallback and authoritative_seen
            if role_warning and confidence > 0.5:
                logger.info(
                    "CitedAnswerOp: capping confidence at 0.5 (fallback-as-primary "
                    "with authoritative evidence available)"
                )
                confidence = 0.5

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
                            "source_role": chunk.get("source_role"),
                            "doc_weight": chunk.get("doc_weight"),
                            "role_warning": role_warning,
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
