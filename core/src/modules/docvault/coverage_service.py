"""DocVault Coverage Service — gap analysis and Pipeline B orchestration.

Handles:
  1. Coverage gap detection from CRAG INCORRECT verdicts
  2. Gap analysis: suggest potential sources to fill the gap
  3. Pipeline B: gap → analysis → conditional ingest → re-answer
  4. Gap statistics and resolution tracking
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.shared.errors import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


class CoverageAnalysisService:
    """Orchestrates Pipeline B: coverage gap detection → analysis → resolution."""

    async def detect_gap(
        self,
        db: AsyncSession,
        query_text: str,
        gap_type: str = "topic_missing",
        space_id: str = "default",
    ) -> dict[str, Any]:
        """Detect and record a coverage gap from a failed QA attempt.

        Deduplicates by query_hash. If gap already exists, returns existing.
        """
        from .schemas import CoverageGapCreate
        from .services import coverage_gap_service

        query_hash = _hash_query(query_text)

        # Dedup check
        existing = await self._find_by_hash(db, query_hash, space_id)
        if existing:
            logger.debug("Coverage gap already exists: %s", query_hash[:12])
            return coverage_gap_service.to_response(existing).model_dump()

        gap_data = CoverageGapCreate(
            query_text=query_text,
            query_hash=query_hash,
            detected_at=datetime.now(UTC),
            gap_type=gap_type,
        )
        instance = await coverage_gap_service.create(db, space_id, gap_data)
        await db.commit()
        await db.refresh(instance)

        logger.info(
            "Coverage gap detected: %s (type=%s)",
            query_hash[:12], gap_type,
        )
        return coverage_gap_service.to_response(instance).model_dump()

    async def analyze_gap(
        self,
        db: AsyncSession,
        gap_id: str,
        space_id: str = "default",
    ) -> dict[str, Any]:
        """Analyze a coverage gap and suggest potential sources.

        Uses the gap's query_text to search for potential external sources.
        Updates gap status to 'investigating' and populates suggested_sources.
        """
        from .schemas import CoverageGapUpdate
        from .services import coverage_gap_service

        gap = await coverage_gap_service.get_in_space(db, gap_id, space_id)
        if not gap:
            raise NotFoundError("Coverage gap not found", code="docvault.gap_not_found")

        # Generate suggestions (stub — will use web search in Phase 5)
        suggestions = self._generate_suggestions(gap.query_text, gap.gap_type)

        # Update gap with suggestions and move to investigating
        update_data = CoverageGapUpdate(
            status="investigating",
            suggested_sources={"sources": suggestions},
        )
        await coverage_gap_service.update(
            db, gap_id, update_data, space_id=space_id
        )
        await db.commit()

        return {
            "gap_id": gap_id,
            "query_text": gap.query_text,
            "status": "investigating",
            "suggested_sources": suggestions,
        }

    async def resolve_gap(
        self,
        db: AsyncSession,
        gap_id: str,
        resolution: str,
        resolved_document_id: str | None = None,
        space_id: str = "default",
    ) -> dict[str, Any]:
        """Mark a coverage gap as resolved.

        Args:
            resolution: 'document_added' | 'not_applicable' | 'merged_existing'
        """
        from .schemas import CoverageGapUpdate
        from .services import coverage_gap_service

        gap = await coverage_gap_service.get_in_space(db, gap_id, space_id)
        if not gap:
            raise NotFoundError("Coverage gap not found", code="docvault.gap_not_found")

        update_data = CoverageGapUpdate(
            status="resolved",
            resolution=resolution,
            resolved_document_id=resolved_document_id,
        )
        await coverage_gap_service.update(
            db, gap_id, update_data, space_id=space_id
        )
        await db.commit()

        logger.info(
            "Coverage gap resolved: %s → %s (doc=%s)",
            gap_id[:8], resolution, (resolved_document_id or "N/A")[:8],
        )
        return {
            "gap_id": gap_id,
            "status": "resolved",
            "resolution": resolution,
            "resolved_document_id": resolved_document_id,
        }

    async def get_stats(
        self,
        db: AsyncSession,
        space_id: str = "default",
    ) -> dict[str, Any]:
        """Coverage gap statistics."""
        from sqlalchemy import func, select

        from .models import CoverageGap

        base = select(CoverageGap).where(
            CoverageGap.space_id == space_id,
            CoverageGap.deleted_at == None,  # noqa: E711
        )

        total = (
            await db.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        # Count by status
        status_q = (
            select(CoverageGap.status, func.count())
            .where(
                CoverageGap.space_id == space_id,
                CoverageGap.deleted_at == None,  # noqa: E711
            )
            .group_by(CoverageGap.status)
        )
        status_rows = (await db.execute(status_q)).all()
        by_status = {row[0]: row[1] for row in status_rows}

        # Count by gap_type
        type_q = (
            select(CoverageGap.gap_type, func.count())
            .where(
                CoverageGap.space_id == space_id,
                CoverageGap.deleted_at == None,  # noqa: E711
            )
            .group_by(CoverageGap.gap_type)
        )
        type_rows = (await db.execute(type_q)).all()
        by_type = {row[0]: row[1] for row in type_rows}

        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "resolution_rate": (
                round(by_status.get("resolved", 0) / total, 3) if total else 0.0
            ),
        }

    def _generate_suggestions(
        self, query_text: str, gap_type: str
    ) -> list[dict[str, str]]:
        """Generate source suggestions for a coverage gap.

        Stub implementation — Phase 5 will add web search + LLM analysis.
        """
        suggestions = []

        if gap_type == "topic_missing":
            suggestions.append({
                "type": "web_search",
                "query": query_text,
                "confidence": "low",
                "note": "No documents cover this topic. Consider uploading relevant materials.",
            })
        elif gap_type == "depth_insufficient":
            suggestions.append({
                "type": "expand_existing",
                "query": query_text,
                "confidence": "medium",
                "note": "Existing documents mention this topic but lack depth.",
            })
        elif gap_type == "outdated":
            suggestions.append({
                "type": "update_existing",
                "query": query_text,
                "confidence": "medium",
                "note": "Document content may be outdated. Consider uploading newer version.",
            })

        return suggestions

    async def _find_by_hash(
        self,
        db: AsyncSession,
        query_hash: str,
        space_id: str,
    ) -> Any | None:
        """Find existing gap by query hash (dedup)."""
        from sqlalchemy import select

        from .models import CoverageGap

        stmt = select(CoverageGap).where(
            CoverageGap.query_hash == query_hash,
            CoverageGap.space_id == space_id,
            CoverageGap.deleted_at == None,  # noqa: E711
        )
        return (await db.execute(stmt)).scalar_one_or_none()


# Module singleton
coverage_analysis_service = CoverageAnalysisService()
