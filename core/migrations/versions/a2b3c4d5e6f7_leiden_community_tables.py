"""Replace GMM clusters/wisdom with Leiden communities/summaries.

Revision ID: a2b3c4d5e6f7
Revises: z7r8s9t0u1v2
Create Date: 2026-03-18

GraphRAG-inspired refactor:
- Cluster (GMM) → Community (Leiden graph community detection)
- ClusterTriple → CommunityTriple
- WisdomNode → CommunitySummary
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "a2b3c4d5e6f7"
down_revision = "z7r8s9t0u1v2"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    # --- Create new tables ---

    op.create_table(
        "communities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("resolution_level", sa.Integer, nullable=False),
        sa.Column("size", sa.Integer, server_default=sa.text("0")),
        sa.Column("entity_ids", ARRAY(sa.Text), nullable=True),
        sa.Column("top_entities", ARRAY(sa.Text), nullable=True),
        sa.Column("top_predicates", ARRAY(sa.Text), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "parent_community_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.communities.id"),
            nullable=True,
        ),
        sa.Column("generation_batch", sa.String(32), nullable=True),
        sa.Column("modularity_score", sa.Float, nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_communities_level", "communities", ["resolution_level"], schema=SCHEMA)
    op.create_index("idx_communities_parent", "communities", ["parent_community_id"], schema=SCHEMA)

    op.create_table(
        "community_triples",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "community_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.communities.id"),
            nullable=False,
        ),
        sa.Column(
            "triple_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.triples.id"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_community_triples_community", "community_triples", ["community_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_community_triples_triple", "community_triples", ["triple_id"], schema=SCHEMA
    )

    op.create_table(
        "community_summaries",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "community_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.communities.id"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("key_findings", ARRAY(sa.Text), nullable=True),
        sa.Column("representative_triples", ARRAY(sa.Text), nullable=True),
        sa.Column("evidence_count", sa.Integer, nullable=True),
        sa.Column("tags", ARRAY(sa.Text), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("generation_batch", sa.String(32), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_community_summaries_community",
        "community_summaries",
        ["community_id"],
        schema=SCHEMA,
    )

    # --- Drop old tables (order: FK children first) ---

    op.drop_table("cluster_triples", schema=SCHEMA)
    op.drop_table("wisdom_nodes", schema=SCHEMA)
    op.drop_table("clusters", schema=SCHEMA)


def downgrade() -> None:
    # Drop new tables
    op.drop_table("community_summaries", schema=SCHEMA)
    op.drop_table("community_triples", schema=SCHEMA)
    op.drop_table("communities", schema=SCHEMA)

    # Recreate old tables
    op.create_table(
        "clusters",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("size", sa.Integer, server_default=sa.text("0")),
        sa.Column("top_subjects", ARRAY(sa.Text), nullable=True),
        sa.Column("top_predicates", ARRAY(sa.Text), nullable=True),
        sa.Column("top_objects", ARRAY(sa.Text), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("verdict", sa.String(20), server_default=sa.text("'UNVERIFIED'")),
        sa.Column("generation_batch", sa.String(32), nullable=True),
        schema=SCHEMA,
    )

    op.create_table(
        "cluster_triples",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cluster_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.clusters.id"), nullable=False
        ),
        sa.Column(
            "triple_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.triples.id"), nullable=False
        ),
        sa.Column("confidence", sa.Float, nullable=True),
        schema=SCHEMA,
    )

    op.create_table(
        "wisdom_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wisdom", sa.Text, nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("bridge_entity", sa.String(200), nullable=False),
        sa.Column("cluster_ids", ARRAY(sa.Text), nullable=False),
        sa.Column("evidence_count", sa.Integer, nullable=True),
        sa.Column("tags", ARRAY(sa.Text), nullable=True),
        sa.Column("verified", sa.Boolean, server_default=sa.text("false")),
        schema=SCHEMA,
    )
