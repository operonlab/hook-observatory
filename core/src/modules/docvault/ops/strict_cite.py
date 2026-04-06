"""StrictCiteOp — precise citation synthesis for medical/compliance domains.

SynthSlot implementation: question + evidence_chunks → answer + citations.
Every factual claim in the answer MUST be traceable to a specific chunk.
Claims without evidence are marked as unsupported rather than hallucinated.

Design principles:
  - Medical/compliance contexts demand zero hallucination tolerance
  - Each sentence in the answer gets an inline citation [n]
  - Unsupported claims are flagged, not silently included
  - Output includes a citation_map for verification
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Prompt template for strict citation synthesis
_STRICT_CITE_SYSTEM = """You are a precise citation assistant for {domain} documents.

RULES:
1. Every factual claim MUST cite a source using [n] notation
2. If no source supports a claim, write: "[UNSUPPORTED: <claim>]"
3. Never infer beyond what sources explicitly state
4. Use exact quotes when possible, paraphrase minimally
5. If sources conflict, state both positions with citations
6. Answer in the same language as the question

SOURCES:
{sources}

Format your answer with inline citations [1], [2], etc.
End with a CITATION MAP section listing each [n] with the source chunk ID."""

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")
_UNSUPPORTED_PATTERN = re.compile(r"\[UNSUPPORTED:\s*([^\]]+)\]")


def _format_sources(chunks: list[dict[str, Any]]) -> str:
    """Format evidence chunks into numbered source blocks."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        section = chunk.get("section_path", "Unknown section")
        page = chunk.get("page_range", "")
        page_info = f" (p.{page})" if page else ""
        content = chunk.get("content", "").strip()
        parts.append(f"[{i}] Section: {section}{page_info}\n{content}")
    return "\n\n".join(parts)


def _extract_citations(answer: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract citation references from the answer text."""
    citations: list[dict[str, Any]] = []
    seen: set[int] = set()

    for match in _CITATION_PATTERN.finditer(answer):
        idx = int(match.group(1))
        if idx in seen or idx < 1 or idx > len(chunks):
            continue
        seen.add(idx)
        chunk = chunks[idx - 1]
        citations.append({
            "index": idx,
            "document_id": chunk.get("document_id", ""),
            "chunk_id": chunk.get("chunk_id", chunk.get("id", "")),
            "section": chunk.get("section_path", ""),
            "page": chunk.get("page_range", ""),
            "quote": chunk.get("content", "")[:200],
        })

    return citations


def _extract_unsupported(answer: str) -> list[str]:
    """Extract unsupported claim markers from the answer."""
    return [m.group(1) for m in _UNSUPPORTED_PATTERN.finditer(answer)]


class StrictCiteOp:
    """SynthSlot Op: strict citation synthesis for medical/compliance domains.

    Implements the Operator protocol:
      - input_keys: ("question", "evidence_chunks")
      - output_keys: ("answer", "citations", "unsupported_claims", "confidence")

    Designed for domains where every claim must be evidence-backed.
    Uses LLM for synthesis but enforces citation discipline via prompt engineering
    and post-processing validation.
    """

    def __init__(self, domain: str = "medical") -> None:
        self._domain = domain

    @property
    def name(self) -> str:
        return "strict_cite"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("question", "evidence_chunks")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("answer", "citations", "unsupported_claims", "confidence")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        question: str = ctx.get("question", "")
        chunks: list[dict[str, Any]] = ctx.get("evidence_chunks", [])

        if not chunks:
            ctx["answer"] = "No evidence found to answer this question."
            ctx["citations"] = []
            ctx["unsupported_claims"] = []
            ctx["confidence"] = 0.0
            return ctx

        # Build prompt
        sources_text = _format_sources(chunks)
        system_prompt = _STRICT_CITE_SYSTEM.format(
            domain=self._domain,
            sources=sources_text,
        )

        # LLM call — stub for now, will be wired to LiteLLM in Phase 1
        # For now, generate a template answer showing the citation format
        answer = self._stub_answer(question, chunks)

        # Post-process
        citations = _extract_citations(answer, chunks)
        unsupported = _extract_unsupported(answer)

        # Confidence: penalize unsupported claims
        if unsupported:
            confidence = max(0.0, 0.8 - 0.2 * len(unsupported))
        elif citations:
            confidence = min(1.0, 0.6 + 0.1 * len(citations))
        else:
            confidence = 0.3

        ctx["answer"] = answer
        ctx["citations"] = citations
        ctx["unsupported_claims"] = unsupported
        ctx["confidence"] = confidence
        ctx["_synth_system_prompt"] = system_prompt  # for debugging

        logger.info(
            "StrictCiteOp: %d citations, %d unsupported, confidence=%.2f",
            len(citations),
            len(unsupported),
            confidence,
        )
        return ctx

    def _stub_answer(
        self, question: str, chunks: list[dict[str, Any]]
    ) -> str:
        """Stub answer for Phase 1 — will be replaced by LLM call."""
        parts = [f"Based on the available {self._domain} documents:"]
        for i, chunk in enumerate(chunks[:3], 1):
            excerpt = chunk.get("content", "")[:100].strip()
            parts.append(f"- {excerpt}... [{i}]")
        parts.append(
            "\n(StrictCiteOp stub — LLM synthesis pending Phase 1 integration)"
        )
        return "\n".join(parts)
