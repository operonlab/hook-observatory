"""Admin seed script — create initial admin user from environment variables.

Usage:
    python -m src.modules.auth.seed

Requires CORE_ADMIN_EMAIL and CORE_ADMIN_PASSWORD environment variables.
Idempotent: skips if any user already exists.
"""

import asyncio
import sys

from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.modules.auth.models import User

_ph = PasswordHasher()


async def seed_admin() -> None:
    if not settings.admin_email or not settings.admin_password:
        print("ERROR: CORE_ADMIN_EMAIL and CORE_ADMIN_PASSWORD must be set.")
        sys.exit(1)

    db_url = settings.db_url.replace("postgresql://", "postgresql+psycopg://")
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Check if any users exist
        count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        if count > 0:
            print(f"Skipped: {count} user(s) already exist.")
            await engine.dispose()
            return

        admin = User(
            email=settings.admin_email,
            display_name="Admin",
            password_hash=_ph.hash(settings.admin_password),
            role="admin",
            status="active",
        )
        db.add(admin)
        await db.commit()
        print(f"Created admin user: {settings.admin_email} (id={admin.id})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_admin())
