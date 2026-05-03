"""kg_triple verification fields + auto_evolve_log + verification_run_log

Revision ID: ee536d18be05
Revises: 57b1ac650965
Create Date: 2026-05-02 12:35:20.886118

Phase E + F + G of memvault data-flow-complete plan:
- Triple: verification_status / verified_at / last_confirmed_at /
  crag_correct_count / crag_incorrect_count
- New table: kg_auto_evolve_log (idempotency for auto_evolve_kg)
- New table: kg_verification_run_log (audit trail for promote_unverified weekly job)
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "ee536d18be05"
down_revision: str | None = "57b1ac650965"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "memvault"


def upgrade() -> None:
    # ---- Triple verification governance fields ----
    op.add_column(
        "triples",
        sa.Column(
            "verification_status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'unverified'"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column(
            "crag_correct_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "triples",
        sa.Column(
            "crag_incorrect_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema=SCHEMA,
    )
    # Partial index — promote_unverified() iterates only over candidates.
    op.create_index(
        "idx_triples_unverified",
        "triples",
        ["verification_status"],
        unique=False,
        postgresql_where=sa.text(
            "verification_status = 'unverified' AND invalid_at IS NULL"
        ),
        schema=SCHEMA,
    )

    # ---- kg_auto_evolve_log (Phase F) ----
    op.create_table(
        "kg_auto_evolve_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("memory_id", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("triples_extracted", sa.Integer(), server_default=sa.text("0")),
        sa.Column("triples_stored", sa.Integer(), server_default=sa.text("0")),
        sa.Column(
            "contradictions_resolved", sa.Integer(), server_default=sa.text("0")
        ),
        sa.UniqueConstraint(
            "memory_id", "content_hash", name="uq_auto_evolve_memory_hash"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_auto_evolve_log_memory",
        "kg_auto_evolve_log",
        ["memory_id"],
        unique=False,
        schema=SCHEMA,
    )

    # ---- kg_verification_run_log (Phase G) ----
    op.create_table(
        "kg_verification_run_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("candidates_scanned", sa.Integer(), server_default=sa.text("0")),
        sa.Column("promoted_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("demoted_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("notes", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_verification_run_started",
        "kg_verification_run_log",
        ["started_at"],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_verification_run_started", table_name="kg_verification_run_log", schema=SCHEMA
    )
    op.drop_table("kg_verification_run_log", schema=SCHEMA)
    op.drop_index("idx_auto_evolve_log_memory", table_name="kg_auto_evolve_log", schema=SCHEMA)
    op.drop_table("kg_auto_evolve_log", schema=SCHEMA)
    op.drop_index("idx_triples_unverified", table_name="triples", schema=SCHEMA)
    op.drop_column("triples", "crag_incorrect_count", schema=SCHEMA)
    op.drop_column("triples", "crag_correct_count", schema=SCHEMA)
    op.drop_column("triples", "last_confirmed_at", schema=SCHEMA)
    op.drop_column("triples", "verified_at", schema=SCHEMA)
    op.drop_column("triples", "verification_status", schema=SCHEMA)
