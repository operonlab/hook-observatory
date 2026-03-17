"""create paper schema — articles, digests, annotations, citations, article_embeddings.

Revision ID: g4h5i6j7k8l9
Revises: f3g4h5i6j7k8
Create Date: 2026-03-17
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "g4h5i6j7k8l9"
down_revision = "f3g4h5i6j7k8"
branch_labels = None
depends_on = None

SCHEMA = "paper"
EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ── articles (SpaceScopedModel) ──
    op.create_table(
        "articles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        # Core metadata
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("abstract", sa.Text, nullable=True),
        sa.Column("arxiv_id", sa.String(32), nullable=True),
        sa.Column("doi", sa.String(128), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("authors", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("journal", sa.Text, nullable=True),
        # Classification
        sa.Column("categories", postgresql.ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        sa.Column("tags", postgresql.ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        # URLs and storage
        sa.Column("pdf_url", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("full_text", sa.Text, nullable=True),
        sa.Column("s3_uri", sa.Text, nullable=True),
        # Inline embedding
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_articles_deleted_at", "articles", ["deleted_at"], schema=SCHEMA)
    op.create_index("ix_articles_space_id", "articles", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_articles_arxiv_id",
        "articles",
        ["arxiv_id"],
        schema=SCHEMA,
        unique=True,
        postgresql_where=sa.text("arxiv_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "idx_articles_doi",
        "articles",
        ["doi"],
        schema=SCHEMA,
        unique=True,
        postgresql_where=sa.text("doi IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "idx_articles_tags",
        "articles",
        ["tags"],
        schema=SCHEMA,
        postgresql_using="gin",
    )
    op.create_index(
        "idx_articles_categories",
        "articles",
        ["categories"],
        schema=SCHEMA,
        postgresql_using="gin",
    )
    op.create_index("idx_articles_year", "articles", ["year"], schema=SCHEMA)
    op.create_index("idx_articles_created", "articles", ["created_at"], schema=SCHEMA)
    op.create_index(
        "idx_articles_embedding",
        "articles",
        ["embedding"],
        schema=SCHEMA,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # ── digests (SpaceScopedModel) ──
    op.create_table(
        "digests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "paper_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("one_liner", sa.Text, nullable=True),
        sa.Column("key_findings", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("workshop_relevance", sa.String(16), nullable=True),
        sa.Column("applicable_modules", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("actionable_insight", sa.Text, nullable=True),
        sa.Column("effort_estimate", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("model_used", sa.String(128), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_digests_deleted_at", "digests", ["deleted_at"], schema=SCHEMA)
    op.create_index("ix_digests_space_id", "digests", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_digests_paper_id",
        "digests",
        ["paper_id"],
        schema=SCHEMA,
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_digests_workshop_relevance", "digests", ["workshop_relevance"], schema=SCHEMA
    )
    op.create_index("idx_digests_model_used", "digests", ["model_used"], schema=SCHEMA)

    # ── annotations (SpaceScopedModel) ──
    op.create_table(
        "annotations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "paper_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("annotation_type", sa.String(32), server_default=sa.text("'note'")),
        sa.Column("tags", postgresql.ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        schema=SCHEMA,
    )
    op.create_index("ix_annotations_deleted_at", "annotations", ["deleted_at"], schema=SCHEMA)
    op.create_index("ix_annotations_space_id", "annotations", ["space_id"], schema=SCHEMA)
    op.create_index("idx_annotations_paper_id", "annotations", ["paper_id"], schema=SCHEMA)
    op.create_index(
        "idx_annotations_annotation_type", "annotations", ["annotation_type"], schema=SCHEMA
    )
    op.create_index(
        "idx_annotations_tags",
        "annotations",
        ["tags"],
        schema=SCHEMA,
        postgresql_using="gin",
    )

    # ── citations (Base — global facts, not space-scoped) ──
    op.create_table(
        "citations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "source_paper_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_paper_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(32), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_citations_source", "citations", ["source_paper_id"], schema=SCHEMA)
    op.create_index("idx_citations_target", "citations", ["target_paper_id"], schema=SCHEMA)
    op.create_index(
        "idx_citations_unique",
        "citations",
        ["source_paper_id", "target_paper_id", "relationship_type"],
        schema=SCHEMA,
        unique=True,
    )

    # ── article_embeddings (Base — separated vector sub-table) ──
    op.create_table(
        "article_embeddings",
        sa.Column(
            "article_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_article_emb_hnsw",
        "article_embeddings",
        ["embedding"],
        schema=SCHEMA,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
