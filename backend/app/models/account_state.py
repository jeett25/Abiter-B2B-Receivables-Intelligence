import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import AccountCurrentState, ActionType, account_current_state_enum, action_type_enum


class AccountState(Base):
    __tablename__ = "account_state"
    __table_args__ = (Index("ix_account_state_current_state", "current_state"),)

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), primary_key=True)
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    current_state: Mapped[AccountCurrentState] = mapped_column(account_current_state_enum, nullable=False)
    recoverability_score: Mapped[float] = mapped_column(Float, nullable=False)
    promise_score: Mapped[float] = mapped_column(Float, nullable=False)
    expected_payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    revenue_at_risk: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    next_action: Mapped[ActionType | None] = mapped_column(action_type_enum, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
