"""Memvault Knowledge Lint — automated knowledge graph health checking.

Six composable checks:
1. contradictions — triples with same subject+predicate but different object
2. stale — triples not accessed for N days with low access count
3. orphan_entities — entities with zero active triples
4. dangling_refs — triples missing canonical entity links
5. community_anomalies — communities with abnormal size or low modularity
6. data_gaps — frequently referenced entities with very few triples

Cannibalized from 3 converging sources:
- GBrain (Garry Tan) — Knowledge Maintenance/Lint
- Karpathy LLM Wiki — Lint operation
- Harness Engineering — Memory Governance UNVERIFIED→VERIFIED
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .kg_models import Community, EntityCanonical, Triple

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
        return []

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


# ======================== Runner ========================

ALL_CHECKS: dict[str, object] = {
    "contradictions": check_contradictions,
    "stale": check_stale_triples,
    "orphan_entities": check_orphan_entities,
    "dangling_refs": check_dangling_refs,
    "community_anomalies": check_community_anomalies,
    "data_gaps": check_data_gaps,
}

FAST_CHECKS = ["stale", "orphan_entities", "dangling_refs", "data_gaps"]


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
        if not dry_run:
            await db.execute(
                update(Triple)
                .where(Triple.id == f.entity_id)
                .values(invalid_at=datetime.now(UTC), invalidation_reason="stale")
            )
        count += 1
    if not dry_run and count > 0:
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
        if not dry_run:
            await db.execute(
                delete(EntityCanonical).where(EntityCanonical.id == f.entity_id)
            )
        count += 1
    if not dry_run and count > 0:
        await db.commit()
    return count
