"""ChunkEntityOp — extract KG entities and triples from document chunks.

Runs during document ingestion after chunking. For each chunk, calls the
shared kg_ops library to extract SPO triples via LLM. Entities are
deduplicated per-document by canonical_name, then batch-inserted into
DocEntity and DocTriple tables.

Operator protocol:
  input_keys: ("chunks", "document_id", "space_id", "db")
  output_keys: ("entity_count", "triple_count", "doc_entities", "doc_triples")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from kg_ops import extract_triples, normalize_entity_text

from ..kg_models import DocEntity, DocTriple

logger = logging.getLogger(__name__)

# LLM defaults — matches LiteLLM local-dev config
_DEFAULT_LLM_BASE_URL = "http://localhost:4000/v1"
_DEFAULT_LLM_API_KEY = "sk-litellm-local-dev"
_DEFAULT_MODEL = "deepseek-v3"
_DEFAULT_MAX_TRIPLES = 5
_DEFAULT_MAX_CONCURRENT = 5


async def _extract_chunk_triples(
    chunk: dict[str, Any],
    *,
    llm_base_url: str,
    llm_api_key: str,
    model: str,
    max_triples: int,
    semaphore: asyncio.Semaphore,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Extract triples from a single chunk with semaphore-controlled concurrency.

    Returns (chunk, triples). On LLM failure returns empty triples list.
    """
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def _call_with_retry() -> list[dict[str, str]]:
        return await extract_triples(
            chunk["content"],
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            model=model,
            max_triples=max_triples,
        )

    async with semaphore:
        try:
            triples = await _call_with_retry()
        except Exception:
            logger.warning(
                "ChunkEntityOp: triple extraction failed for chunk db_id=%r (after retries)",
                chunk.get("db_id"),
                exc_info=True,
            )
            triples = []
        return chunk, triples


def _build_entity_dedup_map(
    chunk_triples_pairs: list[tuple[dict[str, Any], list[dict[str, str]]]],
) -> dict[str, dict[str, Any]]:
    """Build canonical_name → entity record map (per-document dedup).

    Merges aliases and increments mention_count when the same canonical name
    appears in multiple chunks.
    """
    entity_map: dict[str, dict[str, Any]] = {}

    for chunk, triples in chunk_triples_pairs:
        chunk_id = chunk.get("db_id")

        for triple in triples:
            for raw_name in (triple["subject"], triple["object"]):
                canonical = normalize_entity_text(raw_name)
                if not canonical:
                    continue

                if canonical in entity_map:
                    record = entity_map[canonical]
                    # Accumulate aliases — original form if different from canonical
                    if raw_name != canonical and raw_name not in record["aliases"]:
                        record["aliases"].append(raw_name)
                    # Track source chunks
                    if chunk_id and chunk_id not in record["source_chunk_ids"]:
                        record["source_chunk_ids"].append(chunk_id)
                    record["mention_count"] += 1
                else:
                    aliases = [raw_name] if raw_name != canonical else []
                    entity_map[canonical] = {
                        "canonical_name": canonical,
                        "aliases": aliases,
                        "entity_type": "concept",
                        "source_chunk_ids": [chunk_id] if chunk_id else [],
                        "mention_count": 1,
                    }

    return entity_map


