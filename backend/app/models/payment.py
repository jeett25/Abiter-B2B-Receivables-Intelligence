import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import PaymentStatus, payment_status_enum


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_invoice_id", "invoice_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(payment_status_enum, nullable=False, default=PaymentStatus.COMPLETED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
