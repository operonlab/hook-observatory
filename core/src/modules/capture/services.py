"""CaptureService — CRUD + promote + completeness for the capture pipeline."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.shared.errors import BadRequestError, NotFoundError

from .models import Capture, CaptureEnrichment
from .registry import get_adapter
from .schemas import (
    BATCH_LIMIT,
    MAX_PAYLOAD_BYTES,
    CaptureCreate,
    CapturePromoteResult,
    CaptureResponse,
    CaptureStats,
    CaptureUpdate,
)

logger = logging.getLogger(__name__)


class CaptureService:
    async def create(
        self,
        db: AsyncSession,
        space_id: str,
        data: CaptureCreate,
        user_id: str | None = None,
        user_prefs: dict[str, Any] | None = None,
    ) -> Capture:
        from .registry import list_adapters
        from .schemas import CAPTURABLE_MODULES

        # Module whitelist: static set + dynamically registered adapters
        registered_modules = {m for m, _et in list_adapters()}
        allowed = CAPTURABLE_MODULES | registered_modules
        if data.module not in allowed:
            raise BadRequestError(
                f"Module '{data.module}' does not support capture. "
                f"Supported: {', '.join(sorted(allowed))}"
            )

        # Validate payload size
        payload_size = len(json.dumps(data.payload))
        if payload_size > MAX_PAYLOAD_BYTES:
            raise BadRequestError(
                f"Payload too large: {payload_size} bytes (max {MAX_PAYLOAD_BYTES})"
            )

        adapter = get_adapter(data.module, data.entity_type)
        payload = dict(data.payload)

        # Apply smart defaults if adapter exists
        if adapter:
            payload = adapter.smart_defaults(payload, user_prefs or {})
            completeness = adapter.compute_completeness(payload)
            ttl_days = adapter.default_ttl_days
        else:
            completeness = 0.0
            ttl_days = 30

        capture = Capture(
            space_id=space_id,
            created_by=user_id,
            module=data.module,
            entity_type=data.entity_type,
            payload=payload,
            raw_input=data.raw_input,
            completeness=completeness,
            status="pending",
            group_id=data.group_id,
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        )
        db.add(capture)
        await db.flush()

        try:
            await event_bus.publish(
                Event(
                    type="capture.created",
                    data={
                        "capture_id": capture.id,
                        "space_id": capture.space_id,
                        "module": capture.module,
                        "entity_type": capture.entity_type,
                        "raw_input": capture.raw_input,
                        "completeness": capture.completeness,
                    },
                    source="capture",
                    user_id=user_id,
                )
            )
        except Exception:
            logger.warning("capture.created event publish failed for id=%s", capture.id)
        return capture

    async def get(self, db: AsyncSession, capture_id: str) -> Capture | None:
        stmt = select(Capture).where(Capture.id == capture_id, Capture.deleted_at.is_(None))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        module: str | None = None,
        entity_type: str | None = None,
        status: str = "pending",
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> tuple[list[Capture], int]:
        base = select(Capture).where(
            Capture.space_id == space_id,
            Capture.deleted_at.is_(None),
        )
        if user_id:
            base = base.where(Capture.created_by == user_id)
        if module:
            base = base.where(Capture.module == module)
        if entity_type:
            base = base.where(Capture.entity_type == entity_type)
        if status:
            base = base.where(Capture.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        items_stmt = base.order_by(Capture.created_at.desc()).limit(limit).offset(offset)
        items = list((await db.execute(items_stmt)).scalars().all())
        return items, total

    async def update(
        self,
        db: AsyncSession,
        capture_id: str,
        data: CaptureUpdate,
        user_prefs: dict[str, Any] | None = None,
        agent_id: str | None = None,
        expected_version: int | None = None,
    ) -> Capture:
        capture = await self.get(db, capture_id)
        if not capture:
            raise NotFoundError("capture", capture_id)
        if capture.status != "pending":
            raise BadRequestError(f"Cannot update capture in status '{capture.status}'")

        # Optimistic locking
        if expected_version is not None and capture.version != expected_version:
            from src.shared.errors import ConflictError

            raise ConflictError(
                f"Version conflict: expected {expected_version}, current {capture.version}"
            )

        if data.payload is not None:
            old_payload = dict(capture.payload)
            merged = {**old_payload, **data.payload}
            adapter = get_adapter(capture.module, capture.entity_type)
            if adapter:
                merged = adapter.smart_defaults(merged, user_prefs or {})
                capture.completeness = adapter.compute_completeness(merged)
            capture.payload = merged

            # Record enrichment delta
            delta = {k: v for k, v in data.payload.items() if old_payload.get(k) != v}
            if delta:
                prev = {k: old_payload.get(k) for k in delta}
                enrichment = CaptureEnrichment(
                    capture_id=capture_id,
                    agent_id=agent_id or "user",
                    delta=delta,
                    previous_values=prev,
                )
                db.add(enrichment)

                try:
                    await event_bus.publish(
                        Event(
                            type="capture.enriched",
                            data={
                                "capture_id": capture_id,
                                "space_id": capture.space_id,
                                "module": capture.module,
                                "entity_type": capture.entity_type,
                                "agent_id": agent_id or "user",
                                "delta_fields": list(delta.keys()),
                                "completeness": capture.completeness,
                            },
                            source="capture",
                        )
                    )
                except Exception:
                    logger.warning("capture.enriched event publish failed for id=%s", capture_id)

        if data.raw_input is not None:
            capture.raw_input = data.raw_input

        capture.version += 1
        await db.flush()
        await db.refresh(capture)
        return capture

    async def delete(self, db: AsyncSession, capture_id: str) -> None:
        capture = await self.get(db, capture_id)
        if not capture:
            raise NotFoundError("capture", capture_id)
        capture.deleted_at = datetime.now(UTC)
        await db.flush()

    async def promote(
        self,
        db: AsyncSession,
        capture_id: str,
        user_id: str | None = None,
        user_prefs: dict[str, Any] | None = None,
    ) -> CapturePromoteResult:
        # Row-level lock to prevent concurrent promote on same capture
        stmt = (
            select(Capture)
            .where(Capture.id == capture_id, Capture.deleted_at.is_(None))
            .with_for_update()
        )
        result = await db.execute(stmt)
        capture = result.scalar_one_or_none()
        if not capture:
            raise NotFoundError("capture", capture_id)
        if capture.status != "pending":
            raise BadRequestError(f"Cannot promote capture in status '{capture.status}'")

        adapter = get_adapter(capture.module, capture.entity_type)
        if not adapter:
            raise BadRequestError(f"No adapter for {capture.module}.{capture.entity_type}")

        missing = adapter.missing_fields(capture.payload)

        # ── Enrichment pipeline (optional, runs before reference resolution) ──
        adapter_strategies = getattr(adapter, "enrichment_strategies", None)
        if adapter_strategies:
            from .strategies import DefaultsStrategy, EnrichmentPipeline

            pipeline = EnrichmentPipeline()
            pipeline.add(
                DefaultsStrategy(
                    adapter_defaults=adapter.default_values,
                    user_prefs=user_prefs or {},
                )
            )
            for strategy in adapter_strategies:
                pipeline.add(strategy)

            enrichment_result = await pipeline.run(
                capture.payload,
                module=capture.module,
                entity_type=capture.entity_type,
            )
            logger.info(
                "capture.enrich module=%s entity=%s confidence=%.2f source=%r",
                capture.module,
                capture.entity_type,
                enrichment_result.confidence,
                enrichment_result.source,
            )
            enriched_payload = enrichment_result.payload
        else:
            enriched_payload = dict(capture.payload)

        # Resolve reference fields (name → UUID, auto-create if missing)
        try:
            payload = enriched_payload
            if adapter.reference_fields:
                from .resolvers import resolve_references

                payload = await resolve_references(
                    adapter.reference_fields,
                    payload,
                    db,
                    capture.space_id,
                    user_id or capture.created_by,
                )
                # Persist resolved UUIDs back to capture payload
                updated = dict(capture.payload)
                for field in adapter.reference_fields:
                    if field in payload:
                        updated[field] = payload[field]
                capture.payload = updated

            promoted_id = await adapter.promote(
                payload,
                db,
                capture.space_id,
                user_id or capture.created_by,
            )
        except Exception:
            logger.exception("capture.promote failed id=%s", capture_id)
            return CapturePromoteResult(
                success=False,
                capture_id=capture_id,
                missing_fields=missing,
                error=f"Promotion failed for {capture.module}.{capture.entity_type}",
            )

        capture.status = "promoted"
        capture.promoted_id = promoted_id
        capture.promoted_at = datetime.now(UTC)
        await db.flush()

        try:
            await event_bus.publish(
                Event(
                    type="capture.promoted",
                    data={
                        "capture_id": capture.id,
                        "module": capture.module,
                        "entity_type": capture.entity_type,
                        "promoted_id": promoted_id,
                    },
                    source="capture",
                    user_id=user_id,
                )
            )
        except Exception:
            logger.warning("capture.promoted event publish failed for id=%s", capture.id)

        return CapturePromoteResult(
            success=True,
            capture_id=capture_id,
            promoted_id=promoted_id,
        )

    async def stats(
        self, db: AsyncSession, space_id: str, user_id: str | None = None
    ) -> CaptureStats:
        filters = [Capture.space_id == space_id, Capture.deleted_at.is_(None)]
        if user_id:
            filters.append(Capture.created_by == user_id)

        base = select(Capture).where(*filters)
        # Total
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

        # By module
        mod_stmt = select(Capture.module, func.count()).where(*filters).group_by(Capture.module)
        by_module = dict((await db.execute(mod_stmt)).all())

        # By status
        status_stmt = select(Capture.status, func.count()).where(*filters).group_by(Capture.status)
        by_status = dict((await db.execute(status_stmt)).all())

        return CaptureStats(total=total, by_module=by_module, by_status=by_status)

    def to_response(self, capture: Capture) -> CaptureResponse:
        adapter = get_adapter(capture.module, capture.entity_type)
        missing = adapter.missing_fields(capture.payload) if adapter else []
        return CaptureResponse(
            id=capture.id,
            space_id=capture.space_id,
            module=capture.module,
            entity_type=capture.entity_type,
            payload=capture.payload,
            raw_input=capture.raw_input,
            completeness=capture.completeness,
            status=capture.status,
            version=capture.version,
            group_id=capture.group_id,
            promoted_id=capture.promoted_id,
            promoted_at=capture.promoted_at,
            expires_at=capture.expires_at,
            missing_fields=missing,
            created_at=capture.created_at,
            updated_at=capture.updated_at,
        )

    async def batch_promote(
        self,
        db: AsyncSession,
        capture_ids: list[str],
        user_id: str | None = None,
    ) -> list[CapturePromoteResult]:
        if len(capture_ids) > BATCH_LIMIT:
            raise BadRequestError(f"Batch size {len(capture_ids)} exceeds limit {BATCH_LIMIT}")
        results = []
        for cid in capture_ids:
            try:
                result = await self.promote(db, cid, user_id=user_id)
                results.append(result)
            except Exception:
                logger.exception("capture.batch_promote failed id=%s", cid)
                results.append(
                    CapturePromoteResult(
                        success=False,
                        capture_id=cid,
                        error="Promotion failed",
                    )
                )
        return results

    async def search(
        self,
        db: AsyncSession,
        query: str,
        space_id: str,
        module: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
        top_k: int = 20,
        user_id: str | None = None,
    ) -> list[tuple[Capture, float]]:
        """Search captures via Qdrant hybrid search with ILIKE fallback."""
        from src.shared.qdrant_client import is_available as qdrant_available

        # --- Qdrant path ---
        try:
            if qdrant_available():
                from src.shared.qdrant_search import hybrid_search as qdrant_hybrid_search
                from src.shared.search_types import SearchConfig

                config = SearchConfig(top_k=top_k, service_ids=["capture"])
                results, _meta = await qdrant_hybrid_search(query, space_id, config)

                if results:
                    entity_ids = [r.entity_id for r in results]
                    score_map = {r.entity_id: r.score for r in results}

                    stmt = select(Capture).where(
                        Capture.id.in_(entity_ids),
                        Capture.space_id == space_id,
                        Capture.deleted_at.is_(None),
                    )
                    if user_id:
                        stmt = stmt.where(Capture.created_by == user_id)
                    if module:
                        stmt = stmt.where(Capture.module == module)
                    if entity_type:
                        stmt = stmt.where(Capture.entity_type == entity_type)
                    if status is not None:
                        stmt = stmt.where(Capture.status == status)

                    rows = (await db.execute(stmt)).scalars().all()
                    id_to_capture = {c.id: c for c in rows}
                    return [
                        (id_to_capture[eid], score_map[eid])
                        for eid in entity_ids
                        if eid in id_to_capture
                    ]

                logger.debug(
                    "Qdrant returned 0 results for capture space=%s query=%r"
                    " — falling back to ILIKE",
                    space_id,
                    query,
                )
        except Exception:
            logger.exception("Qdrant search failed, falling back to ILIKE")

        # --- ILIKE fallback (escape special characters) ---
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = select(Capture).where(
            Capture.space_id == space_id,
            Capture.raw_input.ilike(pattern),
            Capture.deleted_at.is_(None),
        )
        if user_id:
            stmt = stmt.where(Capture.created_by == user_id)
        if module:
            stmt = stmt.where(Capture.module == module)
        if entity_type:
            stmt = stmt.where(Capture.entity_type == entity_type)
        if status is not None:
            stmt = stmt.where(Capture.status == status)

        stmt = stmt.order_by(Capture.updated_at.desc()).limit(top_k)
        rows = (await db.execute(stmt)).scalars().all()
        return [(c, 1.0) for c in rows]

    async def resolve_fill_options(
        self,
        db: AsyncSession,
        module: str,
        entity_type: str,
        space_id: str,
        user_id: str | None = None,
    ) -> dict[str, list[dict[str, str]]]:
        """Resolve selectable options for adapter reference fields."""
        adapter = get_adapter(module, entity_type)
        if not adapter or not getattr(adapter, "reference_fields", None):
            return {}

        # Registry of resolver_key → (service_import_path, list_method_kwargs)
        resolvers: dict[str, tuple[str, str, dict]] = {
            "finance.wallet": ("src.modules.finance.services", "wallet_service", {}),
            "finance.category": ("src.modules.finance.services", "category_service", {}),
            "invest.account": ("src.modules.invest.services", "account_service", {}),
        }

        options: dict[str, list[dict[str, str]]] = {}
        for field, resolver_key in adapter.reference_fields.items():
            resolver = resolvers.get(resolver_key)
            if not resolver:
                logger.warning("No resolver for reference field %s -> %s", field, resolver_key)
                continue
            try:
                mod = __import__(resolver[0], fromlist=[resolver[1]])
                service = getattr(mod, resolver[1])
                result = await service.list(db, space_id, user_id=user_id)
                options[field] = [{"id": r.id, "name": r.name} for r in result.items]
            except Exception:
                logger.exception("Failed to resolve options for %s", resolver_key)
                options[field] = []
        return options

    async def get_enrichments(self, db: AsyncSession, capture_id: str) -> list[CaptureEnrichment]:
        stmt = (
            select(CaptureEnrichment)
            .where(CaptureEnrichment.capture_id == capture_id)
            .order_by(CaptureEnrichment.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def expire_stale(self, db: AsyncSession) -> int:
        """Expire captures past their TTL. Returns count of expired records."""
        now = datetime.now(UTC)
        stmt = (
            update(Capture)
            .where(
                Capture.status == "pending",
                Capture.expires_at.isnot(None),
                Capture.expires_at <= now,
                Capture.deleted_at.is_(None),
            )
            .values(status="expired")
        )
        result = await db.execute(stmt)
        return result.rowcount


capture_service = CaptureService()
