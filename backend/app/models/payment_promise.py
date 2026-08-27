import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import PromiseStatus, promise_status_enum


class PaymentPromise(Base):
    __tablename__ = "payment_promises"
    __table_args__ = (
        Index("ix_payment_promises_invoice_id", "invoice_id"),
        Index("ix_payment_promises_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    promised_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    promised_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[PromiseStatus] = mapped_column(promise_status_enum, nullable=False, default=PromiseStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
