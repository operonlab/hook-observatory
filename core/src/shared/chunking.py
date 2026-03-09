"""Text chunking strategies for Workshop.

Inspired by crawl4ai's chunking_strategy.py (vendor/crawl4ai).
Referenced by AD-12 (document ingestion pipeline).

Used by:
  - memvault: embedding chunking before nomic-embed-text indexing
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
