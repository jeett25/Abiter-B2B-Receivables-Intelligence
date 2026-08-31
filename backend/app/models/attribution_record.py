import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import ActionType, TreatmentGroup, action_type_enum, treatment_group_enum


class AttributionRecord(Base):
    __tablename__ = "attribution_records"

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), primary_key=True)
    treatment_group: Mapped[TreatmentGroup] = mapped_column(treatment_group_enum, nullable=False)
    baseline_predicted_recovery: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observed_recovery: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Nullable: never a per-invoice causal number (a single invoice is either
    # treatment or control, never both -- its individual treatment effect is
    # unobservable). The real incremental-recovery figure is a GROUP
    # comparison computed separately -- see app/attribution/DECISIONS.md.
    incremental_recovery: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # The real action dispatched -- treatment rows only, NULL for control.
    action: Mapped[ActionType | None] = mapped_column(action_type_enum, nullable=True)
    # What the engine would have chosen -- control rows only (computed for
    # reporting/stratification, never fed back into control's simulated
    # outcome). NULL for treatment rows, whose `action` above already answers this.
    counterfactual_action: Mapped[ActionType | None] = mapped_column(action_type_enum, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
