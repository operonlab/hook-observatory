"""Add docvault KG tables (entities, triples, communities).

Revision ID: s1t2u3v4w5x6
Revises: m5n6o7p8q9r2
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "s1t2u3v4w5x6"
down_revision = "m5n6o7p8q9r2"
branch_labels = None
depends_on = None

SCHEMA = "docvault"


def upgrade() -> None:
    # 1. doc_entities (no FK deps within new tables)
    op.create_table(
        "doc_entities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("canonical_name", sa.String(500), nullable=False),
        sa.Column(
            "aliases",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "entity_type",
            sa.String(50),
            server_default=sa.text("'concept'"),
        ),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_chunk_ids",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("mention_count", sa.Integer(), server_default=sa.text("1")),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docentity_canonical",
        "doc_entities",
        ["space_id", "canonical_name"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docentity_document",
        "doc_entities",
        ["document_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docentity_type",
        "doc_entities",
        ["entity_type"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docentity_aliases",
        "doc_entities",
        ["aliases"],
        postgresql_using="gin",
        schema=SCHEMA,
    )

    # 2. doc_triples (depends on doc_entities)
    op.create_table(
        "doc_triples",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("predicate", sa.String(100), nullable=False),
        sa.Column("object", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(500), nullable=True),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.document_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0")),
        sa.Column(
            "subject_entity_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.doc_entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "object_entity_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.doc_entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doctriple_subject",
        "doc_triples",
        ["subject"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doctriple_predicate",
        "doc_triples",
        ["predicate"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doctriple_object",
        "doc_triples",
        ["object"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doctriple_document",
        "doc_triples",
        ["document_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doctriple_chunk",
        "doc_triples",
        ["chunk_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doctriple_valid",
        "doc_triples",
        ["space_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema=SCHEMA,
    )

    # 3. doc_communities (self-referential FK, no deps on triples)
    op.create_table(
        "doc_communities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("resolution_level", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), server_default=sa.text("0")),
        sa.Column("entity_ids", ARRAY(sa.Text()), nullable=True),
        sa.Column("top_entities", ARRAY(sa.Text()), nullable=True),
        sa.Column("top_predicates", ARRAY(sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "parent_community_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.doc_communities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("generation_batch", sa.String(32), nullable=True),
        sa.Column("modularity_score", sa.Float(), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doccommunity_level",
        "doc_communities",
        ["resolution_level"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doccommunity_parent",
        "doc_communities",
        ["parent_community_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doccommunity_space",
        "doc_communities",
        ["space_id"],
        schema=SCHEMA,
    )

    # 4. doc_community_triples (depends on doc_communities + doc_triples)
    op.create_table(
        "doc_community_triples",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "community_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.doc_communities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "triple_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.doc_triples.id", ondelete="CASCADE"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docct_community",
        "doc_community_triples",
        ["community_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docct_triple",
        "doc_community_triples",
        ["triple_id"],
        schema=SCHEMA,
    )

    # 5. doc_community_summaries (depends on doc_communities)
    op.create_table(
        "doc_community_summaries",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "community_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.doc_communities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_findings", ARRAY(sa.Text()), nullable=True),
        sa.Column("representative_triples", ARRAY(sa.Text()), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("generation_batch", sa.String(32), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_doccs_community",
        "doc_community_summaries",
        ["community_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("doc_community_summaries", schema=SCHEMA)
    op.drop_table("doc_community_triples", schema=SCHEMA)
    op.drop_table("doc_communities", schema=SCHEMA)
    op.drop_table("doc_triples", schema=SCHEMA)
    op.drop_table("doc_entities", schema=SCHEMA)
