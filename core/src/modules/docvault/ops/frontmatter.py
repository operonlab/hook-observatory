"""Parse YAML frontmatter from markdown documents.

Phase 3 P3.1 — extract document-level authority metadata (type, status,
supersedes, related, updated) from the leading `---\\nYAML\\n---` block
so retrieval can later filter on document lifecycle.

The result is stored in `documents.metadata_` JSONB (no schema migration
needed; we re-use the existing column).
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Keys we care about for authority-aware retrieval. Other frontmatter keys
# (title, slug, owner, tags) are useful but not consumed by retrieval, so
# we ignore them here to keep the persisted metadata focused.
_AUTHORITY_KEYS = {
    "type",
    "status",
    "supersedes",
    "superseded_by",
    "related",
    "related_amendments",
    "updated",
    "created",
}

# A valid frontmatter block: starts with --- on first line, ends with ---.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)


def parse_frontmatter(raw_content: str) -> dict[str, Any]:
    """Return a dict of authority-relevant frontmatter keys (empty if none).

    Safe to call on any markdown; returns {} when the document has no
    frontmatter or the YAML is invalid.
    """
    if not raw_content:
        return {}
    match = _FRONTMATTER_RE.match(raw_content)
    if not match:
        return {}
    body = match.group(1)
    try:
        parsed = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        logger.debug("frontmatter YAML parse failed; ignoring")
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _AUTHORITY_KEYS:
        if key in parsed:
            result[key] = _to_jsonable(parsed[key])
    return result


def _to_jsonable(value: Any) -> Any:
    """Convert YAML-parsed types (date / datetime) to JSON-safe primitives."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value
