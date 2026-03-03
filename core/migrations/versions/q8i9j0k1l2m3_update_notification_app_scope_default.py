"""update notification app_scope default from /v2/ to /

Revision ID: q8i9j0k1l2m3
Revises: p7h8i9j0k1l2
Create Date: 2026-03-03
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q8i9j0k1l2m3"
down_revision: str | None = "p7h8i9j0k1l2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Update server_default for app_scope column
    op.alter_column(
        "push_subscriptions",
        "app_scope",
        server_default="'/'",
        schema="notification",
    )
    # Update existing rows that still have the old default
    op.execute(
        "UPDATE notification.push_subscriptions SET app_scope = '/' WHERE app_scope = '/v2/'"
    )


def downgrade() -> None:
    op.alter_column(
        "push_subscriptions",
        "app_scope",
        server_default="'/v2/'",
        schema="notification",
    )
    op.execute(
        "UPDATE notification.push_subscriptions SET app_scope = '/v2/' WHERE app_scope = '/'"
    )
