"""Paper state management — FeatureStore + NgRx patterns.

Tracks articles map, digest count, and recent annotations.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

import logging

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import to_immutable, update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

logger = logging.getLogger(__name__)

# ── 1. Actions ────────────────────────────────────────────────────────────

ArticleCreated = create_action("paper.article.created")
ArticleUpdated = create_action("paper.article.updated")
ArticleDeleted = create_action("paper.article.deleted")
DigestGenerated = create_action("paper.digest.generated")
AnnotationCreated = create_action("paper.annotation.created")

# ── 2. Reducer ────────────────────────────────────────────────────────────

_MAX_RECENT_ANNOTATIONS = 50


def _handle_article_created(state, action):
    """Add article to articles map by id."""
    payload = action.payload or {}
    article_id = payload.get("id")
    if not article_id:
        return state
    articles = state.get("articles", {})
    article_entry = to_immutable(
        {
            "id": article_id,
            "title": payload.get("title"),
            "arxiv_id": payload.get("arxiv_id"),
            "doi": payload.get("doi"),
            "year": payload.get("year"),
            "categories": payload.get("categories"),
            "created_at": payload.get("created_at"),
        }
    )
    return update_in(state, ["articles"], lambda _: articles.set(article_id, article_entry))


def _handle_article_deleted(state, action):
    """Remove article from articles map."""
    payload = action.payload or {}
    article_id = payload.get("id") or payload.get("article_id")
    if not article_id:
        return state
    articles = state.get("articles", {})
    if article_id not in articles:
        return state
    e = articles.mutate()
    del e[article_id]
    return state.set("articles", e.finish())


def _handle_digest_generated(state, action):
    """Increment digest_count."""
    return state.set("digest_count", state["digest_count"] + 1)


def _handle_annotation_created(state, action):
    """Prepend annotation to recent_annotations (capped at 50)."""
    payload = action.payload or {}
    annotation_id = payload.get("id")
    if not annotation_id:
        return state
    recent = state.get("recent_annotations", ())
    entry = to_immutable(
        {
            "id": annotation_id,
            "article_id": payload.get("article_id"),
            "content": payload.get("content"),
            "annotation_type": payload.get("annotation_type"),
            "created_at": payload.get("created_at"),
        }
    )
    new_recent = (entry, *recent)[:_MAX_RECENT_ANNOTATIONS]
    return state.set("recent_annotations", new_recent)


paper_reducer = create_reducer(
    {
        "articles": {},
        "digest_count": 0,
        "recent_annotations": [],
    },
    on(ArticleCreated, _handle_article_created),
    on(ArticleUpdated, lambda s, a: s),
    on(ArticleDeleted, _handle_article_deleted),
    on(DigestGenerated, _handle_digest_generated),
    on(AnnotationCreated, _handle_annotation_created),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_articles = create_selector(lambda s: s["articles"])
select_digest_count = create_selector(lambda s: s["digest_count"])
select_recent_annotations = create_selector(lambda s: s["recent_annotations"])
select_article_count = create_selector(
    select_articles,
    result_fn=lambda articles: len(articles),
)

# ── 4. Store ──────────────────────────────────────────────────────────────

paper_store: FeatureStore = FeatureStore("paper", paper_reducer)

# ── 5. Effects ────────────────────────────────────────────────────────────


@effect(ArticleCreated, store=paper_store)
async def log_article_created(action, store) -> None:
    """Log new article ingestion."""
    payload = action.payload or {}
    logger.info(
        "paper.article.created",
        extra={
            "article_id": payload.get("id"),
            "title": payload.get("title"),
            "arxiv_id": payload.get("arxiv_id"),
        },
    )


@effect(DigestGenerated, store=paper_store)
async def log_digest_generated(action, store) -> None:
    """Log digest generation completion."""
    payload = action.payload or {}
    logger.info(
        "paper.digest.generated",
        extra={
            "article_id": payload.get("article_id"),
            "digest_id": payload.get("id"),
        },
    )


register_effects(paper_store, log_article_created, log_digest_generated)
