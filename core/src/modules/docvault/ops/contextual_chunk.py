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

# --- authority metadata helpers ---

_ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Headings can arrive with markdown prefix ("## Invariant") or stripped
    # by _extract_sections ("Invariant"). Both forms must match.
    (re.compile(r"^(?:#+\s+)?Invariant\b|^(?:#+\s+)?I\d+[a-z]*\b", re.IGNORECASE), "invariant"),
    (re.compile(r"^(?:#+\s+)?Open\s+Decision\b", re.IGNORECASE), "open-decision"),
    (re.compile(r"^(?:#+\s+)?Fallback\b|^(?:#+\s+)?Pass\b", re.IGNORECASE), "fallback"),
    (re.compile(r"^(?:#+\s+)?為什麼"), "decision-rationale"),
    (re.compile(r"^(?:#+\s+)?相關段落|^(?:#+\s+)?依據"), "reference"),
]

_DOC_WEIGHT_RULES: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"/00-(?:prd|spec|glossary)\.md$", re.IGNORECASE), 1.0),
    (re.compile(r"/changelog/blueprint-amendments/"), 1.0),
    (re.compile(r"/02-organized/tech/0[1-3][^/]*\.md$"), 0.95),
    (re.compile(r"/02-organized/tech/(?:0[4-9]|1[0-3])[^/]*\.md$"), 0.85),
    (re.compile(r"/01-scattered/"), 0.4),
    (re.compile(r"/00-source/"), 0.1),
]

_DEFAULT_DOC_WEIGHT = 0.7


def _extract_source_role(heading: str | None) -> str:
    """Map heading text to source_role using regex patterns."""
    if not heading:
        return "raw-note"
    for pattern, role in _ROLE_PATTERNS:
        if pattern.search(heading):
            return role
    return "raw-note"


def _extract_doc_weight(source_path: str | None) -> float:
    """Map file path to doc_weight."""
    if not source_path:
        return _DEFAULT_DOC_WEIGHT
    for pattern, weight in _DOC_WEIGHT_RULES:
        if pattern.search(source_path):
            return weight
    return _DEFAULT_DOC_WEIGHT

_PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
_CHAPTER_RE = re.compile(r"^Chapter\s+\d+\s*$", re.MULTILINE)


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (CJK-aware)."""
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    non_cjk = len(text) - cjk_chars
    return cjk_chars + (non_cjk // 4)


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs by double newlines."""
    return [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]


def _extract_sections(raw_content: str) -> list[dict[str, Any]]:
    """Extract sections with headings and page ranges from raw content.

    Detects <!-- page N --> markers and heading lines (markdown #, Chapter X,
    or _detect_heading_level from hierarchical_chunk).
    Returns list of {"heading", "page_start", "page_end", "content"}.
    """
    from .hierarchical_chunk import _detect_heading_level

    lines = raw_content.split("\n")
    sections: list[dict[str, Any]] = []
    current_heading = ""
    current_page = ""
    current_lines: list[str] = []

    for line in lines:
        # Track page markers
        pm = _PAGE_MARKER_RE.match(line.strip())
        if pm:
            current_page = pm.group(1)
            continue

        # Detect headings
        heading_result = _detect_heading_level(line)
        is_chapter = bool(_CHAPTER_RE.match(line.strip()))

        if heading_result or is_chapter:
            # Flush previous section
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append(
                        {
                            "heading": current_heading,
                            "page_start": sections[-1]["page_start"] if sections else current_page,
                            "page_end": current_page,
                            "content": text,
                        }
                    )
                current_lines = []

            if heading_result:
                _, heading_text = heading_result
                current_heading = heading_text
            elif is_chapter:
                current_heading = line.strip()

        current_lines.append(line)

    # Flush final section
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(
                {
                    "heading": current_heading,
                    "page_start": sections[-1]["page_start"] if sections else current_page,
                    "page_end": current_page,
                    "content": text,
                }
            )

    return sections


def _build_contextual_prefix(
    doc_title: str,
    section_path: str | None,
    heading_stack: list[str] | None = None,
) -> str:
    """Build contextual prefix: doc_title > H1 > H2 > H3 (full header path)."""
    parts = [doc_title]
    if heading_stack:
        parts.extend(heading_stack[:3])
    elif section_path:
        parts.append(section_path)
    return " > ".join(parts)


