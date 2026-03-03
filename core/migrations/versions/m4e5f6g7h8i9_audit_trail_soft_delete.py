"""add audit trail and soft delete support

Merge multi-head branches and add:
  - admin.audit_logs table (cross-module audit trail)
  - deleted_at column to all SpaceScopedModel tables (soft delete)

Revision ID: m4e5f6g7h8i9
Revises: l3d4e5f6g7h8, j1a2b3c4d5e6
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "m4e5f6g7h8i9"
down_revision = ("l3d4e5f6g7h8", "j1a2b3c4d5e6")
branch_labels = None
depends_on = None

# Tables that need deleted_at column added.
# finance.wallets already has deleted_at — skip it.
_SOFT_DELETE_TABLES = [
    # finance
    ("finance", "categories"),
    ("finance", "installment_plans"),
    ("finance", "transactions"),
    ("finance", "subscriptions"),
    ("finance", "wallet_snapshots"),
    ("finance", "budgets"),
    # memvault
    ("memvault", "blocks"),
    ("memvault", "tags"),
    ("memvault", "knowledge_domains"),
    ("memvault", "profile_scores"),
    ("memvault", "triples"),
    ("memvault", "clusters"),
    ("memvault", "cluster_triples"),
    ("memvault", "wisdom_nodes"),
    ("memvault", "attitude_facts"),
    ("memvault", "skill_invocations"),
    # intelflow
    ("intelflow", "reports"),
    ("intelflow", "topics"),
    ("intelflow", "briefing_topics"),
    ("intelflow", "briefing_subtopics"),
    ("intelflow", "briefings"),
    ("intelflow", "search_sessions"),
]


def upgrade() -> None:
    # --- 1. Create admin schema + audit_logs table ---
    op.execute("CREATE SCHEMA IF NOT EXISTS admin")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column("module", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=False),
        sa.Column("entity_id", sa.String(32), nullable=False),
        sa.Column("space_id", sa.String(32), nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("changes", JSONB, nullable=True),
        sa.Column("snapshot", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="admin",
    )
    op.create_index(
        "idx_audit_entity",
        "audit_logs",
        ["module", "entity_type", "entity_id"],
        schema="admin",
    )
    op.create_index("idx_audit_user", "audit_logs", ["user_id"], schema="admin")
    op.create_index(
        "idx_audit_created",
        "audit_logs",
        [sa.text("created_at DESC")],
        schema="admin",
    )
    op.create_index("idx_audit_space", "audit_logs", ["space_id"], schema="admin")

    # --- 2. Add deleted_at column to all SpaceScopedModel tables ---
    for schema, table in _SOFT_DELETE_TABLES:
        op.add_column(
            table,
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            schema=schema,
        )
        op.create_index(
            f"idx_{table}_deleted_at",
            table,
            ["deleted_at"],
            schema=schema,
        )


def downgrade() -> None:
    # Remove deleted_at columns
    for schema, table in reversed(_SOFT_DELETE_TABLES):
        op.drop_index(f"idx_{table}_deleted_at", table_name=table, schema=schema)
        op.drop_column(table, "deleted_at", schema=schema)

    # Drop audit_logs table and admin schema
    op.drop_table("audit_logs", schema="admin")
    # Don't drop admin schema — it may be used by other things
