"""ContextualChunkOp — prefix each chunk with doc_title > section_path.

Enriches raw chunks by prepending hierarchical context so that
each chunk is self-contained when embedded or displayed.

Operator protocol:
  input_keys: ("raw_content", "metadata")
  output_keys: ("chunks",)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHUNK_SIZE = 1500
DEFAULT_MIN_CHUNK_SIZE = 100
DEFAULT_OVERLAP = 100


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (CJK-aware)."""
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    non_cjk = len(text) - cjk_chars
    return cjk_chars + (non_cjk // 4)


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs by double newlines."""
    return [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]


def _build_contextual_prefix(doc_title: str, section_path: str | None) -> str:
    """Build the contextual prefix: doc_title > section_path."""
    parts = [doc_title]
    if section_path:
        parts.append(section_path)
    return " > ".join(parts)


def contextual_chunk(
    raw_content: str,
    doc_title: str,
    section_path: str | None = None,
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    """Split content into chunks with contextual prefix.

    Each chunk is prefixed with "doc_title > section_path: " to maintain
    self-contained context for embedding and retrieval.
    """
    prefix = _build_contextual_prefix(doc_title, section_path)
    paragraphs = _split_into_paragraphs(raw_content)

    if not paragraphs:
        return []

    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    buffer_len = 0

    for para in paragraphs:
        para_len = len(para)

        if buffer_len + para_len > max_chunk_size and buffer:
            chunk_text = "\n\n".join(buffer)
            prefixed = f"{prefix}: {chunk_text}"
            chunks.append({
                "content": prefixed,
                "raw_content": chunk_text,
                "section_path": section_path,
                "prefix": prefix,
                "token_count": _estimate_tokens(prefixed),
            })
            # Keep last paragraph for overlap
            if overlap > 0 and buffer:
                last = buffer[-1]
                buffer = [last] if len(last) <= overlap else []
                buffer_len = len(last) if buffer else 0
            else:
                buffer = []
                buffer_len = 0

        buffer.append(para)
        buffer_len += para_len

    # Flush remaining buffer
    if buffer:
        chunk_text = "\n\n".join(buffer)
        if len(chunk_text.strip()) >= min_chunk_size:
            prefixed = f"{prefix}: {chunk_text}"
            chunks.append({
                "content": prefixed,
                "raw_content": chunk_text,
                "section_path": section_path,
                "prefix": prefix,
                "token_count": _estimate_tokens(prefixed),
            })

    return chunks


class ContextualChunkOp:
    """Chunk raw content with contextual doc_title > section_path prefix.

    Operator protocol:
      input_keys: ("raw_content", "metadata")
      output_keys: ("chunks",)
    """

    def __init__(
        self,
        max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ) -> None:
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size
        self._overlap = overlap

    @property
    def name(self) -> str:
        return "contextual_chunk"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("raw_content", "metadata")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("chunks",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raw_content: str = ctx.get("raw_content", "")
        metadata: dict[str, Any] = ctx.get("metadata", {})
        doc_title = metadata.get("title", ctx.get("doc_title", "Untitled"))
        section_path = metadata.get("section_path")

        if not raw_content.strip():
            ctx["chunks"] = []
            return ctx

        chunks = contextual_chunk(
            raw_content,
            doc_title=doc_title,
            section_path=section_path,
            max_chunk_size=self._max_chunk_size,
            min_chunk_size=self._min_chunk_size,
            overlap=self._overlap,
        )

        ctx["chunks"] = chunks

        logger.info(
            "ContextualChunkOp: %d chars → %d chunks (prefix=%r)",
            len(raw_content),
            len(chunks),
            doc_title[:40],
        )
        return ctx
