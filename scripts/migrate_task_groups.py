#!/usr/bin/env python3
"""Migration: Create task_groups table + add group_id to recurring_items."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://workshop:workshop@127.0.0.1:5432/workshop"


async def migrate():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        # Create task_groups table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dailyos.task_groups (
                id VARCHAR(32) PRIMARY KEY,
                space_id VARCHAR(32) NOT NULL,
                created_by VARCHAR(32),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                deleted_at TIMESTAMPTZ,
                name TEXT NOT NULL,
                color TEXT DEFAULT '#cba6f7',
                icon TEXT,
                sort_order INTEGER DEFAULT 0
            )
        """))

        # Create index
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tg_space
            ON dailyos.task_groups (space_id)
        """))

        # Add group_id to recurring_items
        await conn.execute(text("""
            ALTER TABLE dailyos.recurring_items
            ADD COLUMN IF NOT EXISTS group_id VARCHAR(32)
            REFERENCES dailyos.task_groups(id) ON DELETE SET NULL
        """))

    await engine.dispose()
    print("Migration complete: task_groups table created, group_id added to recurring_items")


if __name__ == "__main__":
    asyncio.run(migrate())
