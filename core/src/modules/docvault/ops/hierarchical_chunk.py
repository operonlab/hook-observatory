"""HierarchicalChunkOp — structure-aware chunking for legal/regulatory documents.

ChunkSlot implementation: raw_content → chunks + section_tree.
Preserves heading hierarchy (chapter → section → subsection → paragraph)
and ensures each chunk carries its full section_path for citation accuracy.

Designed for documents with strict hierarchical structure:
  - Legal codes (章→條→款→項)
  - Technical specifications (Part → Section → Subsection)
  - Academic papers (Chapter → Section → Subsection)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Heading patterns ordered by depth (most specific first)
_HEADING_PATTERNS: list[tuple[int, re.Pattern[str]]] = [
    # Markdown headings
    (1, re.compile(r"^#{1}\s+(.+)$", re.MULTILINE)),
    (2, re.compile(r"^#{2}\s+(.+)$", re.MULTILINE)),
    (3, re.compile(r"^#{3}\s+(.+)$", re.MULTILINE)),
    (4, re.compile(r"^#{4}\s+(.+)$", re.MULTILINE)),
    # CJK legal structure (法條)
    (1, re.compile(r"^第[一二三四五六七八九十百]+[章編篇]", re.MULTILINE)),
    (2, re.compile(r"^第[一二三四五六七八九十百]+[條節]", re.MULTILINE)),
    (3, re.compile(r"^第[一二三四五六七八九十百]+款", re.MULTILINE)),
    (4, re.compile(r"^第[一二三四五六七八九十百]+項", re.MULTILINE)),
    # Numbered headings
    (1, re.compile(r"^(\d+)\.\s+(.+)$", re.MULTILINE)),
    (2, re.compile(r"^(\d+\.\d+)\s+(.+)$", re.MULTILINE)),
    (3, re.compile(r"^(\d+\.\d+\.\d+)\s+(.+)$", re.MULTILINE)),
]

# Default max chunk size in characters
DEFAULT_MAX_CHUNK_SIZE = 1500
DEFAULT_MIN_CHUNK_SIZE = 100


@dataclass
class SectionNode:
    """A node in the document's section tree."""

    heading: str
    level: int
    content: str = ""
    children: list[SectionNode] = field(default_factory=list)
    page_hint: str | None = None

    @property
    def section_path(self) -> str:
        """Build section path from root to this node (set by tree builder)."""
        return self.heading


@dataclass
class HierarchicalChunk:
    """A single chunk with its hierarchical context."""

    content: str
    section_path: str
    heading: str | None
    chunk_type: str = "text"
    page_range: str | None = None
    token_count: int = 0


