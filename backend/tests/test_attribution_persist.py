"""app/attribution/persist.py tests: pure build_attribution_record() checks,
plus integration tests against the real live pool using an uncommitted,
rolled-back session -- persist_experiment_outcome()'s DB effects are
verified without ever actually committing them, since attribution_records'
primary key (invoice_id) fails loudly on a duplicate insert rather than
tolerating a rerun the way decision_logs does (see DECISIONS.md), so a real
commit here would break on the suite's second run. persist_experiment_outcomes()
(the committing wrapper) is intentionally not exercised for real -- it's a
thin loop+commit around the already-tested persist_experiment_outcome()."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.attribution.persist import build_attribution_record, persist_experiment_outcome
from app.attribution.simulate_outcomes import SimulatedOutcome
from app.core.db import SessionLocal
from app.models import AccountState, AttributionRecord, Invoice
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus, TreatmentGroup


def _outcome(
    invoice_id,
    recovered,
    group=TreatmentGroup.CONTROL,
    amount=50_000.0,
    base_probability=0.6,
    action=ActionType.WAIT,
    counterfactual_action=None,
):
    return SimulatedOutcome(
        invoice_id=invoice_id,
        group=group,
        action=action,
        counterfactual_action=counterfactual_action,
        amount=amount,
        base_probability=base_probability,
        recovered=recovered,
        recovered_amount=amount if recovered else 0.0,
        recovery_date=date(2026, 9, 10) if recovered else None,
        ledger_payment_date=date(2026, 8, 26) if recovered else None,
    )


def test_build_attribution_record_maps_fields_and_leaves_incremental_null():
    outcome = _outcome(
        uuid.uuid4(),
        recovered=True,
        group=TreatmentGroup.ACTED,
        amount=40_000.0,
        base_probability=0.5,
        action=ActionType.ESCALATE,
    )
    record = build_attribution_record(outcome)

    assert record.invoice_id == outcome.invoice_id
    assert record.treatment_group == TreatmentGroup.ACTED
    assert record.baseline_predicted_recovery == Decimal("20000.00")  # 0.5 * 40,000
    assert record.observed_recovery == Decimal("40000.00")
    assert record.incremental_recovery is None
    assert record.action == ActionType.ESCALATE
    assert record.counterfactual_action is None


def test_build_attribution_record_control_stores_counterfactual_not_action():
    outcome = _outcome(
        uuid.uuid4(),
        recovered=False,
        group=TreatmentGroup.CONTROL,
        counterfactual_action=ActionType.WHATSAPP,
    )
    record = build_attribution_record(outcome)

    assert record.action is None  # control's real `action` (always WAIT) is never stored
    assert record.counterfactual_action == ActionType.WHATSAPP


def test_build_attribution_record_not_recovered_has_zero_observed_recovery():
    outcome = _outcome(uuid.uuid4(), recovered=False, amount=15_000.0, base_probability=0.3)
    record = build_attribution_record(outcome)

    assert record.observed_recovery == Decimal("0.00")
    assert record.baseline_predicted_recovery == Decimal("4500.00")  # 0.3 * 15,000
    assert record.incremental_recovery is None


def _pick_invoice_without_attribution_record(session, offset: int):
    """The pool this draws from is small and fixed: only the ~88 invoices
    the real experiment excluded (already-paid/disputed) lack an
    attribution_records row at all -- every other live invoice has one
    since the real `python -m app.attribution.persist` run. offset must
    stay well within that pool; it was originally 300/301, which
    overshot once the real persist ran and is what NoResultFound was
    catching."""
    return session.execute(
        select(Invoice.id)
        .where(Invoice.status == InvoiceStatus.OPEN)
        .where(~Invoice.id.in_(select(AttributionRecord.invoice_id)))
        .offset(offset)
        .limit(1)
    ).scalar_one()


def test_persist_experiment_outcome_recovered_writes_ledger_and_attribution_record(db_session):
    session = SessionLocal()
    try:
        invoice_id = _pick_invoice_without_attribution_record(session, offset=0)
        outcome = _outcome(invoice_id, recovered=True, group=TreatmentGroup.ACTED, amount=75_000.0, base_probability=0.7)

        persist_experiment_outcome(outcome, session)
        session.flush()

        record = session.get(AttributionRecord, invoice_id)
        assert record.treatment_group == TreatmentGroup.ACTED
        assert record.observed_recovery == Decimal("75000.00")
        assert record.incremental_recovery is None

        invoice = session.get(Invoice, invoice_id)
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.paid_at.date() == date(2026, 8, 26)

        account_state = session.get(AccountState, invoice_id)
        assert account_state.current_state == AccountCurrentState.CLOSED_PAID
        assert account_state.recoverability_score == 0.7
        assert account_state.revenue_at_risk == Decimal("0.00")
        assert account_state.next_action == ActionType.STOP
    finally:
        session.rollback()  # never committed -- see module docstring
        session.close()


def test_persist_experiment_outcome_not_recovered_touches_only_attribution_record(db_session):
    session = SessionLocal()
    try:
        invoice_id = _pick_invoice_without_attribution_record(session, offset=1)

        before_invoice_status = session.get(Invoice, invoice_id).status
        before_account_state = session.get(AccountState, invoice_id).current_state
        session.expunge_all()  # force fresh reads after persist_experiment_outcome below

        outcome = _outcome(invoice_id, recovered=False, group=TreatmentGroup.CONTROL, amount=30_000.0, base_probability=0.4)
        persist_experiment_outcome(outcome, session)
        session.flush()

        record = session.get(AttributionRecord, invoice_id)
        assert record.observed_recovery == Decimal("0.00")

        invoice = session.get(Invoice, invoice_id)
        assert invoice.status == before_invoice_status

        account_state = session.get(AccountState, invoice_id)
        assert account_state.current_state == before_account_state
    finally:
        session.rollback()
        session.close()
