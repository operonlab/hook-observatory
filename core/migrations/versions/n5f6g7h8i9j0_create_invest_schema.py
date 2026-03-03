"""create invest schema — investment portfolio tracking

Creates 4 tables for the invest module:
  - invest.accounts     (investment account management)
  - invest.positions    (individual holdings per account)
  - invest.trades       (buy/sell/dividend records)
  - invest.quotes       (price quote cache)

All monetary columns use DECIMAL(15,4).

Revision ID: n5f6g7h8i9j0
Revises: m4e5f6g7h8i9
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op

revision = "n5f6g7h8i9j0"
down_revision = "m4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Create schema ---
    op.execute("CREATE SCHEMA IF NOT EXISTS invest")

    # --- 1. accounts (must come first — referenced by positions) ---
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("broker", sa.Text, nullable=True),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("finance_wallet_id", sa.String(32), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="invest",
    )
    op.create_index("idx_invest_account_space", "accounts", ["space_id"], schema="invest")
    op.create_index(
        "idx_invest_account_unique_name",
        "accounts",
        ["space_id", "name"],
        unique=True,
        schema="invest",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --- 2. positions (per-account holdings) ---
    op.create_table(
        "positions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "account_id",
            sa.String(32),
            sa.ForeignKey("invest.accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("exchange", sa.Text, nullable=True),
        sa.Column("asset_type", sa.Text, nullable=False, server_default=sa.text("'stock'")),
        sa.Column("shares", sa.Numeric(15, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_cost", sa.Numeric(15, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("current_price", sa.Numeric(15, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="invest",
    )
    op.create_index("idx_position_account", "positions", ["account_id"], schema="invest")
    op.create_index(
        "idx_position_unique_symbol",
        "positions",
        ["account_id", "symbol"],
        unique=True,
        schema="invest",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --- 3. trades (buy/sell/dividend records) ---
    op.create_table(
        "trades",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "position_id",
            sa.String(32),
            sa.ForeignKey("invest.positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("shares", sa.Numeric(15, 4), nullable=False),
        sa.Column("price", sa.Numeric(15, 4), nullable=False),
        sa.Column("fee", sa.Numeric(15, 4), server_default=sa.text("0")),
        sa.Column("tax", sa.Numeric(15, 4), server_default=sa.text("0")),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="invest",
    )
    op.create_index("idx_trade_position", "trades", ["position_id"], schema="invest")
    op.create_index(
        "idx_trade_space_time",
        "trades",
        ["space_id", sa.text("traded_at DESC")],
        schema="invest",
    )

    # --- 4. quotes (price cache) ---
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("price", sa.Numeric(15, 4), nullable=False),
        sa.Column("prev_close", sa.Numeric(15, 4), nullable=True),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'manual'")),
        sa.Column("quoted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="invest",
    )
    op.create_index("idx_quote_symbol", "quotes", ["symbol"], schema="invest")
    op.create_index(
        "idx_quote_unique_symbol_space",
        "quotes",
        ["space_id", "symbol"],
        unique=True,
        schema="invest",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("quotes", schema="invest")
    op.drop_table("trades", schema="invest")
    op.drop_table("positions", schema="invest")
    op.drop_table("accounts", schema="invest")
    op.execute("DROP SCHEMA IF EXISTS invest")
