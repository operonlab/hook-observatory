"""Memvault Knowledge Lint — automated knowledge graph health checking.

13 composable checks across 4 layers:
  L0: contradictions, stale, orphan_entities, dangling_refs, community_anomalies, data_gaps
  L1: predicate_contradictions, temporal_staleness, attitude_chain_integrity, entity_alias_collision
  L3: grounding (action-grounded validation)
  L4: semantic_contradictions (LLM judgment)
  Pipeline: knowledge_conflicts (L1+L3+L4 → cross-validate → cascade)

Cannibalized from 3 converging sources:
- GBrain (Garry Tan) — Knowledge Maintenance/Lint
- Karpathy LLM Wiki — Lint operation
- Harness Engineering — Memory Governance UNVERIFIED→VERIFIED
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .kg_models import Community, EntityCanonical, Triple

logger = logging.getLogger(__name__)

# ======================== Data Structures ========================


@dataclass
class LintFinding:
    check: str  # contradictions | stale | orphan_entities | dangling_refs | ...

    severity: str  # info | warning | error
    entity_id: str
    entity_type: str  # triple | entity | community | system
    message: str
    suggested_action: str  # invalidate | delete | resolve | backfill | none
    metadata: dict = field(default_factory=dict)


@dataclass
class LintReport:
    space_id: str
    checks_run: list[str]
    findings: list[LintFinding]
    summary: dict[str, int]
    run_duration_ms: float
    run_at: datetime


@dataclass
class CandidateConflict:
    """Stage 1 output: a suspected conflict from any detection layer."""

    detection_layer: int  # 1-4
    check_name: str
    entity_type: str  # "triple" | "block" | "attitude"
    entity_id_a: str
    entity_id_b: str | None
    source_session_a: str | None
    source_session_b: str | None
    description: str
    raw_confidence: float
    metadata: dict = field(default_factory=dict)


@dataclass
class ConfirmedConflict:
    """Stage 2 output: cross-validated conflict ready for remediation."""

    candidate: CandidateConflict
    cross_validation_score: float
    evidence: list[str]
    stale_id: str
    fresh_id: str | None
    cascade_targets: list[str] = field(default_factory=list)


# ======================== Check Functions ========================


async def check_contradictions(
    db: AsyncSession,
    space_id: str,
    *,
    sample_size: int = 100,
    similarity_threshold: float = 0.80,
) -> list[LintFinding]:
    """Find valid triples that contradict each other via Qdrant semantic search."""
    from src.shared.embedding import get_embedding
    from src.shared.qdrant_client import is_available as qdrant_available
    from src.shared.qdrant_search import vector_search
    from src.shared.search_types import SearchConfig

    if not await qdrant_available():
        return [
            LintFinding(
                check="contradictions",
                severity="warning",
                entity_id="",
                entity_type="system",
                message="Qdrant unavailable — contradiction check skipped",
                suggested_action="none",
            )
        ]

    # Sample recent valid triples
    q = (
        select(Triple)
        .where(Triple.space_id == space_id, Triple.invalid_at.is_(None))
        .order_by(Triple.created_at.desc())
        .limit(sample_size)
    )
    triples = (await db.execute(q)).scalars().all()
    findings: list[LintFinding] = []
    seen_pairs: set[tuple[str, str]] = set()

    for triple in triples:
        embedding_text = f"{triple.subject} {triple.predicate} {triple.object}"
        embedding = await get_embedding(embedding_text)
        if embedding is None:
            continue

        config = SearchConfig(
            top_k=10,
            score_threshold=similarity_threshold,
            service_ids=["memvault-triple"],
        )
        results = await vector_search(embedding, space_id, config)
        if not results:
            continue

        candidate_ids = [r.entity_id for r in results]
        cq = select(Triple).where(
            Triple.id.in_(candidate_ids),
            Triple.id != triple.id,
            Triple.invalid_at.is_(None),
            Triple.subject == triple.subject,
            Triple.predicate == triple.predicate,
        )
        candidates = (await db.execute(cq)).scalars().all()
        for c in candidates:
            if c.object.strip().lower() == triple.object.strip().lower():
                continue
            pair = tuple(sorted([triple.id, c.id]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            findings.append(
                LintFinding(
                    check="contradictions",
                    severity="warning",
                    entity_id=triple.id,
                    entity_type="triple",
                    message=(
                        f'"{triple.subject} {triple.predicate}" has contradicting objects: '
                        f'"{triple.object}" vs "{c.object}"'
                    ),
                    suggested_action="resolve",
                    metadata={"triple_a": triple.id, "triple_b": c.id},
                )
            )

    return findings


async def check_stale_triples(
    db: AsyncSession,
    space_id: str,
    *,
    days_threshold: int = 90,
    access_threshold: int = 2,
) -> list[LintFinding]:
    """Find valid triples not accessed for a long time with low access count."""
    cutoff = datetime.now(UTC) - timedelta(days=days_threshold)
    q = select(Triple).where(
        Triple.space_id == space_id,
        Triple.invalid_at.is_(None),
        Triple.access_count < access_threshold,
        (
            (Triple.last_accessed_at < cutoff)
            | (Triple.last_accessed_at.is_(None) & (Triple.created_at < cutoff))
        ),
    )
    triples = (await db.execute(q)).scalars().all()
    return [
        LintFinding(
            check="stale",
            severity="info",
            entity_id=t.id,
            entity_type="triple",
            message=(
                f'"{t.subject} {t.predicate} {t.object[:50]}" '
                f"last accessed {t.last_accessed_at or 'never'}, count={t.access_count}"
            ),
            suggested_action="invalidate",
            metadata={
                "last_accessed_at": str(t.last_accessed_at),
                "access_count": t.access_count,
                "created_at": str(t.created_at),
            },
        )
        for t in triples
    ]


async def check_orphan_entities(
    db: AsyncSession,
    space_id: str,
) -> list[LintFinding]:
    """Find entities with zero active triples pointing to them."""
    # Subquery: entity IDs referenced by at least one valid triple
    subj_ids = (
        select(Triple.canonical_subject_id)
        .where(Triple.space_id == space_id, Triple.invalid_at.is_(None))
        .distinct()
    )
    obj_ids = (
        select(Triple.canonical_object_id)
        .where(Triple.space_id == space_id, Triple.invalid_at.is_(None))
        .distinct()
    )
    q = select(EntityCanonical).where(
        EntityCanonical.space_id == space_id,
        EntityCanonical.deleted_at.is_(None),
        EntityCanonical.id.notin_(subj_ids),
        EntityCanonical.id.notin_(obj_ids),
    )
    orphans = (await db.execute(q)).scalars().all()
    return [
        LintFinding(
            check="orphan_entities",
            severity="info",
            entity_id=e.id,
            entity_type="entity",
            message=f'Entity "{e.canonical_name}" ({e.entity_type}) has no active triples',
            suggested_action="delete",
            metadata={"merge_count": e.merge_count},
        )
        for e in orphans
    ]


async def check_dangling_refs(
    db: AsyncSession,
    space_id: str,
) -> list[LintFinding]:
    """Find valid triples missing canonical entity links."""
    q = select(Triple).where(
        Triple.space_id == space_id,
        Triple.invalid_at.is_(None),
        (Triple.canonical_subject_id.is_(None) | Triple.canonical_object_id.is_(None)),
    )
    triples = (await db.execute(q)).scalars().all()
    return [
        LintFinding(
            check="dangling_refs",
            severity="warning",
            entity_id=t.id,
            entity_type="triple",
            message=(
                f'"{t.subject} {t.predicate} {t.object[:50]}" missing canonical link '
                f"(subject={'✗' if not t.canonical_subject_id else '✓'}, "
                f"object={'✗' if not t.canonical_object_id else '✓'})"
            ),
            suggested_action="resolve",
        )
        for t in triples
    ]


async def check_community_anomalies(
    db: AsyncSession,
    space_id: str,
) -> list[LintFinding]:
    """Find communities with abnormal size or low modularity."""
    q = select(Community).where(Community.space_id == space_id)
    communities = (await db.execute(q)).scalars().all()
    if len(communities) < 3:
        return []

    sizes = [c.size for c in communities]
    mean_size = statistics.mean(sizes)
    stdev_size = statistics.stdev(sizes) if len(sizes) > 1 else 0
    threshold = mean_size + 2 * stdev_size if stdev_size > 0 else mean_size * 3

    findings: list[LintFinding] = []
    for c in communities:
        issues = []
        if c.size > threshold:
            issues.append(f"size {c.size} > threshold {threshold:.0f}")
        if c.modularity_score is not None and c.modularity_score < 0.1:
            issues.append(f"modularity {c.modularity_score:.3f} < 0.1")
        if issues:
            findings.append(
                LintFinding(
                    check="community_anomalies",
                    severity="info",
                    entity_id=c.id,
                    entity_type="community",
                    message=f'Community "{c.name}" (L{c.resolution_level}): {", ".join(issues)}',
                    suggested_action="none",
                    metadata={
                        "size": c.size,
                        "modularity_score": c.modularity_score,
                        "resolution_level": c.resolution_level,
                    },
                )
            )
    return findings


async def check_data_gaps(
    db: AsyncSession,
    space_id: str,
    *,
    min_merge_count: int = 2,
    max_triples: int = 3,
) -> list[LintFinding]:
    """Find entities that are frequently referenced but have few triples."""
    # Count active triples per entity (as subject or object)
    subj_count = (
        select(
            Triple.canonical_subject_id.label("eid"),
            func.count(Triple.id).label("cnt"),
        )
        .where(Triple.space_id == space_id, Triple.invalid_at.is_(None))
        .group_by(Triple.canonical_subject_id)
        .subquery()
    )
    obj_count = (
        select(
            Triple.canonical_object_id.label("eid"),
            func.count(Triple.id).label("cnt"),
        )
        .where(Triple.space_id == space_id, Triple.invalid_at.is_(None))
        .group_by(Triple.canonical_object_id)
        .subquery()
    )

    q = select(EntityCanonical).where(
        EntityCanonical.space_id == space_id,
        EntityCanonical.merge_count >= min_merge_count,
    )
    entities = (await db.execute(q)).scalars().all()

    # Get triple counts per entity
    eid_to_count: dict[str, int] = {}
    for sub in [subj_count, obj_count]:
        rows = (await db.execute(select(sub.c.eid, sub.c.cnt))).all()
        for eid, cnt in rows:
            if eid:
                eid_to_count[eid] = eid_to_count.get(eid, 0) + cnt

    findings: list[LintFinding] = []
    for e in entities:
        triple_count = eid_to_count.get(e.id, 0)
        if triple_count <= max_triples:
            findings.append(
                LintFinding(
                    check="data_gaps",
                    severity="info",
                    entity_id=e.id,
                    entity_type="entity",
                    message=(
                        f'Entity "{e.canonical_name}" has {triple_count} triples '
                        f"but merge_count={e.merge_count} (frequently referenced)"
                    ),
                    suggested_action="backfill",
                    metadata={
                        "triple_count": triple_count,
                        "merge_count": e.merge_count,
                    },
                )
            )
    return findings


# ======================== Semantic Contradiction Check ========================


async def check_semantic_contradictions(
    db: AsyncSession,
    space_id: str,
    *,
    sample_size: int = 50,
    similarity_threshold: float = 0.70,
    max_llm_calls: int = 20,
    verbose: bool = False,
) -> list[LintFinding]:
    """Find semantically related blocks with contradictory or evolved claims via LLM.

    Unlike check_contradictions() which requires exact subject+predicate match,
    this check uses pure embedding similarity (no structural constraint) and
    LLM judgment to detect belief evolution and semantic contradictions.
    """
    from pydantic_ai import Agent as PydanticAgent

    from src.shared.embedding import get_embedding
    from src.shared.qdrant_client import is_available as qdrant_available
    from src.shared.qdrant_search import vector_search
    from src.shared.search_types import SearchConfig

    from .llm_models import SemanticLintOutput
    from .models import MemoryBlock

    if not await qdrant_available():
        return [
            LintFinding(
                check="semantic_contradictions",
                severity="warning",
                entity_id="",
                entity_type="system",
                message="Qdrant unavailable — semantic contradiction check skipped",
                suggested_action="none",
            )
        ]

    # Mixed sampling: half recent + half oldest — ensures cross-era comparison
    half = sample_size // 2
    base_where = [
        MemoryBlock.space_id == space_id,
        MemoryBlock.deleted_at.is_(None),
        MemoryBlock.invalid_at.is_(None),
        MemoryBlock.block_type.in_(["knowledge", "attitude"]),
    ]

    q_recent = (
        select(MemoryBlock).where(*base_where).order_by(MemoryBlock.created_at.desc()).limit(half)
    )
    q_oldest = (
        select(MemoryBlock).where(*base_where).order_by(MemoryBlock.created_at.asc()).limit(half)
    )
    recent = (await db.execute(q_recent)).scalars().all()
    oldest = (await db.execute(q_oldest)).scalars().all()

    # Merge and deduplicate (oldest blocks might overlap with recent in small datasets)
    seen_ids: set[str] = set()
    blocks: list[MemoryBlock] = []
    for b in recent + oldest:
        if b.id not in seen_ids:
            seen_ids.add(b.id)
            blocks.append(b)

    # Fall back to all types if not enough knowledge/attitude blocks
    if len(blocks) < 10:
        q_all = (
            select(MemoryBlock)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.deleted_at.is_(None),
                MemoryBlock.invalid_at.is_(None),
            )
            .order_by(MemoryBlock.created_at.desc())
            .limit(sample_size)
        )
        blocks = (await db.execute(q_all)).scalars().all()

    if not blocks:
        logger.info("semantic_lint: no valid blocks found for space=%s", space_id)
        return []

    logger.info("semantic_lint: sampled %d blocks for space=%s", len(blocks), space_id)

    # Build block lookup for later
    block_map: dict[str, MemoryBlock] = {b.id: b for b in blocks}

    # Collect candidate pairs via embedding search
    seen_pairs: set[tuple[str, str]] = set()
    candidate_pairs: list[tuple[MemoryBlock, MemoryBlock, float]] = []

    for block in blocks:
        if len(candidate_pairs) >= max_llm_calls:
            break

        content = (block.content or "").strip()
        if len(content) < 20:
            continue

        embedding = await get_embedding(content)
        if embedding is None:
            continue

        config = SearchConfig(
            top_k=5,
            score_threshold=similarity_threshold,
            service_ids=["memvault"],
        )
        results = await vector_search(embedding, space_id, config)

        for r in results:
            if r.entity_id == block.id:
                continue
            pair = tuple(sorted([block.id, r.entity_id]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Look up the other block
            other = block_map.get(r.entity_id)
            if other is None:
                # Not in our sample — fetch from DB
                oq = select(MemoryBlock).where(
                    MemoryBlock.id == r.entity_id,
                    MemoryBlock.deleted_at.is_(None),
                    MemoryBlock.invalid_at.is_(None),
                )
                other = (await db.execute(oq)).scalar_one_or_none()
            if other is None:
                continue

            # Skip pairs from the same source session (not evolution, just co-extracted)
            if (
                block.source_session
                and other.source_session
                and block.source_session == other.source_session
            ):
                continue

            candidate_pairs.append((block, other, r.score))
            if len(candidate_pairs) >= max_llm_calls:
                break

    findings: list[LintFinding] = []

    if not candidate_pairs:
        return findings

    # LLM agent for semantic judgment
    _lint_agent = PydanticAgent(
        output_type=SemanticLintOutput,
        system_prompt=(
            "You are a knowledge graph auditor. Compare two memory blocks from the same "
            "personal knowledge base and classify their relationship.\n\n"
            "Decisions:\n"
            '- "contradiction": The blocks make directly conflicting claims about the same topic.\n'
            '- "evolution": The user\'s belief or situation has changed over time. '
            "The newer block supersedes the older one.\n"
            '- "compatible": The blocks are related but not contradictory — different aspects, '
            "contexts, or complementary information.\n\n"
            "Consider timestamps: a newer block about the same topic likely reflects "
            "the user's current state.\n"
            "Set stale_id to the ID of the outdated block (for evolution/contradiction), "
            "or null if compatible.\n"
            "Be conservative — only flag contradiction/evolution when clearly warranted."
        ),
        retries=1,
    )

    # Resolve model with batch-friendly fallback to avoid rate limits
    from .llm_config import make_litellm_model, resolve_model

    batch_candidates = [
        "kimi-k2.5",
        "deepseek-v3",
        "qwen3.5-flash",
        "grok-4.1-fast",
        "gemini-3.1-flash",
    ]
    model_name = await resolve_model(candidates=batch_candidates)
    model = make_litellm_model(model_name)

    for block_a, block_b, score in candidate_pairs:
        # Determine which is older/newer
        if block_a.created_at and block_b.created_at:
            older = block_a if block_a.created_at < block_b.created_at else block_b
            newer = block_b if block_a.created_at < block_b.created_at else block_a
        else:
            older, newer = block_a, block_b

        user_message = (
            f"OLDER block (ID: {older.id}, type: {older.block_type}, "
            f"created: {older.created_at}):\n{(older.content or '')[:500]}\n\n"
            f"NEWER block (ID: {newer.id}, type: {newer.block_type}, "
            f"created: {newer.created_at}):\n{(newer.content or '')[:500]}\n\n"
            f"Semantic similarity: {score:.3f}\n"
            "Classify the relationship and explain briefly."
        )

        # Rate-limit protection: retry once after backoff on 429
        import asyncio as _asyncio

        output = None
        for attempt in range(2):
            try:
                result = await _lint_agent.run(
                    user_message,
                    model=model,
                    model_settings={"temperature": 0.1, "max_tokens": 256, "timeout": 15},
                )
                output = result.output
                break
            except Exception as exc:
                if attempt == 0 and "429" in str(exc):
                    await _asyncio.sleep(3)
                    continue
                logger.debug(
                    "semantic_lint: LLM failed for pair (%s, %s): %s",
                    block_a.id,
                    block_b.id,
                    exc,
                )
                break

        if output is None:
            continue

        # Pace requests to avoid rate limits
        await _asyncio.sleep(1)

        logger.info(
            "semantic_lint: pair (%s, %s) → %s (confidence=%.2f)",
            block_a.id[:8],
            block_b.id[:8],
            output.relationship,
            output.confidence,
        )

        if output.relationship == "compatible":
            if verbose:
                findings.append(
                    LintFinding(
                        check="semantic_contradictions",
                        severity="info",
                        entity_id=block_a.id,
                        entity_type="block",
                        message=(
                            f"Compatible (confidence={output.confidence:.2f}): {output.reason}"
                        ),
                        suggested_action="none",
                        metadata={
                            "relationship": "compatible",
                            "block_a": block_a.id,
                            "block_b": block_b.id,
                            "similarity": round(score, 3),
                            "content_a": (block_a.content or "")[:100],
                            "content_b": (block_b.content or "")[:100],
                        },
                    )
                )
            continue

        if output.relationship == "evolution":
            stale_id = output.stale_id or older.id
            fresh_id = newer.id if stale_id == older.id else older.id
            findings.append(
                LintFinding(
                    check="semantic_contradictions",
                    severity="warning",
                    entity_id=stale_id,
                    entity_type="block",
                    message=(
                        f"Belief evolution detected (confidence={output.confidence:.2f}): "
                        f"{output.reason}"
                    ),
                    suggested_action="invalidate",
                    metadata={
                        "relationship": "evolution",
                        "stale_id": stale_id,
                        "fresh_id": fresh_id,
                        "similarity": round(score, 3),
                        "confidence": output.confidence,
                    },
                )
            )
        elif output.relationship == "contradiction":
            findings.append(
                LintFinding(
                    check="semantic_contradictions",
                    severity="warning",
                    entity_id=block_a.id,
                    entity_type="block",
                    message=(
                        f"Semantic contradiction (confidence={output.confidence:.2f}): "
                        f"{output.reason}"
                    ),
                    suggested_action="resolve",
                    metadata={
                        "relationship": "contradiction",
                        "block_a": block_a.id,
                        "block_b": block_b.id,
                        "similarity": round(score, 3),
                        "confidence": output.confidence,
                    },
                )
            )

    return findings


# ======================== Layer 1: Graph Structure Checks ========================

# Predicates whose values change over time (volatile state claims)
VOLATILE_PREDICATES = frozenset(
    {
        "pattern_is",
        "flow_is",
        "implemented_as",
        "configured_with",
        "default_is",
        "format_is",
        "chosen_over",
    }
)

# Predicate pairs that are structurally contradictory
# (pred_a, pred_b, mode): "same_pair" = same (S,O), "reverse_pair" = (S,O) vs (O,S)
PREDICATE_CONTRADICTION_RULES: list[tuple[str, str, str]] = [
    ("should", "should_NOT", "same_pair"),
    ("enables", "prevents", "same_pair"),
    ("improves", "degrades", "same_pair"),
    ("fixes", "causes", "same_pair"),
    ("chosen_over", "chosen_over", "reverse_pair"),
]


async def check_predicate_contradictions(
    db: AsyncSession,
    space_id: str,
) -> list[LintFinding]:
    """Find valid triples with structurally contradictory predicates for the same entity pair."""
    from sqlalchemy.orm import aliased

    findings: list[LintFinding] = []
    t1 = aliased(Triple)
    t2 = aliased(Triple)

    for pred_a, pred_b, mode in PREDICATE_CONTRADICTION_RULES:
        if mode == "same_pair":
            q = select(t1, t2).where(
                t1.space_id == space_id,
                t2.space_id == space_id,
                t1.invalid_at.is_(None),
                t2.invalid_at.is_(None),
                t1.canonical_subject_id.isnot(None),
                t2.canonical_subject_id.isnot(None),
                t1.canonical_subject_id == t2.canonical_subject_id,
                t1.canonical_object_id == t2.canonical_object_id,
                t1.id < t2.id,
                t1.predicate == pred_a,
                t2.predicate == pred_b,
            )
        else:  # reverse_pair
            q = select(t1, t2).where(
                t1.space_id == space_id,
                t2.space_id == space_id,
                t1.invalid_at.is_(None),
                t2.invalid_at.is_(None),
                t1.canonical_subject_id.isnot(None),
                t2.canonical_subject_id.isnot(None),
                t1.canonical_subject_id == t2.canonical_object_id,
                t1.canonical_object_id == t2.canonical_subject_id,
                t1.id < t2.id,
                t1.predicate == pred_a,
                t2.predicate == pred_b,
            )

        rows = (await db.execute(q)).all()
        for row in rows:
            a, b = row[0], row[1]
            findings.append(
                LintFinding(
                    check="predicate_contradictions",
                    severity="error",
                    entity_id=a.id,
                    entity_type="triple",
                    message=(
                        f'Predicate contradiction: "{a.subject} {a.predicate} {a.object}" '
                        f'vs "{b.subject} {b.predicate} {b.object}" ({mode})'
                    ),
                    suggested_action="resolve",
                    metadata={
                        "triple_a": a.id,
                        "triple_b": b.id,
                        "rule": f"{pred_a} vs {pred_b} ({mode})",
                        "created_a": str(a.created_at),
                        "created_b": str(b.created_at),
                    },
                )
            )

    return findings


async def check_temporal_staleness(
    db: AsyncSession,
    space_id: str,
    *,
    days_threshold: int = 30,
) -> list[LintFinding]:
    """Find same-entity triples with volatile predicates that diverge across time periods."""
    from itertools import groupby as itertools_groupby

    q = (
        select(Triple)
        .where(
            Triple.space_id == space_id,
            Triple.invalid_at.is_(None),
            Triple.canonical_subject_id.isnot(None),
            Triple.predicate.in_(VOLATILE_PREDICATES),
        )
        .order_by(Triple.canonical_subject_id, Triple.predicate, Triple.created_at.desc())
    )
    triples = (await db.execute(q)).scalars().all()

    findings: list[LintFinding] = []
    for _key, group in itertools_groupby(
        triples, key=lambda t: (t.canonical_subject_id, t.predicate)
    ):
        group_list = list(group)
        if len(group_list) < 2:
            continue

        newest = group_list[0]
        newest_ts = newest.valid_at or newest.created_at
        if not newest_ts:
            continue

        for older in group_list[1:]:
            older_ts = older.valid_at or older.created_at
            if not older_ts:
                continue
            # Same object → not a conflict, just duplicate
            if older.object and newest.object and older.object.strip() == newest.object.strip():
                continue
            age = abs((newest_ts - older_ts).days)
            if age >= days_threshold:
                findings.append(
                    LintFinding(
                        check="temporal_staleness",
                        severity="warning",
                        entity_id=older.id,
                        entity_type="triple",
                        message=(
                            f"Temporal drift ({age}d): "
                            f'"{older.subject} {older.predicate}" '
                            f'old="{(older.object or "")[:50]}" '
                            f'vs new="{(newest.object or "")[:50]}"'
                        ),
                        suggested_action="invalidate",
                        metadata={
                            "stale_id": older.id,
                            "fresh_id": newest.id,
                            "age_days": age,
                            "predicate": older.predicate,
                        },
                    )
                )

    return findings


async def check_attitude_chain_integrity(
    db: AsyncSession,
    space_id: str,
) -> list[LintFinding]:
    """Check AttitudeFact supersession chains for cycles, broken links, and duplicates."""
    from sqlalchemy.orm import aliased as sa_aliased

    from .kg_models import AttitudeFact

    findings: list[LintFinding] = []

    # 3a: Circular references (direct cycle: A.superseded_by = B AND B.superseded_by = A)
    a1 = sa_aliased(AttitudeFact)
    a2 = sa_aliased(AttitudeFact)
    q_cycle = select(a1.id, a2.id).where(
        a1.space_id == space_id,
        a2.space_id == space_id,
        a1.superseded_by == a2.id,
        a2.superseded_by == a1.id,
        a1.id < a2.id,
    )
    cycles = (await db.execute(q_cycle)).all()
    for row in cycles:
        findings.append(
            LintFinding(
                check="attitude_chain_integrity",
                severity="error",
                entity_id=row[0],
                entity_type="attitude",
                message=f"Circular supersession: {row[0][:12]}.. ↔ {row[1][:12]}..",
                suggested_action="resolve",
                metadata={"attitude_a": row[0], "attitude_b": row[1], "issue": "circular"},
            )
        )

    # 3b: Broken chains (superseded_by points to non-existent ID)
    q_broken = (
        select(AttitudeFact.id, AttitudeFact.superseded_by)
        .outerjoin(
            a2,
            AttitudeFact.superseded_by == a2.id,
        )
        .where(
            AttitudeFact.space_id == space_id,
            AttitudeFact.superseded_by.isnot(None),
            a2.id.is_(None),
        )
    )
    broken = (await db.execute(q_broken)).all()
    for row in broken:
        findings.append(
            LintFinding(
                check="attitude_chain_integrity",
                severity="warning",
                entity_id=row[0],
                entity_type="attitude",
                message=f"Broken chain: superseded_by={row[1][:12]}.. does not exist",
                suggested_action="resolve",
                metadata={"attitude_id": row[0], "dangling_ref": row[1], "issue": "broken_chain"},
            )
        )

    # 3c: Duplicate current attitudes (same category, high word overlap, both superseded_by=NULL)
    q_current = select(AttitudeFact).where(
        AttitudeFact.space_id == space_id,
        AttitudeFact.superseded_by.is_(None),
        AttitudeFact.deleted_at.is_(None),
    )
    current = (await db.execute(q_current)).scalars().all()

    by_category: dict[str, list] = {}
    for att in current:
        by_category.setdefault(att.category, []).append(att)

    for _cat, atts in by_category.items():
        if len(atts) < 2:
            continue
        for i, a in enumerate(atts):
            words_a = set((a.fact or "").lower().split())
            for b in atts[i + 1 :]:
                words_b = set((b.fact or "").lower().split())
                union = words_a | words_b
                if not union:
                    continue
                jaccard = len(words_a & words_b) / len(union)
                if jaccard > 0.6:
                    findings.append(
                        LintFinding(
                            check="attitude_chain_integrity",
                            severity="info",
                            entity_id=a.id,
                            entity_type="attitude",
                            message=(
                                f"Duplicate current attitudes (jaccard={jaccard:.2f}): "
                                f'"{(a.fact or "")[:60]}" vs "{(b.fact or "")[:60]}"'
                            ),
                            suggested_action="resolve",
                            metadata={
                                "attitude_a": a.id,
                                "attitude_b": b.id,
                                "jaccard": round(jaccard, 3),
                                "issue": "duplicate_current",
                            },
                        )
                    )

    return findings


async def check_entity_alias_collision(
    db: AsyncSession,
    space_id: str,
) -> list[LintFinding]:
    """Find entity pairs that likely represent the same real-world entity."""
    findings: list[LintFinding] = []
    max_findings = 50  # cap to avoid explosion

    # 4a: Alias array overlap (uses GIN index)
    q_overlap = select(EntityCanonical).where(
        EntityCanonical.space_id == space_id,
        EntityCanonical.deleted_at.is_(None),
    )
    entities = (await db.execute(q_overlap)).scalars().all()

    # Build name→id index for dedup (skip pairs with identical canonical_name)
    name_to_ids: dict[str, list[str]] = {}
    for e in entities:
        name_to_ids.setdefault(e.canonical_name.lower(), []).append(e.id)

    # Build alias → entity mapping (exclude very short aliases)
    alias_map: dict[str, list[str]] = {}
    for e in entities:
        if e.aliases:
            for alias in e.aliases:
                a_lower = alias.lower()
                if len(a_lower) >= 4:  # skip short aliases
                    alias_map.setdefault(a_lower, []).append(e.id)

    seen_collision: set[tuple[str, str]] = set()
    entity_by_id = {e.id: e for e in entities}

    for _alias, eids in alias_map.items():
        if len(eids) < 2 or len(findings) >= max_findings:
            continue
        for i, eid_a in enumerate(eids):
            if len(findings) >= max_findings:
                break
            for eid_b in eids[i + 1 :]:
                pair = tuple(sorted([eid_a, eid_b]))
                if pair in seen_collision:
                    continue
                seen_collision.add(pair)
                ea = entity_by_id.get(eid_a)
                eb = entity_by_id.get(eid_b)
                if not ea or not eb:
                    continue
                # Skip same-name entities (that's entity resolution, not lint)
                if ea.canonical_name.lower() == eb.canonical_name.lower():
                    continue
                findings.append(
                    LintFinding(
                        check="entity_alias_collision",
                        severity="warning",
                        entity_id=eid_a,
                        entity_type="entity",
                        message=(
                            f'Alias collision: "{ea.canonical_name}" and '
                            f'"{eb.canonical_name}" share alias "{_alias}"'
                        ),
                        suggested_action="resolve",
                        metadata={
                            "entity_a": eid_a,
                            "entity_b": eid_b,
                            "shared_alias": _alias,
                        },
                    )
                )

    # 4b: Canonical name substring containment (same entity_type, cap at max_findings)
    for i, e1 in enumerate(entities):
        if len(findings) >= max_findings:
            break
        n1 = e1.canonical_name.lower()
        if len(n1) < 6:
            continue
        for e2 in entities[i + 1 :]:
            n2 = e2.canonical_name.lower()
            if len(n2) < 6:
                continue
            if e1.entity_type != e2.entity_type:
                continue
            pair = tuple(sorted([e1.id, e2.id]))
            if pair in seen_collision:
                continue
            if n1 in n2 or n2 in n1:
                seen_collision.add(pair)
                findings.append(
                    LintFinding(
                        check="entity_alias_collision",
                        severity="info",
                        entity_id=e1.id,
                        entity_type="entity",
                        message=(
                            f'Name containment: "{e1.canonical_name}" ⊂ "{e2.canonical_name}" '
                            f"(type={e1.entity_type})"
                        ),
                        suggested_action="resolve",
                        metadata={
                            "entity_a": e1.id,
                            "entity_b": e2.id,
                            "detection": "name_containment",
                        },
                    )
                )

    return findings


# ======================== Attitude Dedup Check ========================


async def check_attitude_dedup(
    db: AsyncSession,
    space_id: str,
    *,
    similarity_threshold: float = 0.90,
    max_findings: int = 50,
) -> list[LintFinding]:
    """Find duplicate current attitudes within the same category.

    Uses Qdrant embedding similarity + Jaccard word overlap cross-validation.
    This is a DEDUP check (same content, multiple copies), not a conflict check.
    """
    from .kg_models import AttitudeFact

    findings: list[LintFinding] = []

    q = select(AttitudeFact).where(
        AttitudeFact.space_id == space_id,
        AttitudeFact.superseded_by.is_(None),
        AttitudeFact.deleted_at.is_(None),
    )
    attitudes = (await db.execute(q)).scalars().all()

    if len(attitudes) < 2:
        return findings

    # Group by category — only check within same category
    by_category: dict[str, list] = {}
    for a in attitudes:
        by_category.setdefault(a.category, []).append(a)

    seen_pairs: set[tuple[str, str]] = set()

    for _cat, atts in by_category.items():
        if len(atts) < 2 or len(findings) >= max_findings:
            continue

        for i, a in enumerate(atts):
            if len(findings) >= max_findings:
                break
            fact_a = (a.fact or "").strip().lower()
            words_a = set(fact_a.split())

            for b in atts[i + 1 :]:
                pair = tuple(sorted([a.id, b.id]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                fact_b = (b.fact or "").strip().lower()

                # Exact text match
                if fact_a == fact_b:
                    findings.append(
                        LintFinding(
                            check="attitude_dedup",
                            severity="error",
                            entity_id=a.id,
                            entity_type="attitude",
                            message=(f'Exact duplicate in [{a.category}]: "{(a.fact or "")[:60]}"'),
                            suggested_action="delete",
                            metadata={
                                "attitude_a": a.id,
                                "attitude_b": b.id,
                                "similarity": 1.0,
                                "detection": "exact_text",
                            },
                        )
                    )
                    continue

                # Jaccard word overlap
                words_b = set(fact_b.split())
                union = words_a | words_b
                if not union:
                    continue
                jaccard = len(words_a & words_b) / len(union)
                if jaccard >= 0.85:
                    findings.append(
                        LintFinding(
                            check="attitude_dedup",
                            severity="warning",
                            entity_id=a.id,
                            entity_type="attitude",
                            message=(
                                f"Near-duplicate in [{a.category}] "
                                f"(jaccard={jaccard:.2f}): "
                                f'"{(a.fact or "")[:50]}" vs '
                                f'"{(b.fact or "")[:50]}"'
                            ),
                            suggested_action="delete",
                            metadata={
                                "attitude_a": a.id,
                                "attitude_b": b.id,
                                "jaccard": round(jaccard, 3),
                                "detection": "jaccard_overlap",
                            },
                        )
                    )

    return findings


# ======================== Attitude Conflict Checks ========================


async def check_attitude_semantic_contradictions(
    db: AsyncSession,
    space_id: str,
    *,
    max_llm_calls: int = 10,
) -> list[LintFinding]:
    """Find semantically contradictory attitudes within the same category.

    Uses _is_attitude_contradiction() heuristic as fast filter,
    then LLM judgment for candidates that pass.
    This is a CONFLICT check (different claims on same topic), not dedup.
    """
    from .kg_models import AttitudeFact
    from .kg_services import _is_attitude_contradiction

    findings: list[LintFinding] = []

    q = select(AttitudeFact).where(
        AttitudeFact.space_id == space_id,
        AttitudeFact.superseded_by.is_(None),
        AttitudeFact.deleted_at.is_(None),
    )
    attitudes = (await db.execute(q)).scalars().all()

    if len(attitudes) < 2:
        return findings

    # Group by category
    by_category: dict[str, list] = {}
    for a in attitudes:
        by_category.setdefault(a.category, []).append(a)

    # Heuristic pass: find pairs with contradiction signals
    candidates: list[tuple] = []  # (att_a, att_b)
    seen_pairs: set[tuple[str, str]] = set()

    for _cat, atts in by_category.items():
        if len(atts) < 2:
            continue
        for i, a in enumerate(atts):
            for b in atts[i + 1 :]:
                pair = tuple(sorted([a.id, b.id]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                if _is_attitude_contradiction(a.fact or "", b.fact or ""):
                    candidates.append((a, b))
                    if len(candidates) >= max_llm_calls * 2:
                        break
            if len(candidates) >= max_llm_calls * 2:
                break

    if not candidates:
        return findings

    # LLM pass for top candidates
    from pydantic_ai import Agent as PydanticAgent

    from .llm_config import make_litellm_model, resolve_model
    from .llm_models import SemanticLintOutput

    batch_candidates = [
        "kimi-k2.5",
        "deepseek-v3",
        "qwen3.5-flash",
        "grok-4.1-fast",
        "gemini-3.1-flash",
    ]
    model_name = await resolve_model(candidates=batch_candidates)
    model = make_litellm_model(model_name)

    _agent = PydanticAgent(
        output_type=SemanticLintOutput,
        system_prompt=(
            "You are a belief auditor. Compare two attitude/preference statements "
            "from the same personal knowledge base and classify their relationship.\n\n"
            'Decisions:\n- "contradiction": Directly conflicting beliefs.\n'
            '- "evolution": The user\'s preference changed over time.\n'
            '- "compatible": Different aspects, not contradictory.\n\n'
            "Set stale_id to the outdated statement's ID, or null if compatible."
        ),
        retries=1,
    )

    import asyncio as _asyncio

    llm_calls = 0
    for att_a, att_b in candidates:
        if llm_calls >= max_llm_calls:
            break

        # Determine older/newer
        if att_a.created_at and att_b.created_at:
            older = att_a if att_a.created_at < att_b.created_at else att_b
            newer = att_b if att_a.created_at < att_b.created_at else att_a
        else:
            older, newer = att_a, att_b

        user_msg = (
            f"OLDER attitude (ID: {older.id}, category: {older.category}, "
            f"created: {older.created_at}):\n{(older.fact or '')[:300]}\n\n"
            f"NEWER attitude (ID: {newer.id}, category: {newer.category}, "
            f"created: {newer.created_at}):\n{(newer.fact or '')[:300]}\n\n"
            "Classify the relationship."
        )

        output = None
        for attempt in range(2):
            try:
                result = await _agent.run(
                    user_msg,
                    model=model,
                    model_settings={
                        "temperature": 0.1,
                        "max_tokens": 256,
                        "timeout": 15,
                    },
                )
                output = result.output
                break
            except Exception as exc:
                if attempt == 0 and "429" in str(exc):
                    await _asyncio.sleep(3)
                    continue
                logger.debug(
                    "attitude_semantic: LLM failed for (%s, %s): %s",
                    att_a.id,
                    att_b.id,
                    exc,
                )
                break

        llm_calls += 1
        if output is None:
            continue
        await _asyncio.sleep(1)

        if output.relationship == "compatible":
            continue

        stale_id = output.stale_id or older.id
        fresh_id = newer.id if stale_id == older.id else older.id

        findings.append(
            LintFinding(
                check="attitude_semantic_contradictions",
                severity="warning",
                entity_id=stale_id,
                entity_type="attitude",
                message=(
                    f"Attitude {output.relationship} in [{att_a.category}] "
                    f"(confidence={output.confidence:.2f}): {output.reason}"
                ),
                suggested_action="invalidate",
                metadata={
                    "relationship": output.relationship,
                    "stale_id": stale_id,
                    "fresh_id": fresh_id,
                    "attitude_a": att_a.id,
                    "attitude_b": att_b.id,
                    "confidence": output.confidence,
                },
            )
        )

    return findings


async def check_attitude_temporal_staleness(
    db: AsyncSession,
    space_id: str,
    *,
    days_threshold: int = 90,
) -> list[LintFinding]:
    """Find same-category attitudes that diverge across long time periods.

    If the oldest and newest current attitudes in the same category are
    90+ days apart and semantically different, the oldest is a drift candidate.
    """
    from .kg_models import AttitudeFact

    findings: list[LintFinding] = []

    q = (
        select(AttitudeFact)
        .where(
            AttitudeFact.space_id == space_id,
            AttitudeFact.superseded_by.is_(None),
            AttitudeFact.deleted_at.is_(None),
        )
        .order_by(AttitudeFact.category, AttitudeFact.created_at.desc())
    )
    attitudes = (await db.execute(q)).scalars().all()

    # Group by category
    by_category: dict[str, list] = {}
    for a in attitudes:
        by_category.setdefault(a.category, []).append(a)

    for _cat, atts in by_category.items():
        if len(atts) < 2:
            continue

        newest = atts[0]  # ordered desc
        newest_ts = newest.created_at
        if not newest_ts:
            continue

        for older in atts[1:]:
            older_ts = older.created_at
            if not older_ts:
                continue

            age = abs((newest_ts - older_ts).days)
            if age < days_threshold:
                continue

            # Check content difference (not just age)
            words_new = set((newest.fact or "").lower().split())
            words_old = set((older.fact or "").lower().split())
            union = words_new | words_old
            if not union:
                continue
            jaccard = len(words_new & words_old) / len(union)

            # Same content = not a conflict, just old
            if jaccard > 0.8:
                continue

            findings.append(
                LintFinding(
                    check="attitude_temporal_staleness",
                    severity="info",
                    entity_id=older.id,
                    entity_type="attitude",
                    message=(
                        f"Attitude drift ({age}d) in [{older.category}]: "
                        f'old="{(older.fact or "")[:50]}" '
                        f'vs new="{(newest.fact or "")[:50]}"'
                    ),
                    suggested_action="invalidate",
                    metadata={
                        "stale_id": older.id,
                        "fresh_id": newest.id,
                        "age_days": age,
                        "jaccard": round(jaccard, 3),
                        "category": older.category,
                    },
                )
            )

    return findings


# ======================== Layer 3: Action-Grounded Validation ========================


async def check_grounding(
    db: AsyncSession,
    space_id: str,
) -> list[LintFinding]:
    """Validate knowledge claims against actual system state (ports, modules, names)."""
    from .ground_truth import (
        build_ground_truth,
        check_deprecated_reference,
        check_module_count_claim,
        check_port_claim,
        is_groundable,
    )

    truth = build_ground_truth()
    findings: list[LintFinding] = []

    # Query triples with groundable predicates
    q = (
        select(Triple)
        .where(
            Triple.space_id == space_id,
            Triple.invalid_at.is_(None),
        )
        .limit(1000)
    )
    triples = (await db.execute(q)).scalars().all()

    for t in triples:
        text = f"{t.subject} {t.predicate} {t.object}"

        # Check deprecated names in ANY triple
        dep = check_deprecated_reference(text, truth)
        if dep:
            findings.append(
                LintFinding(
                    check="grounding",
                    severity="error",
                    entity_id=t.id,
                    entity_type="triple",
                    message=f'Deprecated reference "{dep}" in: {text[:80]}',
                    suggested_action="invalidate",
                    metadata={
                        "grounding_category": "deprecated",
                        "deprecated_name": dep,
                    },
                )
            )
            continue

        # Only check groundable predicates for port/module drift
        if not is_groundable(t.predicate):
            continue

        # Port drift
        port_drift = check_port_claim(text, truth)
        if port_drift:
            claimed, actual = port_drift
            findings.append(
                LintFinding(
                    check="grounding",
                    severity="error",
                    entity_id=t.id,
                    entity_type="triple",
                    message=(
                        f"Port drift: claimed {claimed}, actual {actual} (from port_registry)"
                    ),
                    suggested_action="invalidate",
                    metadata={
                        "grounding_category": "port",
                        "claimed": str(claimed),
                        "actual": str(actual),
                    },
                )
            )

        # Module count drift
        count_drift = check_module_count_claim(text, truth)
        if count_drift:
            claimed, actual = count_drift
            findings.append(
                LintFinding(
                    check="grounding",
                    severity="warning",
                    entity_id=t.id,
                    entity_type="triple",
                    message=(f"Module count drift: claimed {claimed}, actual {actual}"),
                    suggested_action="invalidate",
                    metadata={
                        "grounding_category": "module_count",
                        "claimed": str(claimed),
                        "actual": str(actual),
                    },
                )
            )

    # --- Attitude facts: check deprecated references ---
    from .kg_models import AttitudeFact

    aq = (
        select(AttitudeFact)
        .where(
            AttitudeFact.space_id == space_id,
            AttitudeFact.superseded_by.is_(None),
            AttitudeFact.deleted_at.is_(None),
        )
        .limit(500)
    )
    att_facts = (await db.execute(aq)).scalars().all()

    for a in att_facts:
        fact_text = a.fact or ""
        dep = check_deprecated_reference(fact_text, truth)
        if dep:
            findings.append(
                LintFinding(
                    check="grounding",
                    severity="warning",
                    entity_id=a.id,
                    entity_type="attitude",
                    message=(
                        f'Deprecated reference "{dep}" in attitude [{a.category}]: {fact_text[:80]}'
                    ),
                    suggested_action="invalidate",
                    metadata={
                        "grounding_category": "deprecated",
                        "deprecated_name": dep,
                    },
                )
            )

    return findings


# ======================== Knowledge Conflict Pipeline ========================


def _finding_to_candidate(finding: LintFinding, detection_layer: int) -> CandidateConflict | None:
    """Convert a LintFinding into a CandidateConflict."""
    meta = finding.metadata
    check = finding.check

    if check == "predicate_contradictions":
        eid_a = meta.get("triple_a", finding.entity_id)
        eid_b = meta.get("triple_b")
        confidence = 0.9
    elif check == "temporal_staleness":
        eid_a = meta.get("stale_id", finding.entity_id)
        eid_b = meta.get("fresh_id")
        confidence = 0.7
    elif check == "attitude_chain_integrity":
        eid_a = meta.get("attitude_a", finding.entity_id)
        eid_b = meta.get("attitude_b")
        confidence = 0.9 if meta.get("issue") == "circular" else 0.6
    elif check == "grounding":
        eid_a = finding.entity_id
        eid_b = None
        confidence = 1.0
    elif check == "semantic_contradictions":
        rel = meta.get("relationship")
        if rel == "evolution":
            eid_a = meta.get("stale_id", finding.entity_id)
            eid_b = meta.get("fresh_id")
        elif rel == "contradiction":
            eid_a = meta.get("block_a", finding.entity_id)
            eid_b = meta.get("block_b")
        else:
            return None
        confidence = meta.get("confidence", 0.6)
    elif check == "attitude_semantic_contradictions":
        eid_a = meta.get("stale_id", meta.get("attitude_a", finding.entity_id))
        eid_b = meta.get("fresh_id", meta.get("attitude_b"))
        confidence = meta.get("confidence", 0.7)
    elif check == "attitude_temporal_staleness":
        eid_a = meta.get("stale_id", finding.entity_id)
        eid_b = meta.get("fresh_id")
        confidence = 0.6
    else:
        return None

    if not eid_a:
        return None

    return CandidateConflict(
        detection_layer=detection_layer,
        check_name=check,
        entity_type=finding.entity_type,
        entity_id_a=eid_a,
        entity_id_b=eid_b,
        source_session_a=None,
        source_session_b=None,
        description=finding.message,
        raw_confidence=confidence,
        metadata=meta,
    )


async def _cross_validate(
    db: AsyncSession,
    space_id: str,
    candidates: list[CandidateConflict],
) -> list[ConfirmedConflict]:
    """Stage 2: Cross-validate candidates via pincer approach (上下夾擊).

    Triple candidate → trace DOWN to source blocks (via source_session).
    Block candidate → trace UP to derived triples (via source_session).
    Grounding candidate → skip validation (confidence=1.0).
    Gate: cross_validation_score >= 0.6.
    """
    from .models import MemoryBlock

    if not candidates:
        return []

    # --- Batch-fetch source_sessions for all referenced entities ---
    triple_ids: set[str] = set()
    block_ids: set[str] = set()
    for c in candidates:
        if c.entity_type == "triple":
            triple_ids.add(c.entity_id_a)
            if c.entity_id_b:
                triple_ids.add(c.entity_id_b)
        elif c.entity_type == "block":
            block_ids.add(c.entity_id_a)
            if c.entity_id_b:
                block_ids.add(c.entity_id_b)

    triple_sessions: dict[str, str | None] = {}
    if triple_ids:
        q = select(Triple.id, Triple.source_session).where(Triple.id.in_(triple_ids))
        triple_sessions = {r[0]: r[1] for r in (await db.execute(q)).all()}

    block_sessions: dict[str, str | None] = {}
    if block_ids:
        q = select(MemoryBlock.id, MemoryBlock.source_session).where(MemoryBlock.id.in_(block_ids))
        block_sessions = {r[0]: r[1] for r in (await db.execute(q)).all()}

    # Populate source_sessions on candidates
    for c in candidates:
        if c.entity_type == "triple":
            c.source_session_a = triple_sessions.get(c.entity_id_a)
            if c.entity_id_b:
                c.source_session_b = triple_sessions.get(c.entity_id_b)
        elif c.entity_type == "block":
            c.source_session_a = block_sessions.get(c.entity_id_a)
            if c.entity_id_b:
                c.source_session_b = block_sessions.get(c.entity_id_b)

    # --- Batch-fetch session cross-references ---
    all_sessions: set[str] = set()
    for c in candidates:
        if c.source_session_a:
            all_sessions.add(c.source_session_a)
        if c.source_session_b:
            all_sessions.add(c.source_session_b)

    session_block_ids: dict[str, set[str]] = {}
    session_triple_ids: dict[str, set[str]] = {}
    if all_sessions:
        bq = select(MemoryBlock.id, MemoryBlock.source_session).where(
            MemoryBlock.space_id == space_id,
            MemoryBlock.source_session.in_(all_sessions),
            MemoryBlock.deleted_at.is_(None),
        )
        for bid, sess in (await db.execute(bq)).all():
            session_block_ids.setdefault(sess, set()).add(bid)

        tq = select(Triple.id, Triple.source_session).where(
            Triple.space_id == space_id,
            Triple.source_session.in_(all_sessions),
            Triple.invalid_at.is_(None),
        )
        for tid, sess in (await db.execute(tq)).all():
            session_triple_ids.setdefault(sess, set()).add(tid)

    # Build L1/L4 cross-reference sets
    l1_triple_ids: set[str] = set()
    l4_block_ids: set[str] = set()
    for c in candidates:
        if c.detection_layer == 1 and c.entity_type == "triple":
            l1_triple_ids.add(c.entity_id_a)
            if c.entity_id_b:
                l1_triple_ids.add(c.entity_id_b)
        elif c.detection_layer == 4 and c.entity_type == "block":
            l4_block_ids.add(c.entity_id_a)
            if c.entity_id_b:
                l4_block_ids.add(c.entity_id_b)

    # --- Score each candidate ---
    confirmed: list[ConfirmedConflict] = []
    for c in candidates:
        evidence: list[str] = []
        score = c.raw_confidence
        stale_id = c.entity_id_a
        fresh_id = c.entity_id_b

        if c.detection_layer == 3:
            # Grounding = absolute truth, skip validation
            score = 1.0
            evidence.append("Ground truth verified (system state)")
            fresh_id = None

        elif c.entity_type == "triple":
            # Triple → trace DOWN to source blocks
            sess = c.source_session_a
            if sess:
                b_ids = session_block_ids.get(sess, set())
                if b_ids:
                    evidence.append(f"Source session has {len(b_ids)} blocks")
                    score += 0.1
                    flagged = b_ids & l4_block_ids
                    if flagged:
                        score += 0.2
                        evidence.append(f"{len(flagged)} source blocks also flagged by L4")
            stale_id = c.metadata.get("stale_id", c.entity_id_a)
            fresh_id = c.metadata.get("fresh_id", c.entity_id_b)

        elif c.entity_type == "block":
            # Block → trace UP to derived triples
            sess = c.source_session_a
            if sess:
                t_ids = session_triple_ids.get(sess, set())
                if t_ids:
                    evidence.append(f"Session has {len(t_ids)} active triples")
                    flagged = t_ids & l1_triple_ids
                    if flagged:
                        score += 0.2
                        evidence.append(f"{len(flagged)} derived triples flagged by L1")
            stale_id = c.metadata.get("stale_id", c.entity_id_a)
            fresh_id = c.metadata.get("fresh_id", c.entity_id_b)

        elif c.entity_type == "attitude":
            evidence.append(f"Attitude chain issue: {c.metadata.get('issue', 'unknown')}")

        score = min(score, 1.0)
        if score < 0.6:
            continue

        confirmed.append(
            ConfirmedConflict(
                candidate=c,
                cross_validation_score=round(score, 3),
                evidence=evidence,
                stale_id=stale_id,
                fresh_id=fresh_id,
            )
        )

    return confirmed


async def check_knowledge_conflicts(
    db: AsyncSession,
    space_id: str,
    *,
    max_llm_calls: int = 20,
) -> list[LintFinding]:
    """Unified knowledge conflict pipeline (Stage 1 + Stage 2).

    Stage 1: Integrate L1 (graph) + L3 (grounding) + L4 (semantic LLM) candidates.
    Stage 2: Cross-validate via pincer approach (上下夾擊).
    Returns confirmed conflicts as LintFindings with enriched metadata.
    """
    candidates: list[CandidateConflict] = []
    seen_pairs: set[tuple[str, str]] = set()

    def _dedup_add(results: list[LintFinding], layer: int) -> None:
        for f in results:
            c = _finding_to_candidate(f, detection_layer=layer)
            if c is None:
                continue
            pair = tuple(sorted([c.entity_id_a, c.entity_id_b or ""]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            candidates.append(c)

    # L1: Graph structure (~200ms, deterministic)
    for check_fn in [
        check_predicate_contradictions,
        check_temporal_staleness,
        check_attitude_chain_integrity,
        check_attitude_temporal_staleness,
    ]:
        try:
            _dedup_add(await check_fn(db, space_id), layer=1)
        except Exception as exc:
            logger.warning("knowledge_conflicts L1 %s: %s", check_fn.__name__, exc)

    # L3: Grounding (~15ms, deterministic — triples + attitudes)
    try:
        _dedup_add(await check_grounding(db, space_id), layer=3)
    except Exception as exc:
        logger.warning("knowledge_conflicts L3: %s", exc)

    # L4: Semantic LLM (slow, ≤max_llm_calls — blocks + attitudes)
    half_llm = max(max_llm_calls // 2, 5)
    try:
        _dedup_add(
            await check_semantic_contradictions(db, space_id, max_llm_calls=half_llm),
            layer=4,
        )
    except Exception as exc:
        logger.warning("knowledge_conflicts L4 blocks: %s", exc)

    try:
        _dedup_add(
            await check_attitude_semantic_contradictions(db, space_id, max_llm_calls=half_llm),
            layer=4,
        )
    except Exception as exc:
        logger.warning("knowledge_conflicts L4 attitudes: %s", exc)

    logger.info("knowledge_conflicts: %d candidates from L1+L3+L4", len(candidates))

    # Stage 2: Cross-validate
    confirmed = await _cross_validate(db, space_id, candidates)
    logger.info(
        "knowledge_conflicts: %d/%d confirmed",
        len(confirmed),
        len(candidates),
    )

    # Convert to LintFindings with enriched metadata
    return [
        LintFinding(
            check="knowledge_conflicts",
            severity="error" if c.cross_validation_score >= 0.8 else "warning",
            entity_id=c.stale_id,
            entity_type=c.candidate.entity_type,
            message=(
                f"[L{c.candidate.detection_layer}/{c.candidate.check_name}] "
                f"{c.candidate.description}"
            ),
            suggested_action="invalidate",
            metadata={
                "detection_layer": c.candidate.detection_layer,
                "original_check": c.candidate.check_name,
                "cross_validation_score": c.cross_validation_score,
                "evidence": c.evidence,
                "stale_id": c.stale_id,
                "fresh_id": c.fresh_id,
                "entity_id_a": c.candidate.entity_id_a,
                "entity_id_b": c.candidate.entity_id_b,
                "source_session_a": c.candidate.source_session_a,
                "source_session_b": c.candidate.source_session_b,
            },
        )
        for c in confirmed
    ]


# ======================== Runner ========================

ALL_CHECKS: dict[str, object] = {
    # Original checks
    "contradictions": check_contradictions,
    "semantic_contradictions": check_semantic_contradictions,
    "stale": check_stale_triples,
    "orphan_entities": check_orphan_entities,
    "dangling_refs": check_dangling_refs,
    "community_anomalies": check_community_anomalies,
    "data_gaps": check_data_gaps,
    # Layer 1: Graph structure (deterministic, fast)
    "predicate_contradictions": check_predicate_contradictions,
    "temporal_staleness": check_temporal_staleness,
    "attitude_chain_integrity": check_attitude_chain_integrity,
    "entity_alias_collision": check_entity_alias_collision,
    # Layer 3: Action-grounded validation
    "grounding": check_grounding,
    # Dedup checks (same content, multiple copies)
    "attitude_dedup": check_attitude_dedup,
    # Attitude conflict checks (different claims on same topic)
    "attitude_semantic_contradictions": check_attitude_semantic_contradictions,
    "attitude_temporal_staleness": check_attitude_temporal_staleness,
    # Unified pipeline: L1+L3+L4 → cross-validate → cascade
    "knowledge_conflicts": check_knowledge_conflicts,
}

FAST_CHECKS = [
    "stale",
    "orphan_entities",
    "dangling_refs",
    "data_gaps",
    "predicate_contradictions",
    "temporal_staleness",
    "attitude_chain_integrity",
    "entity_alias_collision",
    "attitude_dedup",
    "attitude_temporal_staleness",
]


async def run_lint(
    db: AsyncSession,
    space_id: str = "default",
    checks: list[str] | None = None,
) -> LintReport:
    """Run knowledge lint checks. If checks is None, run all."""
    selected = checks or list(ALL_CHECKS.keys())
    findings: list[LintFinding] = []
    start = time.monotonic()

    for name in selected:
        check_fn = ALL_CHECKS.get(name)
        if check_fn is None:
            continue
        try:
            results = await check_fn(db, space_id)
            findings.extend(results)
        except Exception as e:
            findings.append(
                LintFinding(
                    check=name,
                    severity="error",
                    entity_id="",
                    entity_type="system",
                    message=f"Check failed: {e}",
                    suggested_action="none",
                )
            )

    elapsed = (time.monotonic() - start) * 1000
    summary: dict[str, int] = {}
    for f in findings:
        summary[f.check] = summary.get(f.check, 0) + 1

    return LintReport(
        space_id=space_id,
        checks_run=selected,
        findings=findings,
        summary=summary,
        run_duration_ms=elapsed,
        run_at=datetime.now(UTC),
    )


# ======================== Remediation ========================


async def remediate_stale(
    db: AsyncSession,
    findings: list[LintFinding],
    *,
    dry_run: bool = True,
) -> int:
    """Invalidate stale triples. dry_run=True by default (report only)."""
    count = 0
    for f in findings:
        if f.check != "stale" or not f.entity_id:
            continue
        if dry_run:
            continue
        await db.execute(
            update(Triple)
            .where(Triple.id == f.entity_id)
            .values(invalid_at=datetime.now(UTC), invalidation_reason="stale")
        )
        count += 1
    if count > 0:
        await db.commit()
    return count


async def remediate_orphans(
    db: AsyncSession,
    findings: list[LintFinding],
    *,
    dry_run: bool = True,
) -> int:
    """Delete orphan entities. dry_run=True by default (report only)."""
    count = 0
    for f in findings:
        if f.check != "orphan_entities" or not f.entity_id:
            continue
        if dry_run:
            continue
        await db.execute(delete(EntityCanonical).where(EntityCanonical.id == f.entity_id))
        count += 1
    if count > 0:
        await db.commit()
    return count


async def remediate_semantic(
    db: AsyncSession,
    findings: list[LintFinding],
    *,
    dry_run: bool = True,
) -> int:
    """Remediate semantic contradiction findings. dry_run=True by default.

    - evolution: invalidate the stale block (reason="evolved")
    - contradiction: use conflict_resolver for MERGE/SUPERSEDE/COEXIST
    """
    from .models import MemoryBlock

    count = 0
    for f in findings:
        if f.check != "semantic_contradictions" or not f.entity_id:
            continue
        if dry_run:
            continue

        meta = f.metadata
        relationship = meta.get("relationship")

        if relationship == "evolution":
            stale_id = meta.get("stale_id")
            fresh_id = meta.get("fresh_id")
            if not stale_id:
                continue
            await db.execute(
                update(MemoryBlock)
                .where(MemoryBlock.id == stale_id, MemoryBlock.invalid_at.is_(None))
                .values(
                    invalid_at=datetime.now(UTC),
                    superseded_by=fresh_id,
                    invalidation_reason="evolved",
                )
            )
            count += 1

        elif relationship == "contradiction":
            block_a_id = meta.get("block_a")
            block_b_id = meta.get("block_b")
            if not block_a_id or not block_b_id:
                continue

            # Fetch both blocks for conflict resolution
            qa = select(MemoryBlock).where(MemoryBlock.id == block_a_id)
            qb = select(MemoryBlock).where(MemoryBlock.id == block_b_id)
            block_a = (await db.execute(qa)).scalar_one_or_none()
            block_b = (await db.execute(qb)).scalar_one_or_none()
            if not block_a or not block_b:
                continue

            # Determine older/newer for conflict resolution
            if block_a.created_at and block_b.created_at:
                if block_a.created_at < block_b.created_at:
                    existing, newer = block_a, block_b
                else:
                    existing, newer = block_b, block_a
            else:
                existing, newer = block_a, block_b

            try:
                from .conflict_resolver import resolve_conflict

                result = await resolve_conflict(
                    new_content=newer.content or "",
                    existing_content=existing.content or "",
                    existing_block_id=existing.id,
                    block_type=existing.block_type or "knowledge",
                    similarity=meta.get("similarity", 0.0),
                    existing_created_at=str(existing.created_at) if existing.created_at else None,
                )
            except Exception as exc:
                logger.debug(
                    "remediate_semantic: conflict resolution failed for %s: %s", existing.id, exc
                )
                continue

            from src.shared.conflict import ConflictDecision

            if result.decision == ConflictDecision.SUPERSEDE:
                await db.execute(
                    update(MemoryBlock)
                    .where(MemoryBlock.id == existing.id, MemoryBlock.invalid_at.is_(None))
                    .values(
                        invalid_at=datetime.now(UTC),
                        superseded_by=newer.id,
                        invalidation_reason="contradiction",
                    )
                )
                count += 1
            elif result.decision == ConflictDecision.MERGE and result.merged_content:
                # Update newer block with merged content, invalidate older
                await db.execute(
                    update(MemoryBlock)
                    .where(MemoryBlock.id == newer.id)
                    .values(content=result.merged_content)
                )
                await db.execute(
                    update(MemoryBlock)
                    .where(MemoryBlock.id == existing.id, MemoryBlock.invalid_at.is_(None))
                    .values(
                        invalid_at=datetime.now(UTC),
                        superseded_by=newer.id,
                        invalidation_reason="merged",
                    )
                )
                count += 1
            # COEXIST → no action

    if count > 0:
        await db.commit()
    return count


async def remediate_knowledge_conflicts(
    db: AsyncSession,
    findings: list[LintFinding],
    *,
    dry_run: bool = True,
) -> int:
    """Stage 3: Cascade invalidation for confirmed knowledge conflicts.

    Block stale → cascade to same-session triples (content overlap >= 3 words).
    Triple stale → invalidate triple only (conservative: don't touch source block).
    One db.commit() at the end.
    """
    from .models import MemoryBlock

    count = 0
    now = datetime.now(UTC)

    for f in findings:
        if f.check != "knowledge_conflicts" or not f.entity_id:
            continue
        if dry_run:
            continue

        meta = f.metadata
        stale_id = meta.get("stale_id")
        fresh_id = meta.get("fresh_id")
        source_session = meta.get("source_session_a")

        if not stale_id:
            continue

        reason = meta.get("original_check", "knowledge_conflict")

        if f.entity_type == "triple":
            await db.execute(
                update(Triple)
                .where(Triple.id == stale_id, Triple.invalid_at.is_(None))
                .values(
                    invalid_at=now,
                    invalidated_by=fresh_id,
                    invalidation_reason=reason,
                )
            )
            count += 1

        elif f.entity_type == "block":
            await db.execute(
                update(MemoryBlock)
                .where(MemoryBlock.id == stale_id, MemoryBlock.invalid_at.is_(None))
                .values(
                    invalid_at=now,
                    superseded_by=fresh_id,
                    invalidation_reason=reason,
                )
            )
            count += 1

            # Cascade DOWN: invalidate same-session triples with content overlap
            if source_session:
                bq = select(MemoryBlock.content).where(MemoryBlock.id == stale_id)
                block_content = (await db.execute(bq)).scalar_one_or_none()
                if block_content:
                    block_words = set(block_content.lower().split())
                    tq = select(Triple).where(
                        Triple.source_session == source_session,
                        Triple.invalid_at.is_(None),
                    )
                    for t in (await db.execute(tq)).scalars().all():
                        t_words = set(f"{t.subject} {t.predicate} {t.object}".lower().split())
                        if len(block_words & t_words) >= 3:
                            await db.execute(
                                update(Triple)
                                .where(
                                    Triple.id == t.id,
                                    Triple.invalid_at.is_(None),
                                )
                                .values(
                                    invalid_at=now,
                                    invalidation_reason="cascade_from_block",
                                )
                            )
                            count += 1

    if count > 0:
        await db.commit()
    return count


async def remediate_attitude_conflicts(
    db: AsyncSession,
    findings: list[LintFinding],
    *,
    dry_run: bool = True,
) -> int:
    """Remediate attitude semantic contradiction and temporal staleness findings.

    evolution/temporal → set invalid_at + invalidation_reason on stale attitude.
    contradiction → use conflict_resolver for LLM judgment.
    dry_run=True by default.
    """
    from .kg_models import AttitudeFact

    count = 0
    now = datetime.now(UTC)
    valid_checks = {"attitude_semantic_contradictions", "attitude_temporal_staleness"}

    for f in findings:
        if f.check not in valid_checks or not f.entity_id:
            continue
        if dry_run:
            continue

        meta = f.metadata
        stale_id = meta.get("stale_id")

        if not stale_id:
            continue

        reason = f.check.replace(
            "attitude_", ""
        )  # "semantic_contradictions" or "temporal_staleness"

        await db.execute(
            update(AttitudeFact)
            .where(
                AttitudeFact.id == stale_id,
                AttitudeFact.invalid_at.is_(None),
            )
            .values(
                invalid_at=now,
                invalidation_reason=reason,
            )
        )
        count += 1

    if count > 0:
        await db.commit()
    return count
