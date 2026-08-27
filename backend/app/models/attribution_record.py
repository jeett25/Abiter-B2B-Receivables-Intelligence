import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import TreatmentGroup, treatment_group_enum


class AttributionRecord(Base):
    __tablename__ = "attribution_records"

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), primary_key=True)
    treatment_group: Mapped[TreatmentGroup] = mapped_column(treatment_group_enum, nullable=False)
    baseline_predicted_recovery: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observed_recovery: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    incremental_recovery: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
