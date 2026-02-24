"""create memvault schema and tables

Revision ID: 2bb21e53cb53
Revises:
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "2bb21e53cb53"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create memvault schema
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # --- blocks ---
    op.create_table(
        "blocks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("source_session", sa.String(64), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "block_type",
            sa.String(50),
            server_default=sa.text("'general'"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_blocks_space", "blocks", ["space_id"], schema=SCHEMA)
    op.create_index("idx_blocks_type", "blocks", ["block_type"], schema=SCHEMA)
    op.create_index(
        "idx_blocks_session", "blocks", ["source_session"], schema=SCHEMA
    )
    op.create_index(
        "idx_blocks_tags",
        "blocks",
        ["tags"],
        schema=SCHEMA,
        postgresql_using="gin",
    )
    op.execute(
        f"""
        CREATE INDEX idx_blocks_embedding
        ON {SCHEMA}.blocks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # --- tags ---
    op.create_table(
        "tags",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "usage_count", sa.Integer, server_default=sa.text("0"), nullable=False
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_tags_name",
        "tags",
        ["space_id", "name"],
        unique=True,
        schema=SCHEMA,
    )

    # --- knowledge_domains ---
    op.create_table(
        "knowledge_domains",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "maturity", sa.Float, server_default=sa.text("0.0"), nullable=False
        ),
        sa.Column(
            "block_count", sa.Integer, server_default=sa.text("0"), nullable=False
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_kd_name",
        "knowledge_domains",
        ["space_id", "name"],
        unique=True,
        schema=SCHEMA,
    )

    # --- kas_profiles ---
    op.create_table(
        "kas_profiles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "knowledge_score",
            sa.Float,
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "attitude_score",
            sa.Float,
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "skill_score",
            sa.Float,
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_kas_space",
        "kas_profiles",
        ["space_id"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("kas_profiles", schema=SCHEMA)
    op.drop_table("knowledge_domains", schema=SCHEMA)
    op.drop_table("tags", schema=SCHEMA)
    op.drop_table("blocks", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
