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

# app/attribution/persist.py's LEDGER_PAYMENT_METHOD and
# app/agent/simulate_scenarios.py's Scenario A payment method -- the only 2
# non-organic payment methods in the codebase (see synthetic/seed_demo.py's
# own SYNTHETIC_PAYMENT_METHODS for the same pair). Timeline is a viewer-
# facing surface with no source-code context, so the raw enum string
# ("...via attribution_simulation") reads as a debug artifact, not a real
# payment -- translated to a plain sentence instead. Deliberately doesn't
# claim "no intervention": attribution_simulation is written for BOTH
# control (organic) and treatment (post-action) arm recoveries, so the copy
# stays accurate for either without needing an extra query to know which.
# Deliberately generic (2026-09-03: dropped "Day-5", an internal build-day
# reference a reader outside the project has no way to interpret) -- same
# wording family as app/attribution/persist.py's CLOSING_ENTRY_MARKER.
_SYNTHETIC_PAYMENT_SUMMARY = {
    "attribution_simulation": "recovered as part of a randomized control-group experiment, not a live transaction",
    "scenario_rehearsal": "injected for this demo rehearsal, not a live transaction",
}


@router.get("/{invoice_id}/decision", response_model=DecisionTrace)
def get_decision(invoice_id: UUID, db: Annotated[Session, Depends(get_db)]):
    invoice_row = db.execute(
        select(Invoice.invoice_number, Invoice.amount, Customer.company_name)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(Invoice.id == invoice_id)
    ).first()
    if invoice_row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # All rows, most recent first -- decision_logs is append-only with no
    # dedup (see docs/agent-DECISIONS.md's Idempotency entry), so more than
    # one row can exist for an invoice if it was ever reprocessed.
    # `timestamp` alone can't break ties (every invoice in the same batch
    # run shares the same business timestamp) -- `created_at` (real
    # wall-clock insert time, added 2026-09-02) is the real tiebreaker;
    # ordering by timestamp first still matters for a genuinely different
    # `as_of` re-run. Fetching all (typically 1-3) rather than just the
    # latest is what makes the fallback-merge below possible without a
    # second query or JSONB-operator SQL.
    logs = (
        db.execute(
            select(DecisionLog)
            .where(DecisionLog.invoice_id == invoice_id)
            .order_by(DecisionLog.timestamp.desc(), DecisionLog.created_at.desc())
        )
        .scalars()
        .all()
    )
    if not logs:
        raise HTTPException(status_code=404, detail="No decision recorded for this invoice yet")

    log = logs[0]
    model_scores = log.model_scores
    evidence = log.evidence
    assessed_at: datetime | None = None

    # A "bare closing entry" (build_closing_decision_log() in
    # app/attribution/persist.py) has all three model_scores keys
    # explicitly None -- honest about not being a fresh assessment, but it
    # means the Invoice Detail page's predictive/economics/retrieval panels
    # go empty for every one of the ~509 invoices closed this way, even
    # though a real prior assessment (with real scores) almost always
    # exists right before it. Fall back to the most recent EARLIER row that
    # has at least one real score, and surface when that happened via
    # assessed_at so the frontend can label it as "from an earlier
    # assessment" rather than silently implying it's current.
    is_bare = all(
        (log.model_scores or {}).get(key) is None for key in ("recovery_probability", "ptp_probability", "root_cause")
    )
    if is_bare:
        for prior in logs[1:]:
            has_real_score = any(
                (prior.model_scores or {}).get(key) is not None
                for key in ("recovery_probability", "ptp_probability", "root_cause")
            )
            if has_real_score:
                model_scores = prior.model_scores
                evidence = prior.evidence
                assessed_at = prior.timestamp
                break

    return DecisionTrace(
        invoice_id=invoice_id,
        invoice_number=invoice_row.invoice_number,
        customer_name=invoice_row.company_name,
        amount=float(invoice_row.amount),
        decision=log.decision,
        model_scores=model_scores,
        evidence=evidence,
        policy_checks=log.policy_checks,
        reason=log.reason,
        timestamp=log.timestamp,
        assessed_at=assessed_at,
    )


@router.get("/{invoice_id}/timeline", response_model=InvoiceTimeline)
def get_timeline(invoice_id: UUID, db: Annotated[Session, Depends(get_db)]):
    invoice_exists = db.execute(select(Invoice.id).where(Invoice.id == invoice_id)).first()
    if invoice_exists is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    logs = (
        db.execute(
            select(DecisionLog)
            .where(DecisionLog.invoice_id == invoice_id)
            .order_by(DecisionLog.timestamp, DecisionLog.created_at)
        )
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
        # state_transition_path is only ever populated by the Day-4 agent
        # shape (app/agent/audit.py) -- absent (not an empty list) on the
        # one invoice still written by Day-3's persist.py path, since that
        # shape never computed one. .get() rather than indexing so this
        # degrades to the plain decision/reason summary either way.
        detail: dict = {"decision": log.decision, "reason": log.reason}
        state_transition_path = log.policy_checks.get("state_transition_path")
        if state_transition_path:
            detail["state_transition_path"] = state_transition_path
        events.append(
            TimelineEntry(
                timestamp=log.timestamp,
                type="decision",
                summary=f"{log.decision} -- {log.reason}",
                detail=detail,
            )
        )
    for payment in payments:
        # payment_date is a Date, not a datetime -- normalized to UTC
        # midnight so it sorts correctly alongside decision_logs' real
        # timestamps in one chronological list.
        ts = datetime(payment.payment_date.year, payment.payment_date.month, payment.payment_date.day, tzinfo=timezone.utc)
        synthetic_note = _SYNTHETIC_PAYMENT_SUMMARY.get(payment.method)
        summary = (
            f"Payment of Rs.{payment.amount:,.2f} -- {synthetic_note}"
            if synthetic_note
            else f"Payment of Rs.{payment.amount:,.2f} via {payment.method}"
        )
        events.append(
            TimelineEntry(
                timestamp=ts,
                type="payment",
                summary=summary,
                detail={"amount": float(payment.amount), "method": payment.method},
            )
        )

    events.sort(key=lambda e: e.timestamp)
    return InvoiceTimeline(invoice_id=invoice_id, events=events)