def _detect_heading_level(line: str) -> tuple[int, str] | None:
    """Detect if a line is a heading and return (level, heading_text)."""
    stripped = line.strip()
    if not stripped:
        return None

    # Markdown headings (most common)
    md_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
    if md_match:
        level = len(md_match.group(1))
        return (level, md_match.group(2).strip())

    # CJK legal headings
    for level, pattern in _HEADING_PATTERNS[4:8]:  # CJK patterns
        if pattern.match(stripped):
            return (level, stripped)

    # Numbered headings (e.g., "1.2.3 Title")
    num_match = re.match(r"^(\d+(?:\.\d+)*)\s+(.+)$", stripped)
    if num_match:
        dots = num_match.group(1).count(".")
        return (dots + 1, stripped)

    return None


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (CJK-aware)."""
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    non_cjk = len(text) - cjk_chars
    return cjk_chars + (non_cjk // 4)


def build_section_tree(text: str) -> list[SectionNode]:
    """Parse document text into a hierarchical section tree."""
    lines = text.split("\n")
    root_children: list[SectionNode] = []
    stack: list[SectionNode] = []  # stack of parent nodes

    current_content_lines: list[str] = []

    def flush_content() -> None:
        """Assign accumulated content to the current deepest node."""
        if not current_content_lines:
            return
        content = "\n".join(current_content_lines).strip()
        if not content:
            current_content_lines.clear()
            return
        if stack:
            stack[-1].content += ("\n\n" + content) if stack[-1].content else content
        current_content_lines.clear()

    for line in lines:
        heading_info = _detect_heading_level(line)
        if heading_info is None:
            current_content_lines.append(line)
            continue

        flush_content()
        level, heading_text = heading_info
        node = SectionNode(heading=heading_text, level=level)

        # Pop stack until we find a parent with lower level
        while stack and stack[-1].level >= level:
            stack.pop()

        if stack:
            stack[-1].children.append(node)
        else:
            root_children.append(node)

        stack.append(node)

    flush_content()

    # If no headings found, create a single root node
    if not root_children and text.strip():
        root_children.append(SectionNode(heading="(untitled)", level=0, content=text.strip()))

    return root_children


def _build_path(ancestors: list[str], current: str) -> str:
    """Build section path string from ancestor headings + current."""
    parts = [*ancestors, current]
    return " > ".join(parts)


def _flatten_to_chunks(
    nodes: list[SectionNode],
    ancestors: list[str],
    max_size: int = DEFAULT_MAX_CHUNK_SIZE,
    min_size: int = DEFAULT_MIN_CHUNK_SIZE,
) -> list[HierarchicalChunk]:
    """Recursively flatten section tree into chunks."""
    chunks: list[HierarchicalChunk] = []

    for node in nodes:
        path = _build_path(ancestors, node.heading)
        new_ancestors = [*ancestors, node.heading]

        # Node's own content → chunk(s)
        if node.content and len(node.content.strip()) >= min_size:
            content = node.content.strip()
            if len(content) <= max_size:
                chunks.append(
                    HierarchicalChunk(
                        content=content,
                        section_path=path,
                        heading=node.heading,
                        token_count=_estimate_tokens(content),
                    )
                )
            else:
                # Split large content by paragraphs
                paragraphs = re.split(r"\n\n+", content)
                buffer: list[str] = []
                buffer_len = 0
                for para in paragraphs:
                    para_len = len(para)
                    if buffer_len + para_len > max_size and buffer:
                        chunk_text = "\n\n".join(buffer)
                        chunks.append(
                            HierarchicalChunk(
                                content=chunk_text,
                                section_path=path,
                                heading=node.heading,
                                token_count=_estimate_tokens(chunk_text),
                            )
                        )
                        buffer = []
                        buffer_len = 0
                    buffer.append(para)
                    buffer_len += para_len
                if buffer:
                    chunk_text = "\n\n".join(buffer)
                    if len(chunk_text.strip()) >= min_size:
                        chunks.append(
                            HierarchicalChunk(
                                content=chunk_text,
                                section_path=path,
                                heading=node.heading,
                                token_count=_estimate_tokens(chunk_text),
                            )
                        )

        # Recurse into children
        if node.children:
            chunks.extend(
                _flatten_to_chunks(node.children, new_ancestors, max_size, min_size)
            )

    return chunks


class HierarchicalChunkOp:
    """ChunkSlot Op: structure-aware hierarchical chunking.

    Implements the Operator protocol:
      - input_keys: ("raw_content",)
      - output_keys: ("chunks", "section_tree")

    Designed for legal, regulatory, and highly-structured documents
    where section hierarchy must be preserved in each chunk's metadata.
    """

    def __init__(
        self,
        max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
    ) -> None:
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size

    @property
    def name(self) -> str:
        return "hierarchical_chunk"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("raw_content",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("chunks", "section_tree")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raw_content: str = ctx.get("raw_content", "")
        if not raw_content.strip():
            ctx["chunks"] = []
            ctx["section_tree"] = []
            return ctx

        tree = build_section_tree(raw_content)
        chunks = _flatten_to_chunks(
            tree, [], self._max_chunk_size, self._min_chunk_size
        )

        ctx["chunks"] = [
            {
                "content": c.content,
                "section_path": c.section_path,
                "heading": c.heading,
                "chunk_type": c.chunk_type,
                "page_range": c.page_range,
                "token_count": c.token_count,
            }
            for c in chunks
        ]
        ctx["section_tree"] = _serialize_tree(tree)

        logger.info(
            "HierarchicalChunkOp: %d sections → %d chunks",
            len(tree),
            len(chunks),
        )
        return ctx


def _serialize_tree(nodes: list[SectionNode]) -> list[dict[str, Any]]:
    """Serialize section tree for JSON storage (table_of_contents)."""
    result: list[dict[str, Any]] = []
    for node in nodes:
        entry: dict[str, Any] = {
            "heading": node.heading,
            "level": node.level,
            "has_content": bool(node.content.strip()),
        }
        if node.children:
            entry["children"] = _serialize_tree(node.children)
        result.append(entry)
    return result