def _chunk_paragraphs(
    paragraphs: list[str],
    prefix: str,
    section_path: str | None,
    heading: str | None,
    page_range: str | None,
    max_chunk_size: int,
    min_chunk_size: int,
    overlap: int,
    source_role: str = "raw-note",
    doc_weight: float = _DEFAULT_DOC_WEIGHT,
) -> list[dict[str, Any]]:
    """Buffer paragraphs into chunks with metadata."""
    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    buffer_len = 0

    for para in paragraphs:
        para_len = len(para)

        if buffer_len + para_len > max_chunk_size and buffer:
            chunk_text = "\n\n".join(buffer)
            prefixed = f"{prefix}\n\n{chunk_text}"
            chunks.append(
                {
                    "content": prefixed,
                    "raw_content": chunk_text,
                    "section_path": section_path,
                    "heading": heading,
                    "page_range": page_range,
                    "prefix": prefix,
                    "token_count": _estimate_tokens(prefixed),
                    "source_role": source_role,
                    "doc_weight": doc_weight,
                }
            )
            if overlap > 0 and buffer:
                last = buffer[-1]
                buffer = [last] if len(last) <= overlap else []
                buffer_len = len(last) if buffer else 0
            else:
                buffer = []
                buffer_len = 0

        buffer.append(para)
        buffer_len += para_len

    if buffer:
        chunk_text = "\n\n".join(buffer)
        if len(chunk_text.strip()) >= min_chunk_size:
            prefixed = f"{prefix}\n\n{chunk_text}"
            chunks.append(
                {
                    "content": prefixed,
                    "raw_content": chunk_text,
                    "section_path": section_path,
                    "heading": heading,
                    "page_range": page_range,
                    "prefix": prefix,
                    "token_count": _estimate_tokens(prefixed),
                    "source_role": source_role,
                    "doc_weight": doc_weight,
                }
            )

    return chunks


def contextual_chunk(
    raw_content: str,
    doc_title: str,
    section_path: str | None = None,
    source_path: str | None = None,
    extract_headings: bool = False,
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    """Split content into chunks with contextual prefix.

    Each chunk is prefixed with "doc_title > H1 > H2 > H3" full header path
    to maintain self-contained context for embedding and retrieval.
    Each chunk carries source_role and doc_weight metadata for authority ranking.

    When extract_headings=True, detects headings and page markers in the
    raw content to populate section_path, heading, and page_range per chunk.
    """
    if not raw_content.strip():
        return []

    doc_weight = _extract_doc_weight(source_path)

    if extract_headings:
        sections = _extract_sections(raw_content)
        if sections:
            all_chunks: list[dict[str, Any]] = []
            # Track heading stack for full header path (max 3 levels)
            heading_stack: list[str] = []
            for sec in sections:
                sec_heading = sec.get("heading", "")
                if sec_heading:
                    # Maintain heading hierarchy: detect level from leading #
                    level = len(sec_heading) - len(sec_heading.lstrip("#"))
                    if level == 0:
                        level = 1
                    heading_text = sec_heading.lstrip("# ").strip()
                    heading_stack = heading_stack[: level - 1] + [heading_text]
                sec_path = f"{doc_title} > {sec_heading}" if sec_heading else doc_title
                page_start = sec.get("page_start", "")
                page_end = sec.get("page_end", "")
                page_range = (
                    f"{page_start}-{page_end}"
                    if page_start and page_end and page_start != page_end
                    else page_start
                )
                prefix = _build_contextual_prefix(
                    doc_title, sec_heading or None, heading_stack or None
                )
                source_role = _extract_source_role(sec_heading or None)
                paragraphs = _split_into_paragraphs(sec["content"])
                if paragraphs:
                    all_chunks.extend(
                        _chunk_paragraphs(
                            paragraphs,
                            prefix=prefix,
                            section_path=sec_path,
                            heading=sec_heading,
                            page_range=page_range,
                            max_chunk_size=max_chunk_size,
                            min_chunk_size=min_chunk_size,
                            overlap=overlap,
                            source_role=source_role,
                            doc_weight=doc_weight,
                        )
                    )
            if all_chunks:
                return all_chunks

    # Fallback: flat chunking without heading extraction
    prefix = _build_contextual_prefix(doc_title, section_path)
    source_role = _extract_source_role(section_path)
    paragraphs = _split_into_paragraphs(raw_content)
    if not paragraphs:
        return []
    return _chunk_paragraphs(
        paragraphs,
        prefix=prefix,
        section_path=section_path,
        heading=None,
        page_range=None,
        max_chunk_size=max_chunk_size,
        min_chunk_size=min_chunk_size,
        overlap=overlap,
        source_role=source_role,
        doc_weight=doc_weight,
    )


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
        source_path = metadata.get("source_path") or ctx.get("source_path")

        if not raw_content.strip():
            ctx["chunks"] = []
            return ctx

        chunks = contextual_chunk(
            raw_content,
            doc_title=doc_title,
            section_path=section_path,
            source_path=source_path,
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
