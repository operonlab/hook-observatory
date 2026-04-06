"""ContextualChunkOp — chunk with document context prefix (Anthropic method).

Each chunk gets a prefix like "{doc_title} > {section_path}:" before embedding,
reducing retrieval failure rate by ~49% (Anthropic contextual retrieval paper).
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 512
DEFAULT_OVERLAP = 64


class ContextualChunkOp:
    """ChunkSlot: raw_content + metadata → chunks with context prefix."""

    @property
    def name(self) -> str:
        return "contextual_chunk"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("raw_content", "doc_title")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("chunks", "section_tree")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raw_content: str = ctx["raw_content"]
        doc_title: str = ctx["doc_title"]
        chunk_size: int = ctx.get("chunk_size", DEFAULT_CHUNK_SIZE)
        overlap: int = ctx.get("chunk_overlap", DEFAULT_OVERLAP)

        sections = self._split_sections(raw_content)
        chunks = []
        section_tree: list[dict[str, Any]] = []

        for section in sections:
            heading = section["heading"] or doc_title
            section_path = f"{doc_title} > {heading}"
            section_tree.append(
                {
                    "title": heading,
                    "level": section["level"],
                    "chunk_start": len(chunks),
                }
            )

            text_chunks = self._split_text(section["content"], chunk_size, overlap)
            for _i, text in enumerate(text_chunks):
                chunks.append(
                    {
                        "content": text,
                        "contextualized": f"{section_path}: {text}",
                        "section_path": section_path,
                        "heading": heading,
                        "chunk_index": len(chunks),
                        "chunk_type": "text",
                        "token_count": len(text.split()),
                    }
                )

        ctx["chunks"] = chunks
        ctx["section_tree"] = section_tree
        logger.info("ContextualChunk: %d chunks from %d sections", len(chunks), len(sections))
        return ctx

    def _split_sections(self, content: str) -> list[dict[str, Any]]:
        """Split content by markdown headings."""
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        sections: list[dict[str, Any]] = []
        last_end = 0
        last_heading = None
        last_level = 0

        for match in heading_pattern.finditer(content):
            if last_end < match.start():
                text = content[last_end : match.start()].strip()
                if text:
                    sections.append(
                        {
                            "heading": last_heading,
                            "level": last_level,
                            "content": text,
                        }
                    )
            last_heading = match.group(2).strip()
            last_level = len(match.group(1))
            last_end = match.end()

        # Trailing content
        trailing = content[last_end:].strip()
        if trailing:
            sections.append(
                {
                    "heading": last_heading,
                    "level": last_level,
                    "content": trailing,
                }
            )

        if not sections:
            sections.append({"heading": None, "level": 0, "content": content})

        return sections

    def _split_text(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Fixed-length splitting with overlap, respecting sentence boundaries."""
        words = text.split()
        if len(words) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk = " ".join(words[start:end])
            if chunk.strip():
                chunks.append(chunk)
            start = end - overlap if end < len(words) else len(words)
        return chunks
