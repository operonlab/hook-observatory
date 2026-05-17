"""Intelflow text search — ILIKE-based search for standalone service.

Standalone variant:
- No Qdrant (semantic/hybrid search removed)
- No cross-encoder reranking
- No tier-config / warm-cold tiered search
- Simple CJK-aware ILIKE search with basic scoring
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Report
from .schemas import ReportBrief, TextSearchResult

logger = logging.getLogger(__name__)


def _tokenize_cjk(query: str) -> list[str]:
    """Simple CJK-aware tokenization: split on whitespace, then extract
    CJK character bigrams for queries containing CJK characters."""
    tokens = query.strip().split()
    result = []
    for token in tokens:
        # Check if token contains CJK characters
        cjk_chars = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", token)
        if cjk_chars and len(cjk_chars) >= 2:
            # Bigram extraction for CJK
            for i in range(len(cjk_chars) - 1):
                result.append(cjk_chars[i] + cjk_chars[i + 1])
            # Also add full token
            result.append(token)
        else:
            result.append(token)
    return [t for t in result if t]


def _score_match(query: str, text: str) -> float:
    """Simple BM25-lite scoring: count token matches / total tokens."""
    tokens = _tokenize_cjk(query.lower())
    if not tokens:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for t in tokens if t in text_lower)
    return hits / len(tokens)


async def text_search(
    db: AsyncSession,
    space_id: str,
    query: str,
    limit: int = 10,
) -> list[TextSearchResult]:
    """Simple ILIKE text search across report title and content.

    Tokenizes query (CJK-aware), builds OR conditions for each token,
    then scores results by match proportion.
    """
    tokens = _tokenize_cjk(query)
    if not tokens:
        return []

    # Build ILIKE conditions (OR — any token matches)
    conditions = []
    for token in tokens[:10]:  # Cap at 10 tokens to prevent huge queries
        pattern = f"%{token}%"
        conditions.append(Report.title.ilike(pattern))
        conditions.append(Report.content.ilike(pattern))

    from sqlalchemy import or_

    q = (
        select(Report)
        .where(
            Report.space_id == space_id,
            Report.deleted_at == None,  # noqa: E711
            or_(*conditions),
        )
        .order_by(Report.updated_at.desc())
        .limit(limit * 2)  # Fetch extra for scoring/filtering
    )

    rows = (await db.execute(q)).scalars().all()

    # Score and sort
    scored = []
    for r in rows:
        score = _score_match(query, f"{r.title} {r.content[:2000]}")
        if score > 0:
            scored.append(
                TextSearchResult(
                    report=_to_brief(r),
                    score=round(score, 4),
                )
            )

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:limit]


def _to_brief(report: Report) -> ReportBrief:
    """Convert ORM Report to lightweight ReportBrief."""
    return ReportBrief(
        id=report.id,
        title=report.title,
        query=report.query,
        tags=report.tags or [],
        skill_name=report.skill_name,
        created_at=report.created_at,
    )
