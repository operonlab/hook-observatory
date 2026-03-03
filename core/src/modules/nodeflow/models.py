"""Nodeflow ORM models — flows, nodes, edges, flow runs, node run logs.

All tables live in the `nodeflow` PostgreSQL schema.
IDs: String(32) + uuid7().hex.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.models import SpaceScopedModel

SCHEMA = "nodeflow"


# ======================== Flows ========================


class Flow(SpaceScopedModel):
    """A visual DAG flow — triggered by event, schedule, or manual."""

    __tablename__ = "flows"
    __table_args__ = (
        Index("idx_nf_flow_space_status", "space_id", "status"),
        Index("idx_nf_flow_space_trigger", "space_id", "trigger_type"),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'event'")
    )  # event / schedule / manual
    trigger_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )  # draft / active / paused / archived

    # Relationships
    nodes: Mapped[list["Node"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", lazy="selectin"
    )
    edges: Mapped[list["Edge"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", lazy="selectin"
    )
    runs: Mapped[list["FlowRun"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", lazy="noload"
    )


# ======================== Nodes ========================


class Node(SpaceScopedModel):
    """A single node inside a flow — trigger, action, condition, etc."""

    __tablename__ = "nodes"
    __table_args__ = (
        Index("idx_nf_node_flow", "flow_id"),
        {"schema": SCHEMA},
    )

    flow_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.flows.id", ondelete="CASCADE"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # trigger / action / condition / transform / notify / delay
    label: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    position_y: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))

    # Relationships
    flow: Mapped["Flow"] = relationship(back_populates="nodes")


# ======================== Edges ========================


class Edge(SpaceScopedModel):
    """A directed edge connecting two nodes in a flow."""

    __tablename__ = "edges"
    __table_args__ = (
        Index("idx_nf_edge_flow", "flow_id"),
        UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "source_port",
            name="uq_nf_edge_src_tgt_port",
        ),
        {"schema": SCHEMA},
    )

    flow_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.flows.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.nodes.id", ondelete="CASCADE"), nullable=False
    )
    source_port: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'output'")
    )  # output / true / false

    # Relationships
    flow: Mapped["Flow"] = relationship(back_populates="edges")


# ======================== Flow Runs ========================


class FlowRun(SpaceScopedModel):
    """A single execution of a flow."""

    __tablename__ = "flow_runs"
    __table_args__ = (
        Index("idx_nf_flowrun_flow", "flow_id"),
        Index("idx_nf_flowrun_space_status", "space_id", "status"),
        {"schema": SCHEMA},
    )

    flow_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.flows.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'running'")
    )  # running / completed / failed / cancelled
    trigger_event: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    flow: Mapped["Flow"] = relationship(back_populates="runs")
    node_run_logs: Mapped[list["NodeRunLog"]] = relationship(
        back_populates="flow_run", cascade="all, delete-orphan", lazy="selectin"
    )


# ======================== Node Run Logs ========================


class NodeRunLog(SpaceScopedModel):
    """Execution log for a single node within a flow run."""

    __tablename__ = "node_run_logs"
    __table_args__ = (
        Index("idx_nf_noderunlog_flowrun", "flow_run_id"),
        {"schema": SCHEMA},
    )

    flow_run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.flow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.nodes.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )  # pending / running / completed / failed / skipped
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    flow_run: Mapped["FlowRun"] = relationship(back_populates="node_run_logs")
