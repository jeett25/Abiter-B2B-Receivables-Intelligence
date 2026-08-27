import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import ActionType, PolicyResult, action_type_enum, policy_result_enum


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"
    __table_args__ = (Index("ix_recovery_actions_invoice_id", "invoice_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(action_type_enum, nullable=False)
    expected_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    policy_result: Mapped[PolicyResult] = mapped_column(policy_result_enum, nullable=False)
    result: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
