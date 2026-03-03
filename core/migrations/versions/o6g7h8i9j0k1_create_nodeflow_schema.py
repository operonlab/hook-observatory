"""create nodeflow schema

Revision ID: o6g7h8i9j0k1
Revises: n5f6g7h8i9j0
Create Date: 2026-03-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "o6g7h8i9j0k1"
down_revision: Union[str, None] = "n5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nodeflow"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ── flows ──
    op.create_table(
        "flows",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("trigger_type", sa.Text, nullable=False, server_default=sa.text("'event'")),
        sa.Column("trigger_config", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'draft'")),
        schema=SCHEMA,
    )
    op.create_index("idx_nf_flow_space_status", "flows", ["space_id", "status"], schema=SCHEMA)
    op.create_index("idx_nf_flow_space_trigger", "flows", ["space_id", "trigger_type"], schema=SCHEMA)

    # ── nodes ──
    op.create_table(
        "nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flow_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_type", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=True),
        sa.Column("position_x", sa.Float, nullable=False, server_default=sa.text("0")),
        sa.Column("position_y", sa.Float, nullable=False, server_default=sa.text("0")),
        schema=SCHEMA,
    )
    op.create_index("idx_nf_node_flow", "nodes", ["flow_id"], schema=SCHEMA)

    # ── edges ──
    op.create_table(
        "edges",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flow_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_port", sa.Text, nullable=False, server_default=sa.text("'output'")),
        schema=SCHEMA,
    )
    op.create_index("idx_nf_edge_flow", "edges", ["flow_id"], schema=SCHEMA)
    op.create_unique_constraint(
        "uq_nf_edge_src_tgt_port",
        "edges",
        ["source_node_id", "target_node_id", "source_port"],
        schema=SCHEMA,
    )

    # ── flow_runs ──
    op.create_table(
        "flow_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flow_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'running'")),
        sa.Column("trigger_event", postgresql.JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_nf_flowrun_flow", "flow_runs", ["flow_id"], schema=SCHEMA)
    op.create_index("idx_nf_flowrun_space_status", "flow_runs", ["space_id", "status"], schema=SCHEMA)

    # ── node_run_logs ──
    op.create_table(
        "node_run_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flow_run_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.flow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(32), sa.ForeignKey(f"{SCHEMA}.nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("input_data", postgresql.JSONB, nullable=True),
        sa.Column("output_data", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_nf_noderunlog_flowrun", "node_run_logs", ["flow_run_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("node_run_logs", schema=SCHEMA)
    op.drop_table("flow_runs", schema=SCHEMA)
    op.drop_table("edges", schema=SCHEMA)
    op.drop_table("nodes", schema=SCHEMA)
    op.drop_table("flows", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
