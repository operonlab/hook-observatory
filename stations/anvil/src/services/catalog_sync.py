"""Catalog sync service — extract from filesystem, write to DB.

Imports extraction logic directly from skill-catalog and skill-graph scripts
to avoid duplication. The sys.path manipulation is intentional (cannibalisation
of standalone skill scripts into the Anvil station backend).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("anvil.catalog_sync")

# ---------------------------------------------------------------------------
# Dynamic imports from skill scripts
# ---------------------------------------------------------------------------

CATALOG_SCRIPTS = str(Path.home() / ".claude/skills/skill-catalog/scripts")
GRAPH_SCRIPTS = str(Path.home() / ".claude/skills/skill-graph/scripts")

if CATALOG_SCRIPTS not in sys.path:
    sys.path.insert(0, CATALOG_SCRIPTS)
if GRAPH_SCRIPTS not in sys.path:
    sys.path.insert(0, GRAPH_SCRIPTS)

try:
    from extract_catalog import DEFAULT_SKILLS_DIR, extract_skill  # type: ignore[import-not-found]

    _catalog_available = True
except ImportError as e:
    logger.warning("extract_catalog not importable: %s", e)
    _catalog_available = False
    DEFAULT_SKILLS_DIR = str(Path.home() / ".claude/skills")

try:
    from scan_skills import build_graph  # type: ignore[import-not-found]

    _graph_available = True
except ImportError as e:
    logger.warning("scan_skills not importable: %s", e)
    _graph_available = False


# ---------------------------------------------------------------------------
# Upsert SQL
# ---------------------------------------------------------------------------

_UPSERT_SKILL_SQL = text("""
    INSERT INTO anvil.skills (
        name, version, description, tags, io_schema, health_score, status,
        domain, strengths, pain_point, triggers, tools, body_lines,
        resources, guide, health_details
    )
    VALUES (
        :name, :version, :description,
        CAST(:tags AS jsonb), CAST(:io_schema AS jsonb),
        :health_score, 'active',
        :domain, CAST(:strengths AS jsonb), :pain_point,
        CAST(:triggers AS jsonb), CAST(:tools AS jsonb), :body_lines,
        CAST(:resources AS jsonb), :guide, CAST(:health_details AS jsonb)
    )
    ON CONFLICT (name) DO UPDATE SET
        version        = EXCLUDED.version,
        description    = EXCLUDED.description,
        tags           = EXCLUDED.tags,
        io_schema      = EXCLUDED.io_schema,
        health_score   = EXCLUDED.health_score,
        domain         = EXCLUDED.domain,
        strengths      = EXCLUDED.strengths,
        pain_point     = EXCLUDED.pain_point,
        triggers       = EXCLUDED.triggers,
        tools          = EXCLUDED.tools,
        body_lines     = EXCLUDED.body_lines,
        resources      = EXCLUDED.resources,
        guide          = EXCLUDED.guide,
        health_details = EXCLUDED.health_details,
        updated_at     = now()
""")

_DELETE_EDGES_SQL = text("DELETE FROM anvil.skill_edges")

_INSERT_EDGE_SQL = text("""
    INSERT INTO anvil.skill_edges (source, target, edge_type, strength, description)
    VALUES (:source, :target, :edge_type, :strength, :description)
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_json(value: Any) -> str:
    """Serialize a Python value to a JSON string for parameterised SQL."""
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False)


def _build_skill_params(entry: dict) -> dict:
    return {
        "name": entry.get("name", ""),
        "version": entry.get("version") or None,
        "description": entry.get("pain_point") or entry.get("description") or None,
        "tags": _to_json(entry.get("tags", [])),
        "io_schema": _to_json(entry.get("io_schema")) if entry.get("io_schema") else "null",
        "health_score": entry.get("health_score"),
        "domain": entry.get("domain", "general"),
        "strengths": _to_json(entry.get("strengths", [])),
        "pain_point": entry.get("pain_point") or None,
        "triggers": _to_json(entry.get("triggers", [])),
        "tools": _to_json(entry.get("tools", [])),
        "body_lines": entry.get("body_lines", 0),
        "resources": _to_json(entry.get("resources", {})),
        "guide": entry.get("guide") or None,
        "health_details": _to_json(entry.get("health_details"))
        if entry.get("health_details")
        else "null",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def sync_catalog_to_db(
    db: AsyncSession,
    skills_dir: str | None = None,
) -> dict:
    """Extract catalog from filesystem and upsert into DB.

    Returns:
        dict with keys: synced_skills, edges, errors
    """
    if not _catalog_available:
        return {
            "synced_skills": 0,
            "edges": 0,
            "errors": ["extract_catalog module not available — check CATALOG_SCRIPTS path"],
        }

    target_dir = skills_dir or DEFAULT_SKILLS_DIR
    skills_path = Path(target_dir)
    errors: list[str] = []

    # ── 1. Extract all skills from filesystem ────────────────────────────
    catalog: list[dict] = []
    guides_dir = Path.home() / ".claude/skills/skill-catalog/guides"

    for d in sorted(skills_path.iterdir()):  # noqa: ASYNC240
        if not d.is_dir() or d.name.startswith("."):
            continue
        try:
            entry = extract_skill(d, guides_dir=guides_dir if guides_dir.exists() else None)
            if entry:
                catalog.append(entry)
        except Exception as exc:
            errors.append(f"extract {d.name}: {exc}")
            logger.warning("Failed to extract skill %s: %s", d.name, exc)

    logger.info("Extracted %d skills from %s", len(catalog), target_dir)

    # ── 2. Upsert skills ─────────────────────────────────────────────────
    synced = 0
    for entry in catalog:
        try:
            params = _build_skill_params(entry)
            await db.execute(_UPSERT_SKILL_SQL, params)
            synced += 1
        except Exception as exc:
            errors.append(f"upsert {entry.get('name', '?')}: {exc}")
            logger.warning("Failed to upsert skill %s: %s", entry.get("name"), exc)

    # ── 3. Replace all edges ─────────────────────────────────────────────
    edge_count = 0
    if _graph_available:
        try:
            graph = build_graph(target_dir)
            raw_edges = graph.get("edges", [])

            await db.execute(_DELETE_EDGES_SQL)

            for e in raw_edges:
                await db.execute(
                    _INSERT_EDGE_SQL,
                    {
                        "source": e.get("source", ""),
                        "target": e.get("target", ""),
                        "edge_type": e.get("type", "unknown"),
                        "strength": float(e.get("strength", 0.5)),
                        "description": e.get("description") or None,
                    },
                )
            edge_count = len(raw_edges)
            logger.info("Replaced edges: %d inserted", edge_count)
        except Exception as exc:
            errors.append(f"graph/edges: {exc}")
            logger.warning("Failed to sync edges: %s", exc)
    else:
        errors.append("scan_skills module not available — edges not synced")

    # ── 4. Refresh utility scores from invocation data ─────────────────
    try:
        from services.telemetry import TelemetryService

        svc = TelemetryService(db)
        utility_count = await svc.refresh_all_utilities()
        logger.info("Refreshed utility scores for %d skills", utility_count)
    except Exception as exc:
        errors.append(f"utility refresh: {exc}")
        logger.warning("Failed to refresh utility scores: %s", exc)

    await db.commit()

    return {
        "synced_skills": synced,
        "edges": edge_count,
        "errors": errors,
    }
