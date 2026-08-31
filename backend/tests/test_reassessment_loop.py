"""Subtask 8 checkpoint: the two named end-to-end scenarios.

Both require a real live invoice and, for scenario A, a real Groq call
(skipped gracefully if LLM_API_KEY isn't configured, same treatment as
Subtask 7's tests). Each picks its own dedicated invoice via a distinct
query to avoid interfering with other tests' shared live-pool assumptions.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.agent.scanners import scan_for_broken_promises
from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Invoice, Payment, PaymentPromise
from app.models.enums import AccountCurrentState, InvoiceStatus, PromiseStatus

requires_groq_key = pytest.mark.skipif(not settings.llm_api_key, reason="LLM_API_KEY not configured")

DAY1 = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
DAY10 = DAY1 + timedelta(days=10)


def _pick_undisputed_live_invoice(offset: int):
    session = SessionLocal()
    try:
        return session.execute(
            select(Invoice.id)
            .where(Invoice.status == InvoiceStatus.OPEN)
            .where(Invoice.true_root_cause != "dispute")
            .offset(offset)
            .limit(1)
        ).scalar_one()
    finally:
        session.close()


@requires_groq_key
def test_overdue_promise_broken_reassess(db_session):
    invoice_id = _pick_undisputed_live_invoice(offset=100)

    # -- promise: customer commits to a date well before DAY10 --
    promise_event = Event(
        event_type=EventType.CUSTOMER_RESPONDED,
        invoice_id=invoice_id,
        occurred_at=DAY1,
        payload={"channel": "whatsapp", "transcript": "I'll pay Rs 50,000 this Friday."},
    )
    promise_result = run_invoice(invoice_id, event=promise_event)
    assert promise_result["event"].event_type == EventType.PROMISE_CREATED
    assert promise_result["next_state"] == AccountCurrentState.PROMISE

    session = SessionLocal()
    try:
        promise = session.execute(
            select(PaymentPromise).where(PaymentPromise.invoice_id == invoice_id, PaymentPromise.status == PromiseStatus.OPEN)
        ).scalars().one()
        assert promise.promised_date < DAY10.date()  # the promised Friday is well before DAY10
    finally:
        session.close()

    # -- broken: no payment ever arrived, and DAY10 is well past the promised date --
    broken_events = scan_for_broken_promises(DAY10)
    matching = [e for e in broken_events if e.invoice_id == invoice_id]
    assert len(matching) == 1
    broken_event = matching[0]
    assert broken_event.event_type == EventType.PROMISE_BROKEN

    # -- reassess: a fresh action is chosen, not stuck at BROKEN/REASSESS --
    reassess_result = run_invoice(invoice_id, event=broken_event)
    assert AccountCurrentState.BROKEN in reassess_result["state_transition_path"]
    assert AccountCurrentState.REASSESS in reassess_result["state_transition_path"]
    assert reassess_result["next_state"] not in (AccountCurrentState.PROMISE, AccountCurrentState.BROKEN)


def test_overdue_action_payment_closed_paid(db_session):
    invoice_id = _pick_undisputed_live_invoice(offset=101)

    session = SessionLocal()
    try:
        invoice_amount = session.execute(select(Invoice.amount).where(Invoice.id == invoice_id)).scalar_one()
    finally:
        session.close()

    # -- overdue: an ordinary first assessment happens --
    overdue_event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DAY1)
    overdue_result = run_invoice(invoice_id, event=overdue_event)
    assert overdue_result["next_state"] != AccountCurrentState.CLOSED_PAID

    # -- payment: the ledger reflects a real, full payment (a real system's
    # payment gateway/webhook would write this row -- outside this graph's
    # scope, exactly like load_context already assumes for is_actually_paid).
    # DAY10 (2026-09-03) is after synthetic.generator.REFERENCE_DATE
    # (2026-08-27) by construction (this test simulates a payment arriving
    # after "today"), so this row is cleaned up in `finally` below --
    # otherwise it permanently fails synthetic/validators.py's
    # temporal-consistency check on every subsequent full-suite run.
    session = SessionLocal()
    try:
        payment = Payment(invoice_id=invoice_id, amount=Decimal(str(invoice_amount)), payment_date=DAY10.date(), method="upi")
        session.add(payment)
        session.commit()
        payment_id = payment.id
    finally:
        session.close()

    try:
        payment_event = Event(
            event_type=EventType.PAYMENT_RECEIVED,
            invoice_id=invoice_id,
            occurred_at=DAY10,
            payload={"amount": float(invoice_amount), "payment_date": DAY10.date().isoformat(), "method": "upi"},
        )
        payment_result = run_invoice(invoice_id, event=payment_event)

        assert payment_result["is_actually_paid"] is True
        assert payment_result["next_state"] == AccountCurrentState.CLOSED_PAID
    finally:
        cleanup_session = SessionLocal()
        try:
            cleanup_session.execute(delete(Payment).where(Payment.id == payment_id))
            cleanup_session.commit()
        finally:
            cleanup_session.close()