class ChunkEntityOp:
    """Extract KG entities and triples from document chunks.

    Operator protocol:
      input_keys: ("chunks", "document_id", "space_id", "db")
      output_keys: ("entity_count", "triple_count", "doc_entities", "doc_triples")

    If "db" is not present in ctx, KG extraction is skipped and the operator
    returns immediately — extraction is considered optional (best-effort).
    """

    def __init__(
        self,
        llm_base_url: str = _DEFAULT_LLM_BASE_URL,
        llm_api_key: str = _DEFAULT_LLM_API_KEY,
        model: str = _DEFAULT_MODEL,
        max_triples: int = _DEFAULT_MAX_TRIPLES,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self._llm_base_url = llm_base_url
        self._llm_api_key = llm_api_key
        self._model = model
        self._max_triples = max_triples
        self._max_concurrent = max_concurrent

    # ------------------------------------------------------------------ protocol

    @property
    def name(self) -> str:
        return "chunk_entity"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("chunks", "document_id", "space_id", "db")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("entity_count", "triple_count", "doc_entities", "doc_triples")

    # ------------------------------------------------------------------ __call__

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        db = ctx.get("db")
        if db is None:
            logger.warning(
                "ChunkEntityOp: 'db' not found in ctx — skipping KG extraction"
            )
            ctx["entity_count"] = 0
            ctx["triple_count"] = 0
            ctx["doc_entities"] = []
            ctx["doc_triples"] = []
            return ctx

        chunks: list[dict[str, Any]] = ctx.get("chunks", [])
        document_id: str = ctx["document_id"]
        space_id: str = ctx["space_id"]
        created_by: str | None = ctx.get("created_by")

        if not chunks:
            ctx["entity_count"] = 0
            ctx["triple_count"] = 0
            ctx["doc_entities"] = []
            ctx["doc_triples"] = []
            return ctx

        # ---- Step 1: parallel LLM extraction (batch of max_concurrent) ----------
        semaphore = asyncio.Semaphore(self._max_concurrent)
        tasks = [
            _extract_chunk_triples(
                chunk,
                llm_base_url=self._llm_base_url,
                llm_api_key=self._llm_api_key,
                model=self._model,
                max_triples=self._max_triples,
                semaphore=semaphore,
            )
            for chunk in chunks
        ]

        # return_exceptions=True ensures one chunk failure does not abort others
        raw_results: list[Any] = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exception results; log them
        chunk_triples_pairs: list[tuple[dict[str, Any], list[dict[str, str]]]] = []
        for result in raw_results:
            if isinstance(result, BaseException):
                logger.warning(
                    "ChunkEntityOp: unexpected error in gather result: %r", result
                )
                continue
            chunk_triples_pairs.append(result)

        # ---- Step 2: entity dedup map (per-document) ----------------------------
        entity_map = _build_entity_dedup_map(chunk_triples_pairs)

        # ---- Step 3: batch insert DocEntity records -----------------------------
        entity_orm_list: list[DocEntity] = []
        for record in entity_map.values():
            entity = DocEntity(
                canonical_name=record["canonical_name"],
                aliases=record["aliases"],
                entity_type=record["entity_type"],
                document_id=document_id,
                source_chunk_ids=record["source_chunk_ids"],
                mention_count=record["mention_count"],
                space_id=space_id,
                created_by=created_by,
            )
            db.add(entity)
            entity_orm_list.append(entity)

        # Flush so ORM assigns IDs before we link triples
        await db.flush()

        # Build canonical_name → entity.id lookup
        canonical_to_id: dict[str, str] = {
            e.canonical_name: e.id for e in entity_orm_list
        }

        # ---- Step 4: batch insert DocTriple records -----------------------------
        triple_orm_list: list[DocTriple] = []
        for chunk, triples in chunk_triples_pairs:
            chunk_id: str | None = chunk.get("db_id")

            for triple in triples:
                subj_canonical = normalize_entity_text(triple["subject"])
                obj_canonical = normalize_entity_text(triple["object"])

                subject_entity_id = canonical_to_id.get(subj_canonical)
                object_entity_id = canonical_to_id.get(obj_canonical)

                doc_triple = DocTriple(
                    subject=triple["subject"],
                    predicate=triple["predicate"],
                    object=triple["object"],
                    topic=triple.get("topic"),
                    document_id=document_id,
                    chunk_id=chunk_id,
                    confidence=1.0,
                    subject_entity_id=subject_entity_id,
                    object_entity_id=object_entity_id,
                    space_id=space_id,
                    created_by=created_by,
                )
                db.add(doc_triple)
                triple_orm_list.append(doc_triple)

        entity_count = len(entity_orm_list)
        triple_count = len(triple_orm_list)

        logger.info(
            "ChunkEntityOp: document_id=%r → %d entities, %d triples",
            document_id,
            entity_count,
            triple_count,
        )

        ctx["entity_count"] = entity_count
        ctx["triple_count"] = triple_count
        ctx["doc_entities"] = entity_orm_list
        ctx["doc_triples"] = triple_orm_list
        return ctx
