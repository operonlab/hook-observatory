"""Streaming re-indexing hook — P3.3 stub.

Status: DEFERRED. Full implementation gates on first real supersede
incident in production (per plan/agent-docvault-smart-search-buzzing-bird.md
P3.3 entry criteria).

Design intent (when activated):
  1. Subscribe to `docvault.document.updated` event (DocvaultEvents).
  2. On fire: load affected chunk ids → re-embed via embedding service →
     Qdrant upsert with new vectors → P2.2 cache freshness check picks
     up the new `doc.updated_at` automatically.
  3. Replace nightly batch re-index for these docs.

Why deferred:
  - No supersede incident yet — P3.2 status filter already covers the
    common case (drop superseded chunks at retrieval time).
  - Streaming re-embed needs benchmarking against MLX worker capacity
    (workshop infra) before going live.
  - VersionRAG hierarchical graph (the wider P3 vision) needs design
    review separately.

To activate:
  - Define DocvaultEvents.DOCUMENT_UPDATED in src/events/types.py.
  - Subscribe handle_document_updated() below in events.py.
  - Replace _stub_log with real re-embed pipeline (see qa_embed.py for
    the index pattern; FlatIndexOp.upsert may be reusable).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_document_updated(event: dict[str, Any]) -> None:
    """Stub handler — log + return. See module docstring for activation steps."""
    doc_id = event.get("document_id") or event.get("entity_id")
    logger.info(
        "streaming_reindex.handle_document_updated: doc_id=%s (stub, deferred)",
        doc_id,
    )
    # TODO(P3.3 activation): trigger re-embed + Qdrant upsert + cache
    # invalidation for `doc_id`. Until then, P3.2 status filter and
    # P2.2 cache invalidation collectively cover the correctness case
    # at retrieval time.
