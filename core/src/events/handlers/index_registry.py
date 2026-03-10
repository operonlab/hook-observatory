"""Module → content field mapping registry for Qdrant indexing.

Each module defines how its entities map to IndexDocument fields.
The indexer uses this registry to extract searchable content from event payloads.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityMapping:
    """Maps a module entity to IndexDocument fields."""

    entity_type: str
    content_fields: list[str]  # fields to concatenate for embedding
    tag_field: str | None = None  # field name containing tags list
    metadata_fields: list[str] = field(default_factory=list)  # extra payload fields


@dataclass
class ModuleMapping:
    """All entity mappings for a single module."""

    service_id: str
    entities: dict[str, EntityMapping]  # event_prefix → mapping


# --- Module Registry ---

REGISTRY: dict[str, ModuleMapping] = {
    "intelflow": ModuleMapping(
        service_id="intelflow",
        entities={
            "report": EntityMapping(
                entity_type="report",
                content_fields=["title", "query", "content"],
                tag_field="tags",
                metadata_fields=["skill_name", "title", "query"],
            ),
            "topic": EntityMapping(
                entity_type="topic",
                content_fields=["name", "display_name"],
            ),
        },
    ),
    "taskflow": ModuleMapping(
        service_id="taskflow",
        entities={
            "task": EntityMapping(
                entity_type="task",
                content_fields=["title", "description"],
                tag_field="tags",
                metadata_fields=["status", "priority", "project"],
            ),
        },
    ),
    "capture": ModuleMapping(
        service_id="capture",
        entities={
            "capture": EntityMapping(
                entity_type="capture",
                content_fields=["raw_input"],
                metadata_fields=["module", "entity_type"],
            ),
        },
    ),
    "finance": ModuleMapping(
        service_id="finance",
        entities={
            "transaction": EntityMapping(
                entity_type="transaction",
                content_fields=["description", "merchant"],
                tag_field="tags",
                metadata_fields=["payment_method", "amount", "currency"],
            ),
            "subscription": EntityMapping(
                entity_type="subscription",
                content_fields=["name", "notes"],
                tag_field="tags",
                metadata_fields=["amount", "currency", "billing_cycle"],
            ),
        },
    ),
    "dailyos": ModuleMapping(
        service_id="dailyos",
        entities={
            "plan": EntityMapping(
                entity_type="plan",
                content_fields=["reflection"],
                tag_field="tags",
                metadata_fields=["method_name"],
            ),
            "method": EntityMapping(
                entity_type="method",
                content_fields=["name", "name_zh", "description"],
                tag_field="tags",
            ),
        },
    ),
    "nodeflow": ModuleMapping(
        service_id="nodeflow",
        entities={
            "flow": EntityMapping(
                entity_type="flow",
                content_fields=["name", "description"],
                metadata_fields=["trigger_type", "status"],
            ),
        },
    ),
    "invest": ModuleMapping(
        service_id="invest",
        entities={
            "position": EntityMapping(
                entity_type="position",
                content_fields=["symbol", "notes"],
                metadata_fields=["asset_type", "exchange", "broker"],
            ),
            "trade": EntityMapping(
                entity_type="trade",
                content_fields=["notes"],
                metadata_fields=["type", "symbol", "quantity", "price"],
            ),
        },
    ),
    "memvault": ModuleMapping(
        service_id="memvault",
        entities={
            "memory": EntityMapping(
                entity_type="block",
                content_fields=["content"],
                tag_field="tags",
                metadata_fields=["block_type"],
            ),
        },
    ),
}


def get_mapping(module: str, entity: str) -> EntityMapping | None:
    """Look up the entity mapping for a module.entity pair."""
    mod = REGISTRY.get(module)
    if mod is None:
        return None
    return mod.entities.get(entity)


def get_service_id(module: str) -> str | None:
    """Get the service_id for a module."""
    mod = REGISTRY.get(module)
    return mod.service_id if mod else None


def extract_content(data: dict[str, Any], mapping: EntityMapping) -> str:
    """Extract and concatenate searchable content from event data."""
    parts = []
    for field_name in mapping.content_fields:
        value = data.get(field_name)
        if value and isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def extract_tags(data: dict[str, Any], mapping: EntityMapping) -> list[str]:
    """Extract tags from event data."""
    if not mapping.tag_field:
        return []
    tags = data.get(mapping.tag_field)
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return []


def extract_metadata(data: dict[str, Any], mapping: EntityMapping) -> dict[str, Any]:
    """Extract metadata fields from event data."""
    meta = {}
    for field_name in mapping.metadata_fields:
        value = data.get(field_name)
        if value is not None:
            meta[field_name] = value
    return meta
