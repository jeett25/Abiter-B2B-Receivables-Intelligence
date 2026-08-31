"""add significance columns to attribution_experiment_results

Revision ID: e7a2c5d9f014
Revises: d4f6b8c31a7e
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a2c5d9f014'
down_revision: Union[str, None] = 'd4f6b8c31a7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # COUNT-based recovery rates (fraction of invoices, not amount-weighted --
    # deliberately a different basis from treatment_recovery_rate/
    # control_recovery_rate above, which are amount-weighted for the dollar
    # figures. Mixing these two bases was exactly the bug fixed in subtask 4;
    # see app/attribution/DECISIONS.md) plus a lightweight two-proportion
    # standard error / z-score for informal noise calibration -- nullable,
    # since a slice with 0 invoices in either arm has no defined SE/z.
    op.add_column('attribution_experiment_results', sa.Column('treatment_count_recovery_rate', sa.Float, nullable=True))
    op.add_column('attribution_experiment_results', sa.Column('control_count_recovery_rate', sa.Float, nullable=True))
    op.add_column('attribution_experiment_results', sa.Column('recovery_rate_diff_se', sa.Float, nullable=True))
    op.add_column('attribution_experiment_results', sa.Column('recovery_rate_diff_z', sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column('attribution_experiment_results', 'recovery_rate_diff_z')
    op.drop_column('attribution_experiment_results', 'recovery_rate_diff_se')
    op.drop_column('attribution_experiment_results', 'control_count_recovery_rate')
    op.drop_column('attribution_experiment_results', 'treatment_count_recovery_rate')
