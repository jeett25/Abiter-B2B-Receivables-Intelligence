import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import InvoiceStatus, invoice_status_enum


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_customer_id", "customer_id"),
        Index("ix_invoices_due_date_status", "due_date", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    # Human-readable label (e.g. "INV-1042") for demo/dashboard display — the
    # UUID stays the real key, this is purely so a judge can track an invoice
    # by eye on screen instead of watching a UUID scroll by.
    invoice_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(invoice_status_enum, nullable=False, default=InvoiceStatus.OPEN)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Synthetic ground truth only — hidden from ML models, used for generator validation
    # and as the label a future root-cause classification stage would be graded against.
    # One of: cash_flow_stress / dispute / oversight.
    true_root_cause: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
