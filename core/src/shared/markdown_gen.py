"""HTML-to-Markdown generation for Workshop.

Inspired by crawl4ai's markdown_generation_strategy.py and html2text library
(vendor/crawl4ai). Referenced by AD-12 (document ingestion pipeline).

Uses only Python stdlib html.parser — zero external dependencies.

Used by:
  - intelflow: article/RSS body conversion
  - capture: raw HTML intake before adapter routing
  - memvault: web content ingestion
"""

from __future__ import annotations

import html
import html.parser
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Compiled once at module load
_LINK_PATTERN = re.compile(r"!?\[([^\]]*)\]\(([^)]+?)(?:\s+\"([^\"]*)\")?\)")
_MULTI_NL = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+\n")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class MarkdownResult:
    """Result from a markdown generator."""

    markdown: str
    links: list[str] = field(default_factory=list)
    title: str = ""


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------


class MarkdownGenerator(ABC):
    """Abstract base for HTML-to-Markdown converters."""

    name: str = "base"

    @abstractmethod
    def convert(self, html_input: str, **options) -> MarkdownResult:
        """Convert HTML string to MarkdownResult."""


# ---------------------------------------------------------------------------
# Internal parser
# ---------------------------------------------------------------------------

_BLOCK_TAGS = frozenset(["div", "section", "article", "main", "aside", "figure", "figcaption"])
_SKIP_DEFAULT = frozenset(["script", "style", "noscript"])
_CONTENT_SKIP = frozenset(["header", "footer", "nav"])
_HEADING_MAP = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class _HTMLToMarkdown(html.parser.HTMLParser):
    """Single-pass HTMLParser that emits Markdown tokens."""

    def __init__(
        self,
        strip_tags: frozenset[str],
        content_only: bool,
        links_as_citations: bool,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._strip = strip_tags
        self._content_only = content_only
        self._links_as_citations = links_as_citations

        self._buf: list[str] = []
        self._links: list[str] = []
        self._title: str = ""

        # state
        self._quiet = 0  # suppress output when > 0
        self._pre = False
        self._code = False
        self._in_title = False
        self._in_table = False
        self._td_buf: list[str] = []
        self._table_rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._list_stack: list[str] = []  # "ul" | "ol"
        self._list_counters: list[int] = []
        self._href: str | None = None
        self._link_text_buf: list[str] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def result(self) -> MarkdownResult:
        raw = "".join(self._buf)
        raw = _TRAILING_SPACES.sub("\n", raw)
        raw = _MULTI_NL.sub("\n\n", raw).strip()
        return MarkdownResult(markdown=raw, links=self._links, title=self._title)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._quiet == 0:
            if self._in_table and self._td_buf is not self._buf:
                self._td_buf.append(text)
            else:
                self._buf.append(text)

    def _emit_link_text(self, text: str) -> None:
        """Emit into link text buffer when inside <a>."""
        if self._href is not None:
            self._link_text_buf.append(text)
        else:
            self._emit(text)

    def _close_link(self) -> None:
        if self._href is None:
            return
        text = "".join(self._link_text_buf).strip() or self._href
        href = self._href
        self._href = None
        self._link_text_buf = []

        if self._links_as_citations:
            if href not in self._links:
                self._links.append(href)
            idx = self._links.index(href) + 1
            self._emit(f"{text}[{idx}]")
        else:
            self._emit(f"[{text}]({href})")

    def _list_indent(self) -> str:
        return "  " * (len(self._list_stack) - 1)

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = dict(attrs_list)

        # Suppress stripped / content-only-skipped tags
        if tag in self._strip:
            self._quiet += 1
            return
        if self._content_only and tag in _CONTENT_SKIP:
            self._quiet += 1
            return

        if tag == "title":
            self._in_title = True
            return

        if self._quiet:
            return

        # Headings
        if tag in _HEADING_MAP:
            self._buf.append(f"\n\n{_HEADING_MAP[tag]} ")
            return

        # Paragraph / block
        if tag == "p" or tag in _BLOCK_TAGS:
            self._buf.append("\n\n")
            return

        if tag == "br":
            self._buf.append("  \n")
            return

        if tag == "hr":
            self._buf.append("\n\n---\n\n")
            return

        # Emphasis
        if tag in ("strong", "b"):
            self._buf.append("**")
            return
        if tag in ("em", "i"):
            self._buf.append("_")
            return
        if tag in ("s", "del", "strike"):
            self._buf.append("~~")
            return

        # Code
        if tag == "code" and not self._pre:
            self._buf.append("`")
            self._code = True
            return
        if tag == "pre":
            lang = ""
            cls = attrs.get("class", "")
            if cls:
                m = re.search(r"language-(\S+)", cls)
                if m:
                    lang = m.group(1)
            self._buf.append(f"\n\n```{lang}\n")
            self._pre = True
            return

        # Links
        if tag == "a":
            href = attrs.get("href", "").strip()
            if href and not href.startswith(("javascript:", "#")):
                self._href = href
                self._link_text_buf = []
            return

        # Images
        if tag == "img":
            alt = attrs.get("alt", "")
            src = attrs.get("src", "")
            if src:
                self._emit(f"![{alt}]({src})")
            return

        # Lists
        if tag == "ul":
            self._list_stack.append("ul")
            self._list_counters.append(0)
            self._buf.append("\n")
            return
        if tag == "ol":
            self._list_stack.append("ol")
            self._list_counters.append(0)
            self._buf.append("\n")
            return
        if tag == "li":
            if self._list_stack:
                kind = self._list_stack[-1]
                indent = self._list_indent()
                if kind == "ul":
                    self._buf.append(f"\n{indent}- ")
                else:
                    self._list_counters[-1] += 1
                    n = self._list_counters[-1]
                    self._buf.append(f"\n{indent}{n}. ")
            return

        # Blockquote
        if tag == "blockquote":
            self._buf.append("\n\n> ")
            return

        # Tables
        if tag == "table":
            self._in_table = True
            self._table_rows = []
            return
        if tag in ("tr",):
            self._current_row = []
            return
        if tag in ("th", "td"):
            self._td_buf = []
            # Temporarily redirect emit to td_buf via flag
            self._buf_backup = self._buf
            self._buf = self._td_buf
            return

    def handle_endtag(self, tag: str) -> None:
        # Un-suppress
        if tag in self._strip or (self._content_only and tag in _CONTENT_SKIP):
            if self._quiet > 0:
                self._quiet -= 1
            return

        if tag == "title":
            self._in_title = False
            return

        if self._quiet:
            return

        if tag in _HEADING_MAP:
            self._buf.append("\n\n")
            return

        if tag == "p" or tag in _BLOCK_TAGS:
            self._buf.append("\n\n")
            return

        if tag in ("strong", "b"):
            self._buf.append("**")
            return
        if tag in ("em", "i"):
            self._buf.append("_")
            return
        if tag in ("s", "del", "strike"):
            self._buf.append("~~")
            return

        if tag == "code" and self._code:
            self._buf.append("`")
            self._code = False
            return
        if tag == "pre":
            self._buf.append("\n```\n\n")
            self._pre = False
            return

        if tag == "a":
            self._close_link()
            return

        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
                self._list_counters.pop()
            self._buf.append("\n")
            return

        if tag == "blockquote":
            self._buf.append("\n\n")
            return

        if tag in ("th", "td"):
            cell_text = "".join(self._buf).strip().replace("\n", " ")
            self._buf = self._buf_backup
            self._current_row.append(cell_text)
            return
        if tag == "tr":
            self._table_rows.append(self._current_row)
            return
        if tag == "table":
            self._in_table = False
            self._flush_table()
            return

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title += data
            return
        if self._quiet:
            return
        if self._pre:
            self._emit(data)
            return
        # Collapse whitespace outside pre
        text = re.sub(r"[ \t\r\n]+", " ", data)
        if self._href is not None:
            self._link_text_buf.append(text)
        else:
            self._emit(text)

    def _flush_table(self) -> None:
        if not self._table_rows:
            return
        rows = self._table_rows
        self._table_rows = []
        # Determine column count
        ncols = max(len(r) for r in rows)
        lines = ["\n\n"]
        for i, row in enumerate(rows):
            # Pad row
            while len(row) < ncols:
                row.append("")
            lines.append("| " + " | ".join(row) + " |")
            if i == 0:
                lines.append("| " + " | ".join(["---"] * ncols) + " |")
        lines.append("\n\n")
        self._buf.extend(lines)


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------


class DefaultMarkdownGenerator(MarkdownGenerator):
    """Workshop-native HTML-to-Markdown converter.

    Inspired by crawl4ai DefaultMarkdownGenerator and html2text library.
    See AD-12 (document ingestion pipeline) for design rationale.

    Uses only Python stdlib html.parser — no external dependencies.
    Handles the 80% case: headings, paragraphs, links, images, lists,
    bold/italic, code blocks, and tables.
    """

    name = "default"

    def convert(self, html_input: str, **options) -> MarkdownResult:
        """Convert HTML to Markdown.

        Args:
            html_input: Raw HTML string.
            links_as_citations: Replace inline links with [N] footnotes.
            strip_tags: Tags to completely remove (default: script, style, noscript).
            content_only: Skip header/footer/nav elements.

        Returns:
            MarkdownResult with markdown, links list, and page title.
        """
        if not html_input:
            return MarkdownResult(markdown="")

        links_as_citations: bool = options.get("links_as_citations", False)
        extra_strip: list[str] = options.get("strip_tags", [])
        content_only: bool = options.get("content_only", False)

        strip_tags = _SKIP_DEFAULT | frozenset(extra_strip)

        parser = _HTMLToMarkdown(
            strip_tags=strip_tags,
            content_only=content_only,
            links_as_citations=links_as_citations,
        )
        try:
            parser.feed(html_input)
            parser.close()
        except Exception:  # noqa: S110
            pass  # return whatever was parsed so far — partial output is still useful

        return parser.result()
