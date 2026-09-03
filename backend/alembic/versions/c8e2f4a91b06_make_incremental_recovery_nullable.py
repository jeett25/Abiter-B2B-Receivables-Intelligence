"""make attribution_records.incremental_recovery nullable

Revision ID: c8e2f4a91b06
Revises: a3f9c1d84e27
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e2f4a91b06'
down_revision: Union[str, None] = 'a3f9c1d84e27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # incremental_recovery is never a per-invoice causal number (see
    # docs/attribution-DECISIONS.md) -- Day 5's persistence writes NULL here
    # for every row; the real incremental-recovery figure is a group-level
    # aggregate computed separately, not stored per attribution_records row.
    op.alter_column('attribution_records', 'incremental_recovery', nullable=True)


def downgrade() -> None:
    op.alter_column('attribution_records', 'incremental_recovery', nullable=False)
