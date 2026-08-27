import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_merchant_id", "merchant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    segment: Mapped[str] = mapped_column(String(100), nullable=False)
    relationship_start_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Synthetic ground truth only — hidden from ML models, used for generator validation.
    archetype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    true_recovery_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    true_promise_keep_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
