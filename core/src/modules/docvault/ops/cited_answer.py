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


def _resolve_model() -> str:
    """Pick first available model from candidates via LiteLLM /v1/models."""
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
                return candidate
    except Exception:
        logger.debug("_resolve_model: failed to query LiteLLM /models, using default")
    return _MODEL_CANDIDATES[0]


_SYSTEM_PROMPT = """\
You are a document QA assistant. Given a question and numbered evidence chunks \
from uploaded documents, produce a cited answer.

Rules:
- Every factual claim MUST cite its source using [N] notation matching chunk numbers.
- If evidence is insufficient, say so honestly — never fabricate.
- CRITICAL: Only answer what the documents ACTUALLY say. If the question uses \
terminology not found in the evidence (e.g., "three types" when evidence says \
"three categories"), explicitly note the terminology mismatch. Do NOT silently \
map one concept to another — state what the documents use and let the user decide.
- If the question's premise is wrong or unsupported (e.g., asking about concept X \
when documents never mention X), say so clearly. Do not force-fit related content.
- Answer in the same language as the question.
- Be concise but thorough. Prefer direct quotes when relevant.
- Rate confidence using this decision tree:
  Step 1: Can the question's KEY CONCEPTS be found verbatim in the documents?
    - YES (e.g., "sequential workflow orchestration" appears in docs) → match=true
    - NO (e.g., "three types of skills" but docs say "use case categories") → match=false
    Note: minor phrasing differences are OK (asking "steps" about a documented pattern = match).
    Only flag mismatch when the CORE CONCEPT itself is absent or named differently.
  Step 2 (if match=true): How complete is the answer?
    0.3-0.5 = partial. 0.6-0.8 = mostly. 0.9-1.0 = fully with direct quotes.
  Step 3 (if match=false): Note what the docs actually say.
    0.0 = no related content. 0.1-0.2 = related but different concept found.

Output format (strict JSON):
{
  "answer": "Your cited answer text with [1], [2] etc.",
  "citations_used": [1, 2, 3],
  "terminology_match": true,
  "confidence": 0.85
}
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


async def _llm_synthesize(
    question: str, chunks: list[dict[str, Any]]
) -> tuple[str, list[int], float]:
    """Call LLM to synthesize a cited answer. Returns (answer, citations_used, confidence)."""
    user_msg = _build_user_message(question, chunks)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_LITELLM_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {_LITELLM_KEY}"},
            json={
                "model": _resolve_model(),
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()

    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    parsed = _parse_llm_json(content)
    if not parsed:
        logger.warning("CitedAnswerOp: failed to parse LLM JSON, using raw text")
        return content, [], 0.3

    answer = parsed.get("answer", content)
    citations_used = parsed.get("citations_used", [])
    confidence = float(parsed.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    # Hard cap: if LLM reports terminology mismatch, enforce confidence ≤ 0.2
    terminology_match = parsed.get("terminology_match", True)
    if not terminology_match:
        confidence = min(confidence, 0.2)

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
