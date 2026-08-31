from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import DecisionTrace, InvoiceTimeline, TimelineEntry
from app.models import Customer, DecisionLog, Invoice, Payment

router = APIRouter(prefix="/api/invoices", tags=["decisions"])


@router.get("/{invoice_id}/decision", response_model=DecisionTrace)
def get_decision(invoice_id: UUID, db: Annotated[Session, Depends(get_db)]):
    invoice_row = db.execute(
        select(Invoice.invoice_number, Invoice.amount, Customer.company_name)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(Invoice.id == invoice_id)
    ).first()
    if invoice_row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Most recent row -- decision_logs is append-only with no dedup (see
    # app/agent/DECISIONS.md's Idempotency entry), so more than one row can
    # exist for an invoice if it was ever reprocessed.
    log = (
        db.execute(
            select(DecisionLog)
            .where(DecisionLog.invoice_id == invoice_id)
            .order_by(DecisionLog.timestamp.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if log is None:
        raise HTTPException(status_code=404, detail="No decision recorded for this invoice yet")

    return DecisionTrace(
        invoice_id=invoice_id,
        invoice_number=invoice_row.invoice_number,
        customer_name=invoice_row.company_name,
        amount=float(invoice_row.amount),
        decision=log.decision,
        model_scores=log.model_scores,
        evidence=log.evidence,
        policy_checks=log.policy_checks,
        reason=log.reason,
        timestamp=log.timestamp,
    )


@router.get("/{invoice_id}/timeline", response_model=InvoiceTimeline)
def get_timeline(invoice_id: UUID, db: Annotated[Session, Depends(get_db)]):
    invoice_exists = db.execute(select(Invoice.id).where(Invoice.id == invoice_id)).first()
    if invoice_exists is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    logs = (
        db.execute(select(DecisionLog).where(DecisionLog.invoice_id == invoice_id).order_by(DecisionLog.timestamp))
        .scalars()
        .all()
    )
    payments = (
        db.execute(select(Payment).where(Payment.invoice_id == invoice_id).order_by(Payment.payment_date))
        .scalars()
        .all()
    )

    events: list[TimelineEntry] = []
    for log in logs:
        events.append(
            TimelineEntry(
                timestamp=log.timestamp,
                type="decision",
                summary=f"{log.decision} -- {log.reason}",
                detail={"decision": log.decision, "reason": log.reason},
            )
        )
    for payment in payments:
        # payment_date is a Date, not a datetime -- normalized to UTC
        # midnight so it sorts correctly alongside decision_logs' real
        # timestamps in one chronological list.
        ts = datetime(payment.payment_date.year, payment.payment_date.month, payment.payment_date.day, tzinfo=timezone.utc)
        events.append(
            TimelineEntry(
                timestamp=ts,
                type="payment",
                summary=f"Payment of Rs.{payment.amount:,.2f} via {payment.method}",
                detail={"amount": float(payment.amount), "method": payment.method},
            )
        )

    events.sort(key=lambda e: e.timestamp)
    return InvoiceTimeline(invoice_id=invoice_id, events=events)
