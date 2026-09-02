import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DecisionLog(Base):
    __tablename__ = "decision_logs"
    __table_args__ = (Index("ix_decision_logs_invoice_id", "invoice_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(100), nullable=False)
    model_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    policy_checks: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # `timestamp` is the business/event moment (identical across an entire
    # batch run -- every invoice in the same final_integration_pass shares
    # it), so it can't disambiguate "which row is actually newest" when an
    # invoice has been reprocessed more than once. `created_at` is the real
    # wall-clock insert time (server_default, DB-assigned) -- added
    # 2026-09-02 after this ambiguity caused the API to non-deterministically
    # serve a stale decision_logs row for some invoices (see migration).
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
