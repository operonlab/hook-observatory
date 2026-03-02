"""create sentinel schema for health monitoring

Creates the sentinel schema with 4 tables:
  - sentinel.health_checks    (individual check results)
  - sentinel.incidents         (incident tracking)
  - sentinel.active_operations (agent operation tracking)
  - sentinel.subscriptions     (webhook subscriptions)

Revision ID: j1a2b3c4d5e6
Revises: i0a1b2c3d4e5, i0b1c2d3e4f5
Create Date: 2026-03-02
"""

from alembic import op

revision = "j1a2b3c4d5e6"
down_revision = ("i0a1b2c3d4e5", "i0b1c2d3e4f5")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create schema
    op.execute("CREATE SCHEMA IF NOT EXISTS sentinel")

    # Use raw SQL with IF NOT EXISTS — sentinel tables may already exist
    # from manual creation before this migration was tracked by alembic.

    # --- sentinel.health_checks ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS sentinel.health_checks (
            id VARCHAR(36) DEFAULT gen_random_uuid()::text NOT NULL PRIMARY KEY,
            service VARCHAR(50) NOT NULL,
            check_type VARCHAR(10) NOT NULL,
            status VARCHAR(20) NOT NULL,
            response_ms FLOAT,
            detail TEXT,
            created_at VARCHAR(50) DEFAULT now()::text NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_hc_service ON sentinel.health_checks (service)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_hc_created ON sentinel.health_checks (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_hc_status ON sentinel.health_checks (status)")

    # --- sentinel.incidents ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS sentinel.incidents (
            id VARCHAR(36) DEFAULT gen_random_uuid()::text NOT NULL PRIMARY KEY,
            service VARCHAR(50) NOT NULL,
            status VARCHAR(20) DEFAULT 'investigating' NOT NULL,
            severity VARCHAR(20) DEFAULT 'minor' NOT NULL,
            title TEXT NOT NULL,
            detail TEXT,
            diagnosis JSONB,
            repair_result JSONB,
            created_at VARCHAR(50) DEFAULT now()::text NOT NULL,
            resolved_at VARCHAR(50)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_inc_service ON sentinel.incidents (service)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_inc_status ON sentinel.incidents (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_inc_created ON sentinel.incidents (created_at)")

    # --- sentinel.active_operations ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS sentinel.active_operations (
            id VARCHAR(36) DEFAULT gen_random_uuid()::text NOT NULL PRIMARY KEY,
            service VARCHAR(50) NOT NULL,
            action VARCHAR(100) NOT NULL,
            agent_id VARCHAR(100) NOT NULL,
            pid INTEGER,
            estimated_duration INTEGER DEFAULT 300 NOT NULL,
            created_at VARCHAR(50) DEFAULT now()::text NOT NULL,
            resolved_at VARCHAR(50),
            result VARCHAR(20)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ao_service ON sentinel.active_operations (service)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ao_agent ON sentinel.active_operations (agent_id)")

    # --- sentinel.subscriptions ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS sentinel.subscriptions (
            id VARCHAR(36) DEFAULT gen_random_uuid()::text NOT NULL PRIMARY KEY,
            url TEXT NOT NULL,
            events JSONB DEFAULT '["*"]'::jsonb NOT NULL,
            active BOOLEAN DEFAULT true NOT NULL,
            created_at VARCHAR(50) DEFAULT now()::text NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sub_active ON sentinel.subscriptions (active)")


def downgrade() -> None:
    op.drop_table("subscriptions", schema="sentinel")
    op.drop_table("active_operations", schema="sentinel")
    op.drop_table("incidents", schema="sentinel")
    op.drop_table("health_checks", schema="sentinel")
    op.execute("DROP SCHEMA IF EXISTS sentinel")
