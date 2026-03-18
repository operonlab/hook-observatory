"""dailyos: Marvin cannibalization P0-P4 — 11 new tables.

Revision ID: f3g4h5i6j7k8
Revises: e2f3g4h5i6j7
Create Date: 2026-03-16
"""

revision = "f3g4h5i6j7k8"
down_revision = "e2f3g4h5i6j7"

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

SCHEMA = "dailyos"


def upgrade() -> None:
    # P1a: user_toggles
    op.create_table(
        "user_toggles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("toggle_key", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("false")),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("config", postgresql.JSONB, nullable=True),
        sa.Column("source", sa.Text, server_default=sa.text("'manual'")),
        schema=SCHEMA,
    )
    op.create_index("idx_ut_space", "user_toggles", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_ut_unique_key",
        "user_toggles",
        ["space_id", "toggle_key"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P1b: backlog_items
    op.create_table(
        "backlog_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("funnel_layer", sa.Text, nullable=False, server_default=sa.text("'master'")),
        sa.Column("priority", sa.Text, server_default=sa.text("'medium'")),
        sa.Column("labels", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("energy_level", sa.Integer, nullable=True),
        sa.Column("duration_min", sa.Integer, nullable=True),
        sa.Column("cognitive_cost", sa.Integer, nullable=True),
        sa.Column("do_date", sa.Date, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column(
            "parent_id",
            sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.backlog_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("source_module", sa.Text, nullable=True),
        sa.Column("source_id", sa.String(32), nullable=True),
        sa.Column("reward_points", sa.Integer, server_default=sa.text("1")),
        sa.Column("is_frog", sa.Boolean, server_default=sa.text("false")),
        sa.Column("defer_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("extra", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_bi_space_layer", "backlog_items", ["space_id", "funnel_layer"], schema=SCHEMA
    )
    op.create_index("idx_bi_space_due", "backlog_items", ["space_id", "due_date"], schema=SCHEMA)

    # P1c: capacity_history
    op.create_table(
        "capacity_history",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("log_date", sa.Date, nullable=False),
        sa.Column("budget_type", sa.Text, nullable=False, server_default=sa.text("'time'")),
        sa.Column("planned_value", sa.Float, server_default=sa.text("0")),
        sa.Column("actual_value", sa.Float, server_default=sa.text("0")),
        sa.Column("unit", sa.Text, server_default=sa.text("'minutes'")),
        sa.Column("energy_start", sa.Integer, nullable=True),
        sa.Column("energy_end", sa.Integer, nullable=True),
        sa.Column("mood", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_ch_unique_date",
        "capacity_history",
        ["space_id", "log_date", "budget_type"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P2a: workflows
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_zh", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.Text, nullable=True),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column("is_preset", sa.Boolean, server_default=sa.text("false")),
        sa.Column("category", sa.Text, server_default=sa.text("'methodology'")),
        sa.Column("method_ids", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("toggle_overrides", postgresql.JSONB, nullable=True),
        sa.Column("snippet_ids", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("false")),
        sa.Column("rating", sa.Float, nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_wf_space", "workflows", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_wf_unique_slug",
        "workflows",
        ["space_id", "slug"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P2c: snippets
    op.create_table(
        "snippets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_zh", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.Text, nullable=True),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column("is_preset", sa.Boolean, server_default=sa.text("false")),
        sa.Column("toggle_keys", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("config_patch", postgresql.JSONB, nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("false")),
        schema=SCHEMA,
    )
    op.create_index("idx_sn_space", "snippets", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_sn_unique_slug",
        "snippets",
        ["space_id", "slug"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P2d: smart_lists
    op.create_table(
        "smart_lists",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_zh", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.Text, nullable=True),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column(
            "filter_expr", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("sort_by", sa.Text, server_default=sa.text("'priority'")),
        sa.Column("group_by", sa.Text, nullable=True),
        sa.Column("is_preset", sa.Boolean, server_default=sa.text("false")),
        sa.Column("source_modules", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_sl_space", "smart_lists", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_sl_unique_slug",
        "smart_lists",
        ["space_id", "slug"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P2b: pilot_state
    op.create_table(
        "pilot_state",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_date", sa.Date, nullable=False),
        sa.Column("flight_mode", sa.Text, server_default=sa.text("'cruise'")),
        sa.Column("cognitive_fuel_budget", sa.Float, server_default=sa.text("100")),
        sa.Column("cognitive_fuel_spent", sa.Float, server_default=sa.text("0")),
        sa.Column("time_budget_min", sa.Integer, server_default=sa.text("480")),
        sa.Column("time_spent_min", sa.Integer, server_default=sa.text("0")),
        sa.Column("verify_level", sa.Text, server_default=sa.text("'normal'")),
        sa.Column("ratchet_history", postgresql.JSONB, nullable=True),
        sa.Column("black_box", postgresql.JSONB, nullable=True),
        sa.Column("decision_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("decision_fatigue_score", sa.Float, nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_ps_unique_date",
        "pilot_state",
        ["space_id", "state_date"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P3c: plan_templates
    op.create_table(
        "plan_templates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_zh", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("items", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("method_ids", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("toggle_overrides", postgresql.JSONB, nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("use_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_pt_space", "plan_templates", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_pt_unique_slug",
        "plan_templates",
        ["space_id", "slug"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P3d: gamification_state
    op.create_table(
        "gamification_state",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_points", sa.Integer, server_default=sa.text("0")),
        sa.Column("current_streak", sa.Integer, server_default=sa.text("0")),
        sa.Column("longest_streak", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_streak_date", sa.Date, nullable=True),
        sa.Column("level", sa.Integer, server_default=sa.text("1")),
        sa.Column("achievements", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reward_config", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_gs_unique_space",
        "gamification_state",
        ["space_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # P3d: point_history
    op.create_table(
        "point_history",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("points", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_id", sa.String(32), nullable=True),
        sa.Column("multiplier", sa.Float, server_default=sa.text("1.0")),
        sa.Column("earned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_ph_space_date", "point_history", ["space_id", "earned_at"], schema=SCHEMA)

    # P4: experiments
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_zh", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.Text, server_default=sa.text("'draft'")),
        sa.Column(
            "variant_a", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "variant_b", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("duration_days", sa.Integer, server_default=sa.text("7")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results", postgresql.JSONB, nullable=True),
        sa.Column("winner", sa.Text, nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_ex_space", "experiments", ["space_id"], schema=SCHEMA)
    op.create_index("idx_ex_status", "experiments", ["space_id", "status"], schema=SCHEMA)

    # Seed pilot method preset
    op.execute("""
        INSERT INTO dailyos.methods (id, space_id, slug, name, name_zh, description, icon, color,
            is_preset, config, version, layout_type, tags, created_at, updated_at)
        SELECT
            'preset_pilot_method_01',
            'system',
            'pilot-method',
            'Pilot Method',
            '領航法',
            '獨創認知操作系統——雙軌容量管理，四種飛行模式動態切換，驗證棘輪確保品質，黑盒子審查持續最佳化。',
            '✈️',
            '#74c7ec',
            true,
            '{}',
            1,
            'list',
            ARRAY['cognitive', 'dual-track', 'innovative', 'self-optimizing'],
            now(),
            now()
        WHERE NOT EXISTS (
            SELECT 1 FROM dailyos.methods WHERE slug = 'pilot-method' AND space_id = 'system'
        );
    """)


def downgrade() -> None:
    op.drop_table("experiments", schema=SCHEMA)
    op.drop_table("point_history", schema=SCHEMA)
    op.drop_table("gamification_state", schema=SCHEMA)
    op.drop_table("plan_templates", schema=SCHEMA)
    op.drop_table("pilot_state", schema=SCHEMA)
    op.drop_table("smart_lists", schema=SCHEMA)
    op.drop_table("snippets", schema=SCHEMA)
    op.drop_table("workflows", schema=SCHEMA)
    op.drop_table("capacity_history", schema=SCHEMA)
    op.drop_table("backlog_items", schema=SCHEMA)
    op.drop_table("user_toggles", schema=SCHEMA)

    op.execute("DELETE FROM dailyos.methods WHERE slug = 'pilot-method' AND space_id = 'system'")
