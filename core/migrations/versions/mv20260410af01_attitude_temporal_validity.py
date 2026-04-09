"""attitude_facts: add temporal validity columns + access tracking

Extends AttitudeFact with Zep/Graphiti-inspired temporal validity:
- invalid_at: when this attitude stopped being valid (independent of superseded_by)
- invalidation_reason: why (evolved, grounding_drift, contradiction, etc.)
- access_count: retrieval frequency for half-life computation
- last_accessed_at: recency tracking

Revision ID: mv20260410af01
Revises: mv20260409tv01
Create Date: 2026-04-10
"""

import sqlalchemy as sa
from alembic import op

revision = "mv20260410af01"
down_revision = "mv20260409tv01"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    op.add_column(
        "attitude_facts",
        sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "attitude_facts",
        sa.Column("invalidation_reason", sa.String(200), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "attitude_facts",
        sa.Column("access_count", sa.Integer, server_default=sa.text("0"), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "attitude_facts",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    # Partial index for valid + current attitudes (replaces idx_attitude_facts_current)
    op.create_index(
        "idx_attitude_facts_valid",
        "attitude_facts",
        ["space_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("invalid_at IS NULL AND superseded_by IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_attitude_facts_valid", "attitude_facts", schema=SCHEMA)
    op.drop_column("attitude_facts", "last_accessed_at", schema=SCHEMA)
    op.drop_column("attitude_facts", "access_count", schema=SCHEMA)
    op.drop_column("attitude_facts", "invalidation_reason", schema=SCHEMA)
    op.drop_column("attitude_facts", "invalid_at", schema=SCHEMA)
