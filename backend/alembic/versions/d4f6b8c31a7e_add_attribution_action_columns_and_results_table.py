"""add attribution_records action columns and attribution_experiment_results table

Revision ID: d4f6b8c31a7e
Revises: c8e2f4a91b06
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4f6b8c31a7e'
down_revision: Union[str, None] = 'c8e2f4a91b06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTION_TYPE_VALUES = ('WAIT', 'EMAIL', 'WHATSAPP', 'PAYMENT_LINK', 'VOICE', 'ESCALATE', 'STOP')


def upgrade() -> None:
    # action_type already exists (created in f77b57a510b7) -- create_type=False
    # on both, same convention as recovery_actions.action_type in that same
    # migration (gotcha #1 in CLAUDE.md: a shared enum re-created by a second
    # table's op.create_table/add_column raises DuplicateObject).
    action_type_col = postgresql.ENUM(*_ACTION_TYPE_VALUES, name='action_type', create_type=False)
    op.add_column('attribution_records', sa.Column('action', action_type_col, nullable=True))
    # Populated for CONTROL rows only -- what the engine would have chosen,
    # computed for reporting/stratification, never fed back into control's
    # simulated outcome. NULL for treatment rows (their `action` column
    # above already gives the real answer). See app/attribution/DECISIONS.md.
    op.add_column(
        'attribution_records',
        sa.Column('counterfactual_action', postgresql.ENUM(*_ACTION_TYPE_VALUES, name='action_type', create_type=False), nullable=True),
    )

    op.create_table(
        'attribution_experiment_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('experiment_id', sa.String(100), nullable=False),
        # NULL segment = pooled across segments; NULL action = pooled across
        # actions. (segment=NULL, action=NULL) is the portfolio headline row.
        sa.Column('segment', sa.String(100), nullable=True),
        sa.Column('action', postgresql.ENUM(*_ACTION_TYPE_VALUES, name='action_type', create_type=False), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('treatment_n', sa.Integer, nullable=False),
        sa.Column('control_n', sa.Integer, nullable=False),
        sa.Column('treatment_recovery_rate', sa.Float, nullable=False),
        sa.Column('control_recovery_rate', sa.Float, nullable=False),
        sa.Column('incremental_recovery_rate', sa.Float, nullable=False),
        sa.Column('treatment_recovered_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('control_recovered_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('incremental_recovered_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('treatment_cost', sa.Numeric(14, 2), nullable=False),
        sa.Column('treatment_friction', sa.Numeric(14, 2), nullable=False),
        sa.Column('incremental_net_recovery', sa.Numeric(14, 2), nullable=False),
    )
    op.create_index(
        'ix_attribution_experiment_results_experiment_id',
        'attribution_experiment_results',
        ['experiment_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_attribution_experiment_results_experiment_id', table_name='attribution_experiment_results')
    op.drop_table('attribution_experiment_results')
    op.drop_column('attribution_records', 'counterfactual_action')
    op.drop_column('attribution_records', 'action')
