"""Ideagraph state management — FeatureStore + NgRx patterns.

Tracks sparks map, links map, and spark count.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import to_immutable, update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── 1. Actions ────────────────────────────────────────────────────────────

SparkCaptured = create_action("ideagraph.spark.captured")
SparkRefined = create_action("ideagraph.spark.refined")
LinkSuggested = create_action("ideagraph.link.suggested")
LinkVerified = create_action("ideagraph.link.verified")

# ── 2. Reducer ────────────────────────────────────────────────────────────


def _handle_spark_captured(state, action):
    """Add spark to sparks map + increment spark_count."""
    payload = action.payload or {}
    spark_id = payload.get("id")
    if not spark_id:
        return state
    sparks = state.get("sparks", {})
    spark_entry = to_immutable(
        {
            "id": spark_id,
            "content": payload.get("content"),
            "tags": payload.get("tags"),
            "space_id": payload.get("space_id"),
            "created_at": payload.get("created_at"),
            "refined": False,
        }
    )
    new_sparks = sparks.set(spark_id, spark_entry)
    return update_in(state, ["sparks"], lambda _: new_sparks).set(
        "spark_count", state["spark_count"] + 1
    )


def _handle_spark_refined(state, action):
    """Update spark with refined content."""
    payload = action.payload or {}
    spark_id = payload.get("id")
    if not spark_id:
        return state
    sparks = state.get("sparks", {})
    if spark_id not in sparks:
        return state
    existing = sparks[spark_id]
    updated_spark = existing.set("refined", True)
    if payload.get("content"):
        updated_spark = updated_spark.set("content", payload["content"])
    return update_in(state, ["sparks"], lambda _: sparks.set(spark_id, updated_spark))


def _handle_link_suggested(state, action):
    """Add link to links map."""
    payload = action.payload or {}
    link_id = payload.get("id")
    if not link_id:
        return state
    links = state.get("links", {})
    link_entry = to_immutable(
        {
            "id": link_id,
            "source_id": payload.get("source_id"),
            "target_id": payload.get("target_id"),
            "link_type": payload.get("link_type"),
            "verified": False,
            "created_at": payload.get("created_at"),
        }
    )
    return update_in(state, ["links"], lambda _: links.set(link_id, link_entry))


def _handle_link_verified(state, action):
    """Mark link as verified."""
    payload = action.payload or {}
    link_id = payload.get("id")
    if not link_id:
        return state
    links = state.get("links", {})
    if link_id not in links:
        return state
    updated_link = links[link_id].set("verified", True)
    return update_in(state, ["links"], lambda _: links.set(link_id, updated_link))


ideagraph_reducer = create_reducer(
    {
        "sparks": {},
        "links": {},
        "spark_count": 0,
    },
    on(SparkCaptured, _handle_spark_captured),
    on(SparkRefined, _handle_spark_refined),
    on(LinkSuggested, _handle_link_suggested),
    on(LinkVerified, _handle_link_verified),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_sparks = create_selector(lambda s: s["sparks"])
select_links = create_selector(lambda s: s["links"])
select_spark_count = create_selector(lambda s: s["spark_count"])
select_verified_links = create_selector(
    select_links,
    result_fn=lambda links: {k: v for k, v in links.items() if v.get("verified")},
)
select_refined_sparks = create_selector(
    select_sparks,
    result_fn=lambda sparks: {k: v for k, v in sparks.items() if v.get("refined")},
)

# ── 4. Store ──────────────────────────────────────────────────────────────

ideagraph_store: FeatureStore = FeatureStore("ideagraph", ideagraph_reducer)
