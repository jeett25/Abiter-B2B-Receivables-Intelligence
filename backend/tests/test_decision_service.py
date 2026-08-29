"""app/decision/service.py tests -- integration tests against the real dev
DB and the persisted Day-2 model artifacts."""
from sqlalchemy import func, select

from app.core.db import engine
from app.decision.service import DEFAULT_AS_OF, decide, run_full_live_pass
from app.ml.config import CALIBRATED_PROBABILITY_CEILING, CALIBRATED_PROBABILITY_FLOOR
from app.models import Customer, Invoice
from app.models.enums import ActionType, InvoiceStatus, PolicyResult


def test_default_as_of_is_consistent_with_live_pool_date_range(db_session):
    """Drift-detection guard, not just a comment: if synthetic/generator.py's
    REFERENCE_DATE is ever changed without updating DEFAULT_AS_OF to match,
    this fails immediately instead of live/historical data silently
    disagreeing about "now". Every live invoice's due_date must fall before
    DEFAULT_AS_OF, per the generator's own LIVE_WINDOW_END = REFERENCE_DATE - 1d."""
    max_due_date = db_session.execute(
        select(func.max(Invoice.due_date)).where(Invoice.status == InvoiceStatus.OPEN)
    ).scalar_one()
    assert max_due_date < DEFAULT_AS_OF.date()


def test_decide_returns_a_sane_decision_for_a_real_live_invoice(db_session):
    live_invoice_id = db_session.execute(
        select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).limit(1)
    ).scalar_one()

    decision = decide(live_invoice_id, engine=engine)

    assert CALIBRATED_PROBABILITY_FLOOR <= decision.base_probability <= CALIBRATED_PROBABILITY_CEILING
    assert decision.amount > 0
    assert isinstance(decision.final_action, ActionType)
    assert isinstance(decision.policy_verdict.result, PolicyResult)
    assert len(decision.economics_ranking) > 0
    assert ActionType.STOP not in [ev.action_type for ev in decision.economics_ranking]


def test_already_paid_false_alarm_invoice_is_stopped_via_actual_payments_not_status(db_session):
    """The exact mechanism the already_paid_false_alarm archetype was built
    to test: invoices.status stays 'open' (reconciliation lag), so the
    Policy Gate must catch this by cross-referencing payments directly, not
    by trusting invoice.status -- proven end-to-end here, not just at the
    Policy Gate's unit-test level."""
    live_invoice_id = db_session.execute(
        select(Invoice.id)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Customer.archetype == "already_paid_false_alarm")
        .where(Invoice.status == InvoiceStatus.OPEN)
        .limit(1)
    ).scalar_one()

    decision = decide(live_invoice_id, engine=engine)

    assert decision.final_action == ActionType.STOP
    assert decision.policy_verdict.result == PolicyResult.BLOCKED
    assert "already paid" in decision.policy_verdict.reason


def test_run_full_live_pass_small_sample_produces_one_decision_per_invoice():
    decisions = run_full_live_pass(engine=engine, limit=10)
    assert len(decisions) == 10
    assert len({d.invoice_id for d in decisions}) == 10
