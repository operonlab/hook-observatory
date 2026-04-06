"""DocumentParserOp — extract markdown + metadata from raw files.

Supports PDF (via pdfplumber), DOCX (via python-docx), and plain markdown.
Outputs normalized markdown content and extracted metadata.

Operator protocol:
  input_keys: ("raw_file", "source_type")
  output_keys: ("raw_content", "metadata")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _parse_pdf(file_path: str) -> tuple[str, dict[str, Any]]:
    """Extract text and metadata from PDF using pdfplumber."""
    import pdfplumber

    metadata: dict[str, Any] = {"source_type": "pdf", "pages": 0}
    pages_text: list[str] = []

    with pdfplumber.open(file_path) as pdf:
        metadata["pages"] = len(pdf.pages)
        pdf_meta = pdf.metadata or {}
        metadata["title"] = pdf_meta.get("Title", Path(file_path).stem)
        metadata["author"] = pdf_meta.get("Author", "")
        metadata["creation_date"] = pdf_meta.get("CreationDate", "")

        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                pages_text.append(f"<!-- page {i + 1} -->\n{text}")

    content = "\n\n".join(pages_text)
    return content, metadata


def _parse_docx(file_path: str) -> tuple[str, dict[str, Any]]:
    """Extract text and metadata from DOCX using python-docx."""
    from docx import Document

    doc = Document(file_path)
    metadata: dict[str, Any] = {"source_type": "docx"}

    core = doc.core_properties
    metadata["title"] = core.title or Path(file_path).stem
    metadata["author"] = core.author or ""
    metadata["creation_date"] = str(core.created) if core.created else ""

    parts: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # Convert heading styles to markdown
        style_name = para.style.name if para.style else ""
        if style_name.startswith("Heading"):
            try:
                level = int(style_name.replace("Heading", "").strip())
                parts.append(f"{'#' * level} {text}")
            except ValueError:
                parts.append(text)
        else:
            parts.append(text)

    content = "\n\n".join(parts)
    metadata["paragraphs"] = len(parts)
    return content, metadata


def _parse_markdown(file_path: str) -> tuple[str, dict[str, Any]]:
    """Read markdown file directly."""
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    metadata: dict[str, Any] = {
        "source_type": "markdown",
        "title": path.stem,
    }
    return content, metadata


def parse_document(
    file_path: str,
    source_type: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Parse a document file into markdown content + metadata.

    Args:
        file_path: Path to the source file.
        source_type: Explicit type ("pdf", "docx", "markdown"). Auto-detected if None.

    Returns:
        (content_markdown, metadata_dict)
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    # Auto-detect source type from extension
    if source_type is None:
        ext = path.suffix.lower()
        type_map = {
            ".pdf": "pdf",
            ".docx": "docx",
            ".doc": "docx",
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "markdown",
        }
        source_type = type_map.get(ext, "markdown")

    parsers = {
        "pdf": _parse_pdf,
        "docx": _parse_docx,
        "markdown": _parse_markdown,
    }

    parser_fn = parsers.get(source_type, _parse_markdown)
    content, metadata = parser_fn(file_path)
    metadata["file_path"] = file_path
    metadata["file_size"] = path.stat().st_size

    return content, metadata


class DocumentParserOp:
    """Parse raw document files into markdown + metadata.

    Supports PDF (pdfplumber), DOCX (python-docx), and markdown.

    Operator protocol:
      input_keys: ("raw_file", "source_type")
      output_keys: ("raw_content", "metadata")
    """

    @property
    def name(self) -> str:
        return "document_parser"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("raw_file", "source_type")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("raw_content", "metadata")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raw_file: str = ctx.get("raw_file", "")
        source_type: str | None = ctx.get("source_type")

        if not raw_file:
            ctx["raw_content"] = ""
            ctx["metadata"] = {}
            return ctx

        content, metadata = parse_document(raw_file, source_type)

        ctx["raw_content"] = content
        ctx["metadata"] = metadata

        logger.info(
            "DocumentParserOp: %s → %d chars, type=%s",
            raw_file,
            len(content),
            metadata.get("source_type", "?"),
        )
        return ctx
