"""Paper actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

ArticleCreated = create_action("paper.article.created")
ArticleUpdated = create_action("paper.article.updated")
ArticleDeleted = create_action("paper.article.deleted")
DigestGenerated = create_action("paper.digest.generated")
AnnotationCreated = create_action("paper.annotation.created")
