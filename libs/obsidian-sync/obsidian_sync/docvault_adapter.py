"""Thin adapter wrapping sdk_client.docvault.DocvaultClient for Obsidian sync."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .frontmatter import build_metadata, extract_tags, extract_title, parse_frontmatter

_SDK_PATH = Path(
    os.environ.get(
        "WORKSHOP_SDK_PATH",
        str(Path.home() / "workshop" / "libs" / "sdk-client"),
    )
)
if str(_SDK_PATH) not in sys.path:
    sys.path.insert(0, str(_SDK_PATH))


class UploadResult:
    __slots__ = ("status", "document_id", "skipped_reason", "error")

    def __init__(
        self,
        status: str,
        document_id: str | None = None,
        skipped_reason: str | None = None,
        error: str | None = None,
    ):
        self.status = status
        self.document_id = document_id
        self.skipped_reason = skipped_reason
        self.error = error


class DocvaultAdapter:
    """Upload markdown files into a given docvault space, merging Obsidian frontmatter."""

    def __init__(
        self,
        space_id: str,
        timeout: float = 300.0,
        client: Any = None,
    ):
        self.space_id = space_id
        if client is None:
            from sdk_client.docvault import DocvaultClient

            client = DocvaultClient(space_id=space_id, timeout=timeout)
        self.client = client

    def upload_markdown(
        self,
        file_path: Path,
        vault: str,
        rel_path: str,
        base_tags: list[str],
    ) -> UploadResult:
        file_path = Path(file_path)
        meta_raw, body = parse_frontmatter(file_path)
        fm_tags = extract_tags(meta_raw)
        merged_tags = _dedup_preserve_order([*base_tags, *fm_tags])
        title = extract_title(meta_raw, body, fallback=file_path.stem)
        metadata = build_metadata(meta_raw, vault=vault, rel_path=rel_path)
        try:
            doc = self.client.upload(
                file_path=str(file_path),
                title=title,
                source_type="markdown",
                tags=merged_tags,
                metadata=metadata,
            )
            return UploadResult(status="uploaded", document_id=str(doc.get("id")))
        except Exception as exc:
            msg = str(exc)
            if "content_hash_conflict" in msg or "already exists" in msg:
                return UploadResult(status="duplicate", skipped_reason=msg[:200])
            if "timed out" in msg.lower():
                return UploadResult(status="timeout", skipped_reason=msg[:200])
            return UploadResult(status="error", error=msg[:500])

    def delete_document(self, document_id: str) -> bool:
        try:
            self.client.delete_document(document_id)
            return True
        except Exception:
            return False


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
