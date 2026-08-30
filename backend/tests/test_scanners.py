"""app/agent/scanners.py tests.

Tested against real, directly-seeded rows -- this project's established
pattern for DB-touching tests (e.g. test_decision_persist.py's documented
side effect), not mocked. Each test picks its own dedicated live invoice
(via a distinct offset) to avoid interfering with other tests' assumptions
about shared live-pool state.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.agent.events import EventType
from app.agent.scanners import (
    BROKEN_PROMISE_STATES,
    REVIEW_TIMEOUT_STATES,
    scan_for_broken_promises,
    scan_for_review_timeouts,
)
from app.core.db import SessionLocal
from app.decision.policy import COOLDOWN_DAYS
from app.models import AccountState, Invoice, Payment, PaymentPromise
from app.models.enums import AccountCurrentState, InvoiceStatus, PromiseStatus

AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def test_review_timeout_and_broken_promise_states_are_disjoint():
    """Regression test for the module's own invariant assertion -- proven
    directly, not just by inspection, so a future edit to either state set
    can't silently reopen a double-fire path."""
    assert REVIEW_TIMEOUT_STATES.isdisjoint(BROKEN_PROMISE_STATES)


def _pick_live_invoice(offset: int):
    session = SessionLocal()
    try:
        return session.execute(
            select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).offset(offset).limit(1)
        ).scalar_one()
    finally:
        session.close()


def _set_account_state(invoice_id, current_state: AccountCurrentState, updated_at: datetime) -> None:
    session = SessionLocal()
    try:
        session.execute(
            AccountState.__table__.update()
            .where(AccountState.invoice_id == invoice_id)
            .values(current_state=current_state, updated_at=updated_at)
        )
        session.commit()
    finally:
        session.close()


def test_scan_for_review_timeouts_finds_invoices_past_cooldown():
    invoice_id = _pick_live_invoice(offset=50)
    _set_account_state(invoice_id, AccountCurrentState.WAIT, AS_OF - timedelta(days=COOLDOWN_DAYS + 1))

    events = scan_for_review_timeouts(AS_OF)
    assert any(e.invoice_id == invoice_id and e.event_type == EventType.REVIEW_TIMEOUT for e in events)


def test_scan_for_review_timeouts_excludes_invoices_within_cooldown():
    invoice_id = _pick_live_invoice(offset=51)
    _set_account_state(invoice_id, AccountCurrentState.WAIT, AS_OF - timedelta(days=1))

    events = scan_for_review_timeouts(AS_OF)
    assert not any(e.invoice_id == invoice_id for e in events)


def test_scan_for_review_timeouts_excludes_dispute_review():
    invoice_id = _pick_live_invoice(offset=52)
    _set_account_state(invoice_id, AccountCurrentState.DISPUTE_REVIEW, AS_OF - timedelta(days=COOLDOWN_DAYS + 30))

    events = scan_for_review_timeouts(AS_OF)
    assert not any(e.invoice_id == invoice_id for e in events)


def _reset_promises(session, invoice_id) -> None:
    session.execute(PaymentPromise.__table__.delete().where(PaymentPromise.invoice_id == invoice_id))


def test_scan_for_broken_promises_finds_an_unpaid_expired_promise():
    invoice_id = _pick_live_invoice(offset=53)
    session = SessionLocal()
    try:
        _reset_promises(session, invoice_id)
        session.add(
            PaymentPromise(
                invoice_id=invoice_id,
                promised_amount=Decimal("50000.00"),
                promised_date=date(2026, 8, 20),
                source="whatsapp",
                confidence_score=0.6,
                status=PromiseStatus.OPEN,
            )
        )
        session.commit()
    finally:
        session.close()

    events = scan_for_broken_promises(AS_OF)
    assert any(e.invoice_id == invoice_id and e.event_type == EventType.PROMISE_BROKEN for e in events)
    matching = [e for e in events if e.invoice_id == invoice_id][0]
    assert "promise_id" in matching.payload


def test_scan_for_broken_promises_skips_a_promise_that_was_actually_paid():
    invoice_id = _pick_live_invoice(offset=54)
    promise_created = AS_OF - timedelta(days=10)
    session = SessionLocal()
    try:
        _reset_promises(session, invoice_id)
        session.add(
            PaymentPromise(
                invoice_id=invoice_id,
                promised_amount=Decimal("1000.00"),  # deliberately tiny so any real payment covers it
                promised_date=date(2026, 8, 20),
                source="whatsapp",
                confidence_score=0.6,
                status=PromiseStatus.OPEN,
                created_at=promise_created,
            )
        )
        session.add(
            Payment(invoice_id=invoice_id, amount=Decimal("1000.00"), payment_date=date(2026, 8, 22), method="bank_transfer")
        )
        session.commit()
    finally:
        session.close()

    events = scan_for_broken_promises(AS_OF)
    assert not any(e.invoice_id == invoice_id for e in events)


def test_scan_for_broken_promises_ignores_promises_not_yet_due():
    invoice_id = _pick_live_invoice(offset=55)
    session = SessionLocal()
    try:
        _reset_promises(session, invoice_id)
        session.add(
            PaymentPromise(
                invoice_id=invoice_id,
                promised_amount=Decimal("50000.00"),
                promised_date=date(2026, 9, 15),  # after AS_OF -- not due yet
                source="whatsapp",
                confidence_score=0.6,
                status=PromiseStatus.OPEN,
            )
        )
        session.commit()
    finally:
        session.close()

    events = scan_for_broken_promises(AS_OF)
    assert not any(e.invoice_id == invoice_id for e in events)
