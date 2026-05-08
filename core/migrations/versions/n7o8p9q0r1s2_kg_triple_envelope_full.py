"""kg triple envelope full + drop display_zh + FTS analyzer english→simple

Revision ID: n7o8p9q0r1s2
Revises: ee536d18be05
Create Date: 2026-05-08

中文化重構（合併版 Plan A+）：
- Triple 表加 9 envelope columns + extra_metadata JSONB
  - kind / modality / polarity / raw_quote / temporal / attribution
  - speaker_id / refs_triple_id / confidence / extra_metadata
- 砍 display_zh 欄位（反譯方案廢除，subject/object 直存中文 surface form）
- 重建 idx_blocks_fts GIN index：to_tsvector 'english' → 'simple'
  原因：'english' analyzer 對中文不分詞 → 中文化後 BM25 channel 歸零

注意：本 migration 只在 Mac 主機跑（multi-machine rule）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "n7o8p9q0r1s2"
down_revision: str | None = "ee536d18be05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------
    # 1. Triple 表加 envelope 9 cols + extra_metadata
    # -----------------------------------------------------------------
    op.add_column(
        "triples",
        sa.Column("kind", sa.String(16), nullable=False, server_default=sa.text("'event'")),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("modality", sa.String(16), nullable=True),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("polarity", sa.String(16), nullable=True),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("raw_quote", sa.Text(), nullable=True),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("temporal", JSONB(), nullable=True),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("attribution", JSONB(), nullable=True),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("speaker_id", sa.String(32), nullable=True),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column(
            "refs_triple_id",
            sa.String(32),
            sa.ForeignKey("memvault.triples.id"),
            nullable=True,
        ),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("confidence", sa.Float(), nullable=True),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("extra_metadata", JSONB(), nullable=True),
        schema="memvault",
    )

    # -----------------------------------------------------------------
    # 2. drop display_zh 欄位（反譯鏈路冗餘，translate_kg_zh.py 也刪除）
    # -----------------------------------------------------------------
    op.drop_column("triples", "display_zh", schema="memvault")

    # -----------------------------------------------------------------
    # 3. 重建 idx_blocks_fts GIN index：'english' → 'simple'
    #    'english' analyzer 對中文不分詞，中文化後 BM25 會歸零
    #    'simple' 純 unicode tokenize + lowercase，中英混排都能分詞
    # -----------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS memvault.idx_blocks_fts")
    op.execute(
        "CREATE INDEX idx_blocks_fts "
        "ON memvault.blocks USING gin (to_tsvector('simple', content))"
    )


def downgrade() -> None:
    # 反向：先 GIN index 還原 'english'，再 add display_zh，再 drop envelope
    op.execute("DROP INDEX IF EXISTS memvault.idx_blocks_fts")
    op.execute(
        "CREATE INDEX idx_blocks_fts "
        "ON memvault.blocks USING gin (to_tsvector('english', content))"
    )

    op.add_column(
        "triples",
        sa.Column("display_zh", sa.Text(), nullable=True),
        schema="memvault",
    )

    op.drop_column("triples", "extra_metadata", schema="memvault")
    op.drop_column("triples", "confidence", schema="memvault")
    op.drop_column("triples", "refs_triple_id", schema="memvault")
    op.drop_column("triples", "speaker_id", schema="memvault")
    op.drop_column("triples", "attribution", schema="memvault")
    op.drop_column("triples", "temporal", schema="memvault")
    op.drop_column("triples", "raw_quote", schema="memvault")
    op.drop_column("triples", "polarity", schema="memvault")
    op.drop_column("triples", "modality", schema="memvault")
    op.drop_column("triples", "kind", schema="memvault")
