"""merge entity_edges + blocks_valid_at heads (bitemporal data flow PR)

Revision ID: 57b1ac650965
Revises: mv20260410ee01, mv20260502bt01
Create Date: 2026-05-02 12:34:34.533211
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57b1ac650965'
down_revision: Union[str, None] = ('mv20260410ee01', 'mv20260502bt01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
