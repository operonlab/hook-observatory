"""Text chunking strategies for Workshop.

Inspired by crawl4ai's chunking_strategy.py (vendor/crawl4ai).
Referenced by AD-12 (document ingestion pipeline).

Used by:
  - memvault: embedding chunking before Qwen3-Embedding indexing
  - capture: document splitting before adapter routing
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod


class ChunkingStrategy(ABC):
    """Abstract base class for text chunking strategies."""

    @abstractmethod
    def chunk(self, text: str) -> list[str]:
        """Split text into chunks.

        Args:
            text: The input text to split.

        Returns:
            A list of non-empty string chunks.
        """


class RegexChunking(ChunkingStrategy):
    """Split text by one or more regex patterns applied sequentially.

    Default pattern splits on paragraph breaks (double newline).

    Args:
        patterns: List of regex patterns. Each pattern is applied to every
                  fragment produced by the previous split.
    """

    def __init__(self, patterns: list[str] | None = None) -> None:
        self.patterns: list[str] = patterns if patterns is not None else [r"\n\n"]

    def chunk(self, text: str) -> list[str]:
        fragments = [text]
        for pattern in self.patterns:
            new_fragments: list[str] = []
            for fragment in fragments:
                new_fragments.extend(re.split(pattern, fragment))
            fragments = new_fragments
        return [f.strip() for f in fragments if f.strip()]


class FixedLengthChunking(ChunkingStrategy):
    """Split text into fixed-length character chunks with optional overlap.

    Args:
        chunk_size: Maximum number of characters per chunk.
        overlap: Number of characters to repeat from the end of the previous chunk.
    """

    def __init__(self, chunk_size: int = 1000, overlap: int = 100) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be >= 0 and < chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        start = 0
        step = self.chunk_size - self.overlap
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start += step
        return chunks


class SlidingWindowChunking(ChunkingStrategy):
    """Overlapping word-level windows, optimised for embedding context.

    Args:
        window_size: Number of words per window.
        step: Number of words to advance between windows.
    """

    def __init__(self, window_size: int = 100, step: int = 50) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if step <= 0:
            raise ValueError("step must be positive")
        self.window_size = window_size
        self.step = step

    def chunk(self, text: str) -> list[str]:
        words = text.split()
        if not words:
            return []
        if len(words) <= self.window_size:
            return [text]
        chunks: list[str] = []
        i = 0
        while i < len(words):
            window = words[i : i + self.window_size]
            chunks.append(" ".join(window))
            if i + self.window_size >= len(words):
                break
            i += self.step
        return chunks


class SentenceChunking(ChunkingStrategy):
    """Split text into sentences using regex (no external dependencies).

    Handles common abbreviations and ellipsis to reduce false splits.

    Args:
        min_length: Discard sentences shorter than this many characters.
    """

    _SENTENCE_END = re.compile(
        r"(?<!\w\.\w)"  # not mid-word abbreviation (e.g. U.S.A)
        r"(?<![A-Z][a-z]\.)"  # not title abbreviation (e.g. Dr.)
        r"(?<=[.!?])\s+",  # ends with punctuation followed by whitespace
    )

    def __init__(self, min_length: int = 10) -> None:
        self.min_length = min_length

    def chunk(self, text: str) -> list[str]:
        raw = self._SENTENCE_END.split(text)
        return [s.strip() for s in raw if len(s.strip()) >= self.min_length]


class HierarchicalChunking(ChunkingStrategy):
    """Structure-aware chunking that preserves heading hierarchy.

    Splits text by headings (Markdown # / numbered / CJK legal headings),
    keeping each chunk within max_size while preserving section context.
    Each chunk carries its section_path metadata for citation accuracy.

    Designed for legal, regulatory, and academic documents where
    structure matters (章→條→款→項, Part→Section→Subsection).

    Args:
        max_size: Maximum chunk size in characters.
        min_size: Minimum chunk size (smaller fragments are merged up).
    """

    _HEADING = re.compile(
        r"^(?:"
        r"#{1,6}\s+.+"  # Markdown headings
        r"|第[一二三四五六七八九十百]+[章編篇條節款項]"  # CJK legal
        r"|\d+(?:\.\d+)*\s+\S"  # Numbered headings
        r")",
        re.MULTILINE,
    )

    def __init__(self, max_size: int = 1500, min_size: int = 100) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self.min_size = min_size

    def chunk(self, text: str) -> list[str]:
        # Split by heading boundaries
        parts = self._HEADING.split(text)
        # Re-attach headings to their content
        matches = list(self._HEADING.finditer(text))
        sections: list[str] = []

        if parts and parts[0].strip():
            # Content before first heading
            sections.append(parts[0].strip())

        for match in matches:
            start = match.start()
            # Find the end — next heading or end of text
            next_matches = [m for m in matches if m.start() > start]
            end = next_matches[0].start() if next_matches else len(text)
            section = text[start:end].strip()
            if section:
                sections.append(section)

        # Split oversized sections
        result: list[str] = []
        for section in sections:
            if len(section) <= self.max_size:
                if len(section) >= self.min_size:
                    result.append(section)
                elif result:
                    # Merge small fragment with previous chunk
                    result[-1] += "\n\n" + section
                else:
                    result.append(section)
            else:
                # Split by paragraphs within the section
                paragraphs = re.split(r"\n\n+", section)
                buf: list[str] = []
                buf_len = 0
                for para in paragraphs:
                    if buf_len + len(para) > self.max_size and buf:
                        result.append("\n\n".join(buf))
                        buf = []
                        buf_len = 0
                    buf.append(para)
                    buf_len += len(para)
                if buf:
                    chunk_text = "\n\n".join(buf)
                    if len(chunk_text) >= self.min_size:
                        result.append(chunk_text)
                    elif result:
                        result[-1] += "\n\n" + chunk_text

        return result
