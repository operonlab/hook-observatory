"""create finance schema — full personal finance management

Creates all 9 tables for the finance module:
  - finance.wallets               (multi-account balance management)
  - finance.categories            (tree-structured categories)
  - finance.installment_plans     (installment payment tracking)
  - finance.transactions          (income/expense/transfer records)
  - finance.transaction_tags      (M2M tags)
  - finance.transaction_attachments (receipt photos via RustFS)
  - finance.subscriptions         (recurring billing)
  - finance.wallet_snapshots      (balance reconciliation)
  - finance.budgets               (monthly budgets)

All monetary columns use DECIMAL(15,4).
wallet_id is NOT NULL in transactions (D1 decision).
Privacy via is_private + SQL WHERE exclusion (D2 decision).

Revision ID: i0a1b2c3d4e5
Revises: h9a0b1c2d3e4
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa

revision = "i0a1b2c3d4e5"
down_revision = "h9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Create schema ---
    op.execute("CREATE SCHEMA IF NOT EXISTS finance")

    # --- 1. wallets (must come first — referenced by transactions, subscriptions, installments) ---
    op.create_table(
        "wallets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("initial_balance", sa.Numeric(15, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("current_balance", sa.Numeric(15, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("credit_limit", sa.Numeric(15, 4), nullable=True),
        sa.Column("icon", sa.Text, nullable=True),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("is_private", sa.Boolean, server_default=sa.text("false")),
        sa.Column("sync_provider", sa.Text, server_default=sa.text("'manual'")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )
    op.create_index(
        "idx_wallet_space", "wallets", ["space_id"], schema="finance"
    )
    op.create_index(
        "idx_wallet_unique_name",
        "wallets",
        ["space_id", "name"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("is_active = true"),
    )

    # --- 2. categories (self-referencing tree) ---
    op.create_table(
        "categories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("parent_id", sa.String(32), sa.ForeignKey("finance.categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("icon", sa.Text, nullable=True),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("is_private", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )
    op.create_index(
        "idx_category_unique_name",
        "categories",
        ["space_id", sa.text("COALESCE(parent_id, '')"), "name"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("is_active = true"),
    )

    # --- 3. installment_plans (referenced by transactions) ---
    op.create_table(
        "installment_plans",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("total_amount", sa.Numeric(15, 4), nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("num_installments", sa.Integer, nullable=False),
        sa.Column("installment_amount", sa.Numeric(15, 4), nullable=False),
        sa.Column("interest_rate", sa.Numeric(5, 4), server_default=sa.text("0")),
        sa.Column("billing_day", sa.Integer, nullable=True),
        sa.Column("fee_type", sa.Text, server_default=sa.text("'none'")),
        sa.Column("fee_per_installment", sa.Numeric(15, 4), server_default=sa.text("0")),
        sa.Column("merchant", sa.Text, nullable=True),
        sa.Column("category_id", sa.String(32), sa.ForeignKey("finance.categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("wallet_id", sa.String(32), sa.ForeignKey("finance.wallets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payment_method", sa.Text, nullable=False),
        sa.Column("payment_detail", sa.Text, nullable=True),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("status", sa.Text, server_default=sa.text("'active'")),
        sa.Column("is_private", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )

    # --- 4. transactions ---
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(15, 4), nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("merchant", sa.Text, nullable=True),
        sa.Column("payment_method", sa.Text, nullable=False),
        sa.Column("payment_detail", sa.Text, nullable=True),
        sa.Column("category_id", sa.String(32), sa.ForeignKey("finance.categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("wallet_id", sa.String(32), sa.ForeignKey("finance.wallets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("transfer_to_wallet_id", sa.String(32), sa.ForeignKey("finance.wallets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("installment_plan_id", sa.String(32), sa.ForeignKey("finance.installment_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("installment_number", sa.Integer, nullable=True),
        sa.Column("paired_transaction_id", sa.String(32), nullable=True),
        sa.Column("status", sa.Text, server_default=sa.text("'completed'")),
        sa.Column("settlement_amount", sa.Numeric(15, 4), nullable=True),
        sa.Column("original_currency", sa.Text, nullable=True),
        sa.Column("exchange_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("fee", sa.Numeric(15, 4), server_default=sa.text("0")),
        sa.Column("invoice_number", sa.Text, nullable=True),
        sa.Column("is_private", sa.Boolean, server_default=sa.text("false")),
        sa.Column("transacted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )
    # Self-referencing FK for paired_transaction_id (added after table creation)
    op.create_foreign_key(
        "fk_txn_paired",
        "transactions",
        "transactions",
        ["paired_transaction_id"],
        ["id"],
        ondelete="SET NULL",
        source_schema="finance",
        referent_schema="finance",
    )
    # Transaction indexes
    op.create_index("idx_txn_space_time", "transactions", ["space_id", sa.text("transacted_at DESC")], schema="finance")
    op.create_index("idx_txn_wallet", "transactions", ["wallet_id"], schema="finance")
    op.create_index("idx_txn_category", "transactions", ["space_id", "category_id", sa.text("transacted_at")], schema="finance")
    op.create_index("idx_txn_installment", "transactions", ["installment_plan_id"], schema="finance")
    op.create_index(
        "idx_txn_installment_num",
        "transactions",
        ["installment_plan_id", "installment_number"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("installment_plan_id IS NOT NULL"),
    )
    op.create_index(
        "idx_txn_scheduled",
        "transactions",
        ["status", sa.text("transacted_at")],
        schema="finance",
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_index(
        "idx_txn_paired",
        "transactions",
        ["paired_transaction_id"],
        schema="finance",
        postgresql_where=sa.text("paired_transaction_id IS NOT NULL"),
    )

    # --- 5. transaction_tags (M2M) ---
    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.String(32), sa.ForeignKey("finance.transactions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag", sa.Text, nullable=False, primary_key=True),
        schema="finance",
    )

    # --- 6. transaction_attachments ---
    op.create_table(
        "transaction_attachments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("transaction_id", sa.String(32), sa.ForeignKey("finance.transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )

    # --- 7. subscriptions ---
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(15, 4), nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'TWD'")),
        sa.Column("billing_cycle", sa.Text, nullable=False),
        sa.Column("billing_day", sa.Integer, nullable=True),
        sa.Column("category_id", sa.String(32), sa.ForeignKey("finance.categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("wallet_id", sa.String(32), sa.ForeignKey("finance.wallets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payment_method", sa.Text, nullable=True),
        sa.Column("payment_detail", sa.Text, nullable=True),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("status", sa.Text, server_default=sa.text("'active'")),
        sa.Column("next_billing", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_private", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )
    op.create_index("idx_sub_space", "subscriptions", ["space_id"], schema="finance")

    # --- 8. wallet_snapshots ---
    op.create_table(
        "wallet_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("wallet_id", sa.String(32), sa.ForeignKey("finance.wallets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("synced_balance", sa.Numeric(15, 4), nullable=False),
        sa.Column("calculated_balance", sa.Numeric(15, 4), nullable=False),
        sa.Column("difference", sa.Numeric(15, 4), sa.Computed("synced_balance - calculated_balance", persisted=True)),
        sa.Column("snapshot_type", sa.Text, server_default=sa.text("'reconciliation'")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )
    op.create_index("idx_snapshot_wallet_time", "wallet_snapshots", ["wallet_id", sa.text("synced_at DESC")], schema="finance")
    op.create_index("idx_snapshot_space_time", "wallet_snapshots", ["space_id", sa.text("synced_at DESC")], schema="finance")

    # --- 9. budgets ---
    op.create_table(
        "budgets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("year_month", sa.Text, nullable=False),
        sa.Column("category_id", sa.String(32), sa.ForeignKey("finance.categories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("budget_amount", sa.Numeric(15, 4), nullable=False),
        sa.Column("savings_target", sa.Numeric(15, 4), nullable=True),
        sa.Column("is_private", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="finance",
    )
    # Two partial unique indexes for NULL category_id handling
    op.create_index(
        "idx_budget_with_category",
        "budgets",
        ["space_id", "year_month", "category_id"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )
    op.create_index(
        "idx_budget_total",
        "budgets",
        ["space_id", "year_month"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("category_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("budgets", schema="finance")
    op.drop_table("wallet_snapshots", schema="finance")
    op.drop_table("subscriptions", schema="finance")
    op.drop_table("transaction_attachments", schema="finance")
    op.drop_table("transaction_tags", schema="finance")
    op.drop_table("transactions", schema="finance")
    op.drop_table("installment_plans", schema="finance")
    op.drop_table("categories", schema="finance")
    op.drop_table("wallets", schema="finance")
    op.execute("DROP SCHEMA IF EXISTS finance")
