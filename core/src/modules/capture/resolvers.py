"""Reference field resolvers — resolve human-readable values to DB UUIDs.

Generic infrastructure for capture adapters. Each module registers resolvers
for its reference fields (wallet_id, category_id, position_id, etc.).

Flow: UUID check → fuzzy name lookup → auto-create.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# UUID v7 pattern (26+ hex chars, no dashes)
_UUID_RE = re.compile(r"^[0-9a-f]{26,}$", re.IGNORECASE)

# Global resolver registry
_registry: dict[str, ReferenceResolver] = {}


def _normalize(raw: str) -> str:
    """Normalize raw value to a lookup key."""
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


class ReferenceResolver:
    """Base resolver — subclass per reference type."""

    schema: str  # DB schema, e.g. "finance"
    table: str  # DB table, e.g. "wallets"
    name_column: str = "name"

    # Subclass overrides: normalized_key → (create_kwargs)
    # Used by auto_create to map natural language to structured data
    name_map: dict[str, dict[str, Any]] = {}

    async def find_by_name(self, db: AsyncSession, space_id: str, raw: str) -> str | None:
        """Fuzzy name lookup — must be implemented by subclass."""
        raise NotImplementedError(f"find_by_name not implemented for {self.schema}.{self.table}")

    async def auto_create(
        self, db: AsyncSession, space_id: str, raw: str, created_by: str | None
    ) -> str:
        """Create entity from raw value. Must be overridden by subclass."""
        raise NotImplementedError(f"No auto-create for {self.schema}.{self.table}: {raw}")

    async def resolve(
        self, db: AsyncSession, space_id: str, raw: str, created_by: str | None = None
    ) -> str:
        """Resolve raw value → valid UUID. Auto-creates if not found."""
        if _UUID_RE.match(raw):
            return raw
        found = await self.find_by_name(db, space_id, raw)
        if found:
            return found
        return await self.auto_create(db, space_id, raw, created_by)


def register(key: str, resolver: ReferenceResolver) -> None:
    """Register a resolver. Key format: 'module.entity' (e.g. 'finance.wallet')."""
    _registry[key] = resolver


def get_resolver(key: str) -> ReferenceResolver | None:
    """Get a registered resolver by key."""
    return _registry.get(key)


async def resolve_references(
    reference_fields: dict[str, str],
    payload: dict[str, Any],
    db: AsyncSession,
    space_id: str,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Resolve all reference fields in a payload.

    Args:
        reference_fields: mapping of field_name → resolver_key
        payload: the capture payload to resolve
        db: database session
        space_id: current space
        created_by: user ID for auto-created entities

    Returns:
        payload with resolved UUIDs
    """
    for field, resolver_key in reference_fields.items():
        raw = payload.get(field)
        if not raw or (isinstance(raw, str) and _UUID_RE.match(raw)):
            continue
        resolver = _registry.get(resolver_key)
        if not resolver:
            continue
        payload[field] = await resolver.resolve(db, space_id, str(raw), created_by)
    return payload
