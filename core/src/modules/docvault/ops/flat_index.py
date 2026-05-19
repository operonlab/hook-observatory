"""FlatIndexOp — index document chunks into Qdrant.

Wraps shared/qdrant_search.py to index docvault chunks with
service_id='docvault-chunk' for unified workshop search.

Operator protocol:
  input_keys: ("chunks", "document_id", "version_id")
  output_keys: ("indexed_count", "index_errors")
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.qdrant_search import index_documents_batch
from src.shared.search_types import IndexDocument

logger = logging.getLogger(__name__)

SERVICE_ID = "docvault-chunk"


def _chunks_to_index_docs(
    chunks: list[dict[str, Any]],
    document_id: str,
    version_id: str,
    space_id: str,
) -> list[IndexDocument]:
    """Convert docvault chunks to IndexDocument format for Qdrant."""
    docs: list[IndexDocument] = []
    for i, chunk in enumerate(chunks):
        content = chunk.get("content", "")
        if not content.strip():
            continue
        # Use DB chunk ID as entity_id (enables DB content lookup from search results)
        # Falls back to composite key if db_id not available
        chunk_entity_id = chunk.get("db_id") or f"{document_id}:{version_id}:{i}"
        docs.append(
            IndexDocument(
                content=content,
                service_id=SERVICE_ID,
                entity_id=chunk_entity_id,
                entity_type="document_chunk",
                space_id=space_id,
                tags=chunk.get("tags", []),
                metadata={
                    "chunk_index": i,
                    "document_id": document_id,
                    "version_id": version_id,
                    "section_path": chunk.get("section_path", ""),
                    "page_range": chunk.get("page_range", ""),
                    "heading": chunk.get("heading", ""),
                    "token_count": chunk.get("token_count", 0),
                    "source_role": chunk.get("source_role"),
                    "doc_weight": chunk.get("doc_weight"),
                },
            )
        )
    return docs


class FlatIndexOp:
    """Index document chunks into Qdrant vector store.

    Operator protocol:
      input_keys: ("chunks", "document_id", "version_id")
      output_keys: ("indexed_count", "index_errors")
    """

    @property
    def name(self) -> str:
        return "flat_index"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("chunks", "document_id", "version_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("indexed_count", "index_errors")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        chunks: list[dict[str, Any]] = ctx.get("chunks", [])
        document_id: str = ctx.get("document_id", "")
        version_id: str = ctx.get("version_id", "")
        space_id: str = ctx.get("space_id", "default")

        if not chunks:
            ctx["indexed_count"] = 0
            ctx["index_errors"] = []
            return ctx

        index_docs = _chunks_to_index_docs(chunks, document_id, version_id, space_id)
        errors: list[str] = []

        try:
            await index_documents_batch(index_docs)
            indexed_count = len(index_docs)
        except Exception as e:
            logger.error("FlatIndexOp: batch index failed: %s", e)
            errors.append(str(e))
            indexed_count = 0

        ctx["indexed_count"] = indexed_count
        ctx["index_errors"] = errors

        logger.info(
            "FlatIndexOp: %d chunks → %d indexed, %d errors",
            len(chunks),
            indexed_count,
            len(errors),
        )
        return ctx
