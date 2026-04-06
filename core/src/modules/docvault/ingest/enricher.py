"""EnrichmentOp — enrich document chunks with summary, relations, and ToC.

Post-chunking enrichment: generates a document summary, extracts
inter-chunk relations, and builds a table of contents from section paths.

Operator protocol:
  input_keys: ("chunks", "metadata")
  output_keys: ("summary", "relations", "table_of_contents")
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

# Summary generation: stub (LLM-based in Phase 2)
MAX_SUMMARY_CHUNKS = 5
MAX_SUMMARY_LENGTH = 500


def _generate_summary(chunks: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    """Generate a document summary from top chunks.

    Stub implementation — concatenates first N chunks.
    Will be replaced by LLM summarization in Phase 2.
    """
    title = metadata.get("title", "Untitled")
    source_type = metadata.get("source_type", "document")
    total_chunks = len(chunks)

    parts = [f"Document: {title} ({source_type}, {total_chunks} chunks)"]

    for chunk in chunks[:MAX_SUMMARY_CHUNKS]:
        content = chunk.get("raw_content", chunk.get("content", ""))
        section = chunk.get("section_path", "")
        excerpt = content[:150].strip()
        if section:
            parts.append(f"- [{section}] {excerpt}...")
        else:
            parts.append(f"- {excerpt}...")

    summary = "\n".join(parts)
    return summary[:MAX_SUMMARY_LENGTH]


def _extract_relations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract potential inter-document relations from chunk content.

    Stub implementation — detects reference patterns.
    LLM-based relation extraction in Phase 2.
    """
    relations: list[dict[str, Any]] = []

    for chunk in chunks:
        content = chunk.get("raw_content", chunk.get("content", ""))
        section = chunk.get("section_path", "")

        # Detect citation patterns (e.g., "see Document X", "根據 XXX 規定")
        if any(marker in content.lower() for marker in
               ("see ", "refer to ", "according to ", "根據", "參見", "依據", "引用")):
            relations.append({
                "type": "cites",
                "source_section": section,
                "evidence": content[:200],
                "confidence": 0.5,  # Low confidence for pattern match
            })

    return relations


def _build_table_of_contents(
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build table of contents from chunk section paths."""
    seen: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for i, chunk in enumerate(chunks):
        section = chunk.get("section_path", "")
        heading = chunk.get("heading", "")
        key = section or heading or f"Section {i + 1}"

        if key not in seen:
            seen[key] = {
                "heading": heading or key,
                "section_path": section,
                "chunk_start": i,
                "chunk_count": 1,
            }
        else:
            seen[key]["chunk_count"] += 1

    return list(seen.values())


class EnrichmentOp:
    """Enrich chunks with summary, relations, and table of contents.

    Operator protocol:
      input_keys: ("chunks", "metadata")
      output_keys: ("summary", "relations", "table_of_contents")
    """

    @property
    def name(self) -> str:
        return "enrichment"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("chunks", "metadata")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("summary", "relations", "table_of_contents")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        chunks: list[dict[str, Any]] = ctx.get("chunks", [])
        metadata: dict[str, Any] = ctx.get("metadata", {})

        if not chunks:
            ctx["summary"] = ""
            ctx["relations"] = []
            ctx["table_of_contents"] = []
            return ctx

        summary = _generate_summary(chunks, metadata)
        relations = _extract_relations(chunks)
        toc = _build_table_of_contents(chunks)

        ctx["summary"] = summary
        ctx["relations"] = relations
        ctx["table_of_contents"] = toc

        logger.info(
            "EnrichmentOp: %d chunks → summary=%d chars, %d relations, %d ToC entries",
            len(chunks),
            len(summary),
            len(relations),
            len(toc),
        )
        return ctx
