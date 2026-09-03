import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import ActionType, action_type_enum


class AttributionExperimentResult(Base):
    """One row per (experiment_id, segment, action) aggregate slice.
    segment=NULL means pooled across segments; action=NULL means pooled
    across actions -- (segment=NULL, action=NULL) is the portfolio headline
    row. See docs/attribution-DECISIONS.md for why this shape (not two
    separate tables) was chosen, and why incremental_recovery_rate/amount
    here -- not attribution_records.incremental_recovery -- is the real
    treatment-vs-control comparison."""

    __tablename__ = "attribution_experiment_results"
    __table_args__ = (Index("ix_attribution_experiment_results_experiment_id", "experiment_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    segment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[ActionType | None] = mapped_column(action_type_enum, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    treatment_n: Mapped[int] = mapped_column(Integer, nullable=False)
    control_n: Mapped[int] = mapped_column(Integer, nullable=False)
    # Amount-weighted (recovered_amount / total_amount) -- the dollar-consistent
    # basis, matching app/decision/evaluation.py's own recovery_rate. See
    # DECISIONS.md for why this must never be mixed with the COUNT-based
    # rates below.
    treatment_recovery_rate: Mapped[float] = mapped_column(Float, nullable=False)
    control_recovery_rate: Mapped[float] = mapped_column(Float, nullable=False)
    incremental_recovery_rate: Mapped[float] = mapped_column(Float, nullable=False)
    # COUNT-based (fraction of invoices recovered) -- the natural basis for a
    # binomial standard error, deliberately kept separate from the
    # amount-weighted rates above. Nullable: undefined when either arm has 0
    # invoices in this slice.
    treatment_count_recovery_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    control_count_recovery_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_rate_diff_se: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_rate_diff_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    treatment_recovered_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    control_recovered_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    incremental_recovered_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    treatment_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    treatment_friction: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    incremental_net_recovery: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
