"""Vision-Route PDF rasterization — fallback path for scanned / image-only PDFs.

蠶食自 ConardLi/garden-skills kb-retriever/scripts/convert_pdf_to_images.py:
- pdf2image.convert_from_path with dpi=200 default
- Per-page resize with max_dim=1000 to bound vision-model input

Routing logic (called from ingest.parser._parse_pdf as fallback):
    if pdfplumber text extraction yields < THRESHOLD chars/page →
        route to vision_route.rasterize_pdf()
        → vision model OCR / description (separate concern, see below)

Vision model integration: this module ONLY rasterizes. The actual vision-call
hand-off is left as an integration point — callers pass the resulting image paths
to whichever vision backend they prefer (openai, claude, internal vision service).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DPI = 200
DEFAULT_MAX_DIM = 1000  # px, longer edge
# Empirical: pdfplumber yielding < 50 chars/page is the scanned-PDF signal
SCANNED_PDF_THRESHOLD_CHARS_PER_PAGE = 50


def is_likely_scanned_pdf(extracted_text: str, page_count: int) -> bool:
    """Heuristic: average chars/page below threshold ⇒ likely scanned."""
    if page_count <= 0:
        return False
    chars_per_page = len(extracted_text) / page_count
    return chars_per_page < SCANNED_PDF_THRESHOLD_CHARS_PER_PAGE


def rasterize_pdf(
    pdf_path: str,
    output_dir: str | None = None,
    dpi: int = DEFAULT_DPI,
    max_dim: int = DEFAULT_MAX_DIM,
) -> list[Path]:
    """Convert each PDF page to a PNG, resizing to bound vision-model input.

    Args:
        pdf_path: Path to source PDF.
        output_dir: Where to write PNGs. If None, uses a tempdir owned by caller
                    (caller responsible for cleanup).
        dpi: Rendering resolution.
        max_dim: Longer-edge pixel cap (downscale if exceeded).

    Returns:
        List of Path objects pointing to the rendered PNGs in page order.
    """
    from pdf2image import convert_from_path

    pdf = Path(pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="docvault-vision-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    images = convert_from_path(str(pdf), dpi=dpi)
    written: list[Path] = []

    for i, image in enumerate(images):
        # Resize if either dim exceeds max_dim
        w, h = image.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            image = image.resize(new_size)
            logger.debug("vision_route: resized page %d %sx%s → %s", i + 1, w, h, new_size)

        out_path = out_dir / f"page_{i + 1:03d}.png"
        image.save(out_path)
        written.append(out_path)

    logger.info(
        "vision_route.rasterize_pdf: %s → %d pages → %s",
        pdf_path, len(written), out_dir,
    )
    return written


def vision_extract_text(image_paths: list[Path]) -> str:
    """Hand-off point for vision-model text extraction.

    NOT implemented here — wire to your vision backend in the caller.
    Workshop currently has `vision` station (port 10204) and `ocr` station;
    integration is a follow-on task once this rasterization path is exercised
    in production.

    Suggested integration:
        from sdk_client.clients.vision_client import VisionClient
        vc = VisionClient()
        texts = [await vc.describe(p) for p in image_paths]
        return "\\n\\n".join(f"<!-- page {i+1} -->\\n{t}" for i, t in enumerate(texts))
    """
    raise NotImplementedError(
        "vision_extract_text: integration with Workshop vision station pending. "
        "Caller should integrate vision backend directly. "
        f"Rasterized {len(image_paths)} page(s) at {image_paths[0].parent if image_paths else '?'}"
    )


def vision_route_pdf(
    pdf_path: str,
    output_dir: str | None = None,
    dpi: int = DEFAULT_DPI,
    max_dim: int = DEFAULT_MAX_DIM,
) -> tuple[str, dict[str, Any]]:
    """End-to-end vision route: rasterize → extract → markdown.

    Currently raises NotImplementedError at the extract step. Surface the
    NotImplementedError to caller so it can decide whether to fall back to
    pdfplumber's partial output, or to record the document as "needs vision
    pipeline" and skip enrichment.

    Returns:
        (content_markdown, metadata_dict) — never reached until vision wired.
    """
    image_paths = rasterize_pdf(pdf_path, output_dir, dpi, max_dim)
    content = vision_extract_text(image_paths)  # raises NotImplementedError today
    metadata: dict[str, Any] = {
        "source_type": "pdf",
        "extraction_route": "vision",
        "pages": len(image_paths),
        "dpi": dpi,
        "max_dim": max_dim,
    }
    return content, metadata
