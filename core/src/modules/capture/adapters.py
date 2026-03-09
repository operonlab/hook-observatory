"""CaptureAdapter protocol — each module implements one to integrate with the capture pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from .strategies import EnrichmentStrategy


@dataclass
class AdapterManifest:
    """Self-describing adapter metadata — single source of truth.

    Inspired by Crawl4AI's CrawlerRunConfig as composition root.
    See AD-12 in docs/architecture/architecture-decisions.md.
    """

    module: str
    entity_type: str
    permission: str  # e.g. "finance.write"
    default_ttl_days: int = 30
    description: str = ""


class CaptureAdapter(Protocol):
    """Interface for module-specific capture behavior."""

    module: str
    entity_type: str

    # Field name -> weight (0-100, must sum to 100)
    field_weights: dict[str, int]

    # Default values to apply when missing
    default_values: dict[str, Any]

    # Default TTL in days for captures of this type
    default_ttl_days: int

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        """Apply smart defaults to fill inferable fields. Returns enriched payload."""
        ...

    def compute_completeness(self, payload: dict[str, Any]) -> float:
        """Calculate completeness score (0.0 - 1.0) based on field_weights."""
        ...

    def missing_fields(self, payload: dict[str, Any]) -> list[str]:
        """Return list of missing weighted fields."""
        ...

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        """Validate and create the formal record. Returns the created entity ID."""
        ...


class BaseCaptureAdapter:
    """Shared logic for capture adapters."""

    module: str = ""
    entity_type: str = ""
    field_weights: dict[str, int] = {}
    default_values: dict[str, Any] = {}
    default_ttl_days: int = 30

    # Mapping: field_name → resolver_key (e.g. {"wallet_id": "finance.wallet"})
    # Resolved automatically before promote() via resolve_references()
    reference_fields: dict[str, str] = {}

    # Optional enrichment strategies to run before promote().
    # Each strategy must be an EnrichmentStrategy instance.
    # If None or empty, the enrichment pipeline step is skipped.
    enrichment_strategies: list[EnrichmentStrategy] | None = None

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}
        return result

    def compute_completeness(self, payload: dict[str, Any]) -> float:
        if not self.field_weights:
            return 1.0
        total_weight = sum(self.field_weights.values())
        filled_weight = sum(
            w
            for field, w in self.field_weights.items()
            if payload.get(field) is not None and payload.get(field) != ""
        )
        return round(filled_weight / total_weight, 2) if total_weight else 1.0

    def missing_fields(self, payload: dict[str, Any]) -> list[str]:
        return [
            f
            for f, w in self.field_weights.items()
            if w > 0 and (payload.get(f) is None or payload.get(f) == "")
        ]

    @classmethod
    def manifest(cls) -> AdapterManifest:
        """Return self-describing manifest. Override in subclass if needed."""
        return AdapterManifest(
            module=cls.module,
            entity_type=cls.entity_type,
            permission=f"{cls.module}.write",
            default_ttl_days=cls.default_ttl_days,
            description=cls.__doc__ or "",
        )
