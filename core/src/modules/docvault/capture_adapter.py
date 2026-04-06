"""DocVault capture adapter — document upload via capture pipeline."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.capture.adapters import BaseCaptureAdapter

from .schemas import DocumentCreate


class DocumentCaptureAdapter(BaseCaptureAdapter):
    module = "docvault"
    entity_type = "document"
    default_ttl_days = 90
    enrichment_adapter_type = "docvault"

    field_weights = {
        "title": 20,
        "content": 40,
        "source_type": 10,
        "tags": 15,
        "source_uri": 15,
    }

    default_values = {
        "source_type": "markdown",
        "tags": [],
    }

    def smart_defaults(
        self, payload: dict[str, Any], user_prefs: dict[str, Any]
    ) -> dict[str, Any]:
        result = {**self.default_values, **payload}

        if result.get("source_type") is None:
            result["source_type"] = "markdown"

        if result.get("tags") is None:
            result["tags"] = []

        # Auto-compute content_hash if content is present
        content = result.get("content", "")
        if content and not result.get("content_hash"):
            result["content_hash"] = hashlib.sha256(content.encode()).hexdigest()

        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        """Capture → Document formal record."""
        from .services import document_service

        content = payload.pop("content", "")
        content_hash = payload.get("content_hash") or hashlib.sha256(
            content.encode()
        ).hexdigest()

        create = DocumentCreate(
            title=payload.get("title", "Untitled Document"),
            source_type=payload.get("source_type", "markdown"),
            source_uri=payload.get("source_uri"),
            content_hash=content_hash,
            tags=payload.get("tags", []),
        )

        instance = await document_service.create(
            db, space_id, create, user_id=created_by
        )
        await db.commit()
        return instance.id
