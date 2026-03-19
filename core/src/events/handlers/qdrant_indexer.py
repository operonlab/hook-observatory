"""Qdrant indexing handler — listens to EventBus events and syncs to Qdrant.

Subscribes to *.created, *.updated, *.deleted events for all registered modules
and maintains the Qdrant search index in sync with PostgreSQL.
"""

import logging
from datetime import datetime

from src.events.bus import Event, event_bus
from src.shared.qdrant_client import is_available
from src.shared.qdrant_search import delete_document, index_document, init_collection
from src.shared.search_types import IndexDocument

from .index_registry import (
    REGISTRY,
    extract_content,
    extract_metadata,
    extract_tags,
    get_mapping,
)

logger = logging.getLogger(__name__)

# Event suffixes we care about
_INDEX_SUFFIXES = {
    "created": "upsert",
    "stored": "upsert",  # memvault uses "stored" instead of "created"
    "updated": "upsert",
    "deleted": "delete",
}


def _parse_event_type(event_type: str) -> tuple[str, str, str] | None:
    """Parse 'module.entity.action' into (module, entity, action).

    Returns None if the event type doesn't match the expected pattern.
    """
    parts = event_type.split(".")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


async def _handle_upsert(event: Event, module: str, entity: str) -> None:
    """Handle create/update events by indexing the document."""
    mapping = get_mapping(module, entity)
    if mapping is None:
        return

    data = event.data
    entity_id = data.get("id") or data.get("entity_id")
    space_id = data.get("space_id")

    if not entity_id or not space_id:
        logger.warning(
            "Missing id or space_id in %s event data, skipping index",
            event.type,
        )
        return

    content = extract_content(data, mapping)
    if not content.strip():
        logger.debug("Empty content for %s/%s, skipping index", module, entity_id)
        return

    tags = extract_tags(data, mapping)
    metadata = extract_metadata(data, mapping)

    created_at = None
    if "created_at" in data:
        try:
            created_at = datetime.fromisoformat(data["created_at"])
        except (ValueError, TypeError):
            pass

    updated_at = None
    if "updated_at" in data:
        try:
            updated_at = datetime.fromisoformat(data["updated_at"])
        except (ValueError, TypeError):
            pass

    doc = IndexDocument(
        service_id=module,
        entity_id=str(entity_id),
        entity_type=mapping.entity_type,
        space_id=str(space_id),
        content=content,
        tags=tags,
        created_at=created_at,
        updated_at=updated_at,
        metadata=metadata,
    )

    success = await index_document(doc)
    if success:
        logger.debug("Indexed %s/%s to Qdrant", module, entity_id)
    else:
        logger.error("Failed to index %s/%s to Qdrant", module, entity_id)


async def _handle_delete(event: Event, module: str, entity: str) -> None:
    """Handle delete events by removing the document from Qdrant."""
    data = event.data
    entity_id = data.get("id") or data.get("entity_id")

    if not entity_id:
        logger.warning("Missing id in %s delete event, skipping", event.type)
        return

    success = await delete_document(module, str(entity_id))
    if success:
        logger.debug("Deleted %s/%s from Qdrant", module, entity_id)
    else:
        logger.warning("Failed to delete %s/%s from Qdrant", module, entity_id)


async def _qdrant_event_handler(event: Event) -> None:
    """Universal handler for all Qdrant-indexable events."""
    parsed = _parse_event_type(event.type)
    if parsed is None:
        return

    module, entity, action = parsed
    operation = _INDEX_SUFFIXES.get(action)
    if operation is None:
        return

    # Check if this module/entity is registered
    if get_mapping(module, entity) is None:
        return

    if operation == "upsert":
        await _handle_upsert(event, module, entity)
    elif operation == "delete":
        await _handle_delete(event, module, entity)


async def register_qdrant_handlers() -> None:
    """Register Qdrant indexing handlers for all modules in the registry.

    Call this during application startup (after EventBus is ready).
    Only registers if Qdrant is available.
    """
    if not await is_available():
        logger.info("Qdrant unavailable — skipping indexer registration")
        return

    registered = 0
    for module_name, module_mapping in REGISTRY.items():
        for entity_name in module_mapping.entities:
            # Subscribe to create/update/delete events
            for suffix in _INDEX_SUFFIXES:
                event_type = f"{module_name}.{entity_name}.{suffix}"
                event_bus.channel(event_type).subscribe_handler(_qdrant_event_handler)
                registered += 1

    logger.info("Registered %d Qdrant indexing handlers", registered)


async def startup() -> None:
    """Initialize Qdrant collection and register handlers.

    Call during app lifespan startup.
    """
    collection_ok = await init_collection()
    if collection_ok:
        await register_qdrant_handlers()
    else:
        logger.warning("Qdrant collection init failed — indexing disabled")
