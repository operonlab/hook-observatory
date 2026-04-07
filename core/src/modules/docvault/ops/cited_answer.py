"""CitedAnswerOp — generate answer with inline citations via LLM.

Default SynthSlot implementation for factual QA.
Produces an answer where every claim cites a source chunk.

Operator protocol:
  input_keys: ("question", "evidence_chunks")
  output_keys: ("answer", "citations", "confidence")
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_LITELLM_BASE = "http://localhost:4000/v1"
_LITELLM_KEY = "sk-litellm-local-dev"
_TIMEOUT = 30.0

# Model preference order — LiteLLM config changes externally
_MODEL_CANDIDATES = ["deepseek-v3", "qwen3.5-flash", "grok-4.1-fast", "gemini-3.1-flash"]


_cached_model: str | None = None
_cached_model_ts: float = 0.0


def _resolve_model() -> str:
    """Pick first available model from candidates via LiteLLM /v1/models. Cached 60s."""
    import time

    global _cached_model, _cached_model_ts
    now = time.monotonic()
    if _cached_model and (now - _cached_model_ts) < 60:
        return _cached_model

    try:
        import httpx

        resp = httpx.get(
            f"{_LITELLM_BASE}/models",
            headers={"Authorization": f"Bearer {_LITELLM_KEY}"},
            timeout=3,
        )
        available = {m["id"] for m in resp.json().get("data", [])}
        for candidate in _MODEL_CANDIDATES:
            if candidate in available:
                _cached_model = candidate
                _cached_model_ts = now
                return candidate
    except Exception:
        logger.debug("_resolve_model: failed to query LiteLLM /models, using default")
    _cached_model = _MODEL_CANDIDATES[0]
    _cached_model_ts = now
    return _cached_model


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


def _parse_llm_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
    return None


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


async def _llm_call(system: str, user_msg: str, temperature: float = 0.2) -> str:
    """Single LLM call helper. Returns raw content string."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_LITELLM_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {_LITELLM_KEY}"},
            json={
                "model": _resolve_model(),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def _llm_synthesize(
    question: str, chunks: list[dict[str, Any]]
) -> tuple[str, list[int], float]:
    """Two-pass parallel synthesis.

    Pass 1 (analogy extraction) and Pass 2 (cited answer) run concurrently.
    If Pass 1 finds analogies, they are woven into the final answer.
    """
    import asyncio

    user_msg = _build_user_message(question, chunks)

    # ── Parallel: verify+analogy extraction + factual synthesis ──
    async def _verify_and_extract() -> dict[str, Any]:
        try:
            raw = await _llm_call(_VERIFY_PROMPT, user_msg, temperature=0.1)
            parsed = _parse_llm_json(raw)
            return parsed if parsed else {"missed": [], "analogies": []}
        except Exception:
            logger.debug("Verify pass failed, skipping")
            return {"missed": [], "analogies": []}

    async def _synthesize() -> dict[str, Any]:
        raw = await _llm_call(_SYSTEM_PROMPT, user_msg)
        parsed = _parse_llm_json(raw)
        if not parsed:
            logger.warning("CitedAnswerOp: failed to parse LLM JSON, using raw text")
            return {"answer": raw, "citations_used": [], "confidence": 0.3}
        return parsed

    verify_result, synth_result = await asyncio.gather(_verify_and_extract(), _synthesize())

    answer = synth_result.get("answer", "")
    citations_used = synth_result.get("citations_used", [])
    confidence = float(synth_result.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    # Hard cap: if LLM reports terminology mismatch, enforce confidence ≤ 0.2
    terminology_match = synth_result.get("terminology_match", True)
    if not terminology_match:
        confidence = min(confidence, 0.2)

    # ── Dedup helper ──
    def _dedup_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            key = item.get("text", "")[:60]
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    # ── Merge missed content (append to answer) ──
    missed = _dedup_items(verify_result.get("missed", []))
    novel_missed = [m for m in missed if m.get("text", "")[:40] not in answer]
    if novel_missed:
        supplement_lines = []
        for m in novel_missed[:3]:
            chunk_ref = f"[{m['chunk']}]" if m.get("chunk") else ""
            supplement_lines.append(f"- {m['text']} {chunk_ref}")
            idx = m.get("chunk")
            if idx and idx not in citations_used:
                citations_used.append(idx)
        answer = f"{answer}\n\nAdditional relevant details from the document:\n" + "\n".join(
            supplement_lines
        )

    # ── Merge analogies (prepend to answer) ──
    analogies = _dedup_items(verify_result.get("analogies", []))
    novel_analogies = [a for a in analogies if a.get("text", "")[:40] not in answer]
    if novel_analogies:
        analogy_lines = []
        for a in novel_analogies[:2]:
            chunk_ref = f"[{a['chunk']}]" if a.get("chunk") else ""
            analogy_lines.append(f"{a['text']} {chunk_ref}")
            idx = a.get("chunk")
            if idx and idx not in citations_used:
                citations_used.append(idx)
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
