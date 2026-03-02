"""create intelflow schema and tables

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-02-27
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

SCHEMA = "intelflow"


def upgrade() -> None:
    # Create intelflow schema
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # --- reports ---
    op.create_table(
        "reports",
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
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "sources",
            sa.dialects.postgresql.JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.Text),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("skill_name", sa.Text, nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_reports_space", "reports", ["space_id"], schema=SCHEMA)
    op.create_index("idx_reports_created", "reports", ["created_at"], schema=SCHEMA)
    op.create_index(
        "idx_reports_tags",
        "reports",
        ["tags"],
        schema=SCHEMA,
        postgresql_using="gin",
    )
    op.execute(
        f"""
        CREATE INDEX idx_reports_embedding
        ON {SCHEMA}.reports
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # --- topics ---
    op.create_table(
        "topics",
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
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column(
            "report_count",
            sa.Integer,
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(768), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_topics_name",
        "topics",
        ["space_id", "name"],
        unique=True,
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE INDEX idx_topics_embedding
        ON {SCHEMA}.topics
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # --- report_topics (M2M) ---
    op.create_table(
        "report_topics",
        sa.Column(
            "report_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.reports.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "relevance",
            sa.Float,
            server_default=sa.text("1.0"),
            nullable=False,
        ),
        schema=SCHEMA,
    )

    # --- topic_relations ---
    op.create_table(
        "topic_relations",
        sa.Column(
            "source_topic_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_topic_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "weight",
            sa.Float,
            server_default=sa.text("1.0"),
            nullable=False,
        ),
        schema=SCHEMA,
    )

    # --- briefing_topics ---
    op.create_table(
        "briefing_topics",
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
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean,
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Integer,
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("prompt_template", sa.Text, nullable=True),
        sa.Column(
            "sources",
            sa.dialects.postgresql.JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "schedule",
            sa.String(20),
            server_default=sa.text("'daily'"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_bt_name",
        "briefing_topics",
        ["space_id", "name"],
        unique=True,
        schema=SCHEMA,
    )

    # --- briefing_subtopics ---
    op.create_table(
        "briefing_subtopics",
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
            "topic_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.briefing_topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "parameters",
            sa.dialects.postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "enabled",
            sa.Boolean,
            server_default=sa.text("true"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_subtopics_topic",
        "briefing_subtopics",
        ["topic_id"],
        schema=SCHEMA,
    )

    # --- briefings ---
    op.create_table(
        "briefings",
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
        sa.Column("date", sa.Date, nullable=False),
        sa.Column(
            "topic_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.briefing_topics.id"),
            nullable=True,
        ),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("raw_data", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("analyses", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("debate", sa.Text, nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.UniqueConstraint("date", "topic_id", name="uq_briefing_date_topic"),
        schema=SCHEMA,
    )
    op.create_index("idx_briefings_date", "briefings", ["date"], schema=SCHEMA)
    op.create_index(
        "idx_briefings_topic", "briefings", ["topic_id"], schema=SCHEMA
    )

    # --- search_sessions ---
    op.create_table(
        "search_sessions",
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
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("result_type", sa.Text, nullable=True),
        sa.Column(
            "report_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("search_sessions", schema=SCHEMA)
    op.drop_table("briefings", schema=SCHEMA)
    op.drop_table("briefing_subtopics", schema=SCHEMA)
    op.drop_table("briefing_topics", schema=SCHEMA)
    op.drop_table("topic_relations", schema=SCHEMA)
    op.drop_table("report_topics", schema=SCHEMA)
    op.drop_table("topics", schema=SCHEMA)
    op.drop_table("reports", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
