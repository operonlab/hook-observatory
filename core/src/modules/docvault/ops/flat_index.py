"""FlatIndexOp — basic Qdrant indexing for document chunks.

IndexSlot: chunks → indexed_collection (service_id="docvault-chunk").
Wraps shared qdrant_search.index_documents_batch().
"""

import logging
from typing import Any

from src.shared import qdrant_search
from src.shared.embedding import get_embeddings_batch

logger = logging.getLogger(__name__)

SERVICE_ID = "docvault-chunk"


class FlatIndexOp:
    """IndexSlot: embed chunks and index into Qdrant."""

    @property
    def name(self) -> str:
        return "flat_index"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("chunks", "document_id", "version_id", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("indexed_count",)

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        chunks: list[dict] = ctx["chunks"]
        document_id: str = ctx["document_id"]
        version_id: str = ctx["version_id"]
        space_id: str = ctx["space_id"]

        if not chunks:
            ctx["indexed_count"] = 0
            return ctx

        # Use contextualized text for embedding if available
        texts = [c.get("contextualized", c["content"]) for c in chunks]
        embeddings = await get_embeddings_batch(texts, task_type="search_document")

        docs = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=False)):
            if emb is None:
                logger.warning("Embedding failed for chunk %d, skipping", i)
                continue
            docs.append(
                qdrant_search.IndexDocument(
                    entity_id=f"{version_id}:{chunk['chunk_index']}",
                    entity_type="docvault_chunk",
                    service_id=SERVICE_ID,
                    space_id=space_id,
                    content=chunk["content"],
                    embedding=emb,
                    metadata={
                        "document_id": document_id,
                        "version_id": version_id,
                        "chunk_index": chunk["chunk_index"],
                        "section_path": chunk.get("section_path", ""),
                        "heading": chunk.get("heading", ""),
                        "page_range": chunk.get("page_range", ""),
                        "chunk_type": chunk.get("chunk_type", "text"),
                    },
                )
            )

        if docs:
            await qdrant_search.index_documents_batch(docs)

        ctx["indexed_count"] = len(docs)
        logger.info(
            "FlatIndex: indexed %d/%d chunks for doc %s", len(docs), len(chunks), document_id
        )
        return ctx
