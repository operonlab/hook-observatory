"""DocVault lifecycle FSMs — Document and DocumentVersion state machines.

Document lifecycle:
    ingested → processing → indexed → enriched → published → archived
                                                                ↑ (re-upload)
    Any non-final state → failed

DocumentVersion lifecycle:
    processing → ready → superseded
"""

import logging

logger = logging.getLogger(__name__)

# ======================== Document Lifecycle ========================

DOCUMENT_STATES = frozenset(
    {"ingested", "processing", "indexed", "enriched", "published", "archived", "failed"}
)

DOCUMENT_TRANSITIONS: dict[str, set[str]] = {
    "ingested": {"processing", "failed"},
    "processing": {"indexed", "failed"},
    "indexed": {"enriched", "failed"},
    "enriched": {"published"},
    "published": {"archived"},
    "archived": set(),  # terminal
    "failed": set(),  # terminal
}


def can_transition_document(current: str, target: str) -> bool:
    """Check if a document state transition is valid."""
    return target in DOCUMENT_TRANSITIONS.get(current, set())


def validate_document_transition(current: str, target: str) -> None:
    """Validate and raise if transition is invalid."""
    if not can_transition_document(current, target):
        allowed = DOCUMENT_TRANSITIONS.get(current, set())
        raise ValueError(
            f"Invalid document transition: {current} → {target}. "
            f"Allowed: {allowed or 'none (terminal state)'}"
        )


# ======================== DocumentVersion Lifecycle ========================

VERSION_STATES = frozenset({"processing", "ready", "superseded"})

VERSION_TRANSITIONS: dict[str, set[str]] = {
    "processing": {"ready"},
    "ready": {"superseded"},
    "superseded": set(),  # terminal
}


def can_transition_version(current: str, target: str) -> bool:
    """Check if a version state transition is valid."""
    return target in VERSION_TRANSITIONS.get(current, set())


def validate_version_transition(current: str, target: str) -> None:
    """Validate and raise if transition is invalid."""
    if not can_transition_version(current, target):
        allowed = VERSION_TRANSITIONS.get(current, set())
        raise ValueError(
            f"Invalid version transition: {current} → {target}. "
            f"Allowed: {allowed or 'none (terminal state)'}"
        )
