"""fix account_current_state enum labels to match member names

Revision ID: b7fa2b3a4acb
Revises: 2f4bc391a33c
Create Date: 2026-08-29 18:53:58.298840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7fa2b3a4acb'
down_revision: Union[str, None] = '2f4bc391a33c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Corrects a real mistake in 2f4bc391a33c: account_current_state_enum
    # (app/models/enums.py) has no values_callable, so SQLAlchemy's default
    # Enum type stores each member's NAME ("OVERDUE", "WAIT", ...), not its
    # .value -- confirmed by querying pg_enum directly against the existing
    # labels. The prior migration added the lowercase .value strings
    # ('closed_paid'/'closed_abandoned'), which SQLAlchemy never actually
    # writes or reads; the real labels it uses are the uppercase names below.
    # The two lowercase labels from the prior migration are left in place as
    # harmless orphans -- Postgres has no ALTER TYPE ... DROP VALUE, and
    # removing them would require rebuilding the type and every column using
    # it, which isn't worth it for two inert, never-referenced labels.
    op.execute("ALTER TYPE account_current_state ADD VALUE IF NOT EXISTS 'CLOSED_PAID'")
    op.execute("ALTER TYPE account_current_state ADD VALUE IF NOT EXISTS 'CLOSED_ABANDONED'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE -- not implemented; see
    # 2f4bc391a33c's downgrade for the same limitation.
    pass
