from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.agent.events import Event, EventType
from app.core.db import SessionLocal
from app.decision.policy import COOLDOWN_DAYS
from app.ml.features import load_raw_tables
from app.models import AccountState, PaymentPromise
from app.models.enums import AccountCurrentState, PromiseStatus

REVIEW_TIMEOUT_STATES = {
    AccountCurrentState.WAIT,
    AccountCurrentState.REMIND,
    AccountCurrentState.ESCALATE,
    AccountCurrentState.KEPT,
}

BROKEN_PROMISE_STATES = {AccountCurrentState.PROMISE}

assert REVIEW_TIMEOUT_STATES.isdisjoint(BROKEN_PROMISE_STATES), (
    "scan_for_review_timeouts and scan_for_broken_promises must never share a "
    "candidate state -- see this module's docstring for why that matters."
)


def _to_naive(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def scan_for_review_timeouts(as_of: datetime) -> list[Event]:
    """Invoices resting in WAIT/REMIND/ESCALATE/KEPT whose account_state row
    hasn't been touched in at least COOLDOWN_DAYS -- reusing the Policy
    Gate's own cooldown constant rather than inventing a parallel threshold:
    "reassess once the cooldown that was blocking further contact has
    elapsed" is the same idea, not a coincidence. Excludes DISPUTE_REVIEW
    (waiting on a human, not the automated system), PROMISE (a different
    scanner's job), OVERDUE (first contact is a separate, already-existing
    mechanism), and the CLOSED_* terminal states."""
    threshold = as_of - timedelta(days=COOLDOWN_DAYS)
    session = SessionLocal()
    try:
        rows = (
            session.execute(
                select(AccountState).where(
                    AccountState.current_state.in_(REVIEW_TIMEOUT_STATES),
                    AccountState.updated_at <= threshold,
                )
            )
            .scalars()
            .all()
        )
        return [Event(event_type=EventType.REVIEW_TIMEOUT, invoice_id=row.invoice_id, occurred_at=as_of) for row in rows]
    finally:
        session.close()


def scan_for_broken_promises(as_of: datetime, engine: Engine | None = None) -> list[Event]:
    """Open promises past their promised_date. Checks cumulative payments on
    the invoice since the promise was made against promised_amount before
    deciding this is genuinely broken -- a promise that's actually been
    kept (payment arrived, invoice not yet fully closed) must not be
    reported broken; that's KEPT's job (current_state==PROMISE plus a real
    payment event), not this scanner's."""
    as_of_naive = _to_naive(as_of)
    promised_date_cutoff = as_of_naive.date() if hasattr(as_of_naive, "date") else as_of

    tables = load_raw_tables(engine)
    payments = tables["payments"]

    session = SessionLocal()
    try:
        promises = (
            session.execute(
                select(PaymentPromise).where(
                    PaymentPromise.status == PromiseStatus.OPEN,
                    PaymentPromise.promised_date < promised_date_cutoff,
                )
            )
            .scalars()
            .all()
        )

        events = []
        for promise in promises:
            promise_created = _to_naive(promise.created_at)
            invoice_payments = payments[
                (payments["invoice_id"] == promise.invoice_id)
                & (payments["payment_date"] >= promise_created)
                & (payments["payment_date"] <= as_of_naive)
            ]
            total_paid = float(invoice_payments["amount"].sum())
            if total_paid >= float(promise.promised_amount):
                continue  # kept -- a real payment event handles/handled this, not a broken-promise scan

            events.append(
                Event(
                    event_type=EventType.PROMISE_BROKEN,
                    invoice_id=promise.invoice_id,
                    occurred_at=as_of,
                    payload={"promise_id": str(promise.id)},
                )
            )
        return events
    finally:
        session.close()
