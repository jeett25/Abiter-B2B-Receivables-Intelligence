from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.attribution.simulate_outcomes import SimulatedOutcome
from app.core.db import SessionLocal
from app.models import AccountState, AttributionRecord, DecisionLog, Invoice, Payment
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus, PaymentStatus, PolicyResult, TreatmentGroup

LEDGER_PAYMENT_METHOD = "attribution_simulation"


def _to_decimal(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def _to_utc_datetime(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def build_attribution_record(outcome: SimulatedOutcome) -> AttributionRecord:
    return AttributionRecord(
        invoice_id=outcome.invoice_id,
        treatment_group=outcome.group,
        baseline_predicted_recovery=_to_decimal(outcome.base_probability * outcome.amount),
        observed_recovery=_to_decimal(outcome.recovered_amount),
        incremental_recovery=None,
        action=outcome.action if outcome.group == TreatmentGroup.ACTED else None,
        counterfactual_action=outcome.counterfactual_action,
    )


# Marker substring, checked by the retroactive backfill script
# (backfill_closing_decision_logs.py) to stay idempotent -- safe to rerun
# without ever creating a second closing entry for the same invoice.
CLOSING_ENTRY_MARKER = "Day-5 attribution experiment's randomized-holdout simulation"


def build_closing_decision_log(invoice_id, payment_date: date, session) -> DecisionLog:
    """The one closing decision_logs entry written when an invoice is
    recovered via the attribution simulation's ledger write-back -- shared
    by the live path (_apply_ledger_write_back, below) and the one-off
    retroactive backfill for invoices resolved before this fix existed.
    Deliberately honest about what it is: model_scores are explicit None
    (never fabricated -- no fresh assessment actually ran), and the reason
    says plainly that this is a recorded outcome, not a new decision.

    Timestamp is NOT simply payment_date: the real decision engine always
    business-dates its assessments at the project's fixed "today"
    (DEFAULT_AS_OF, ~Aug 27, 2026), while the attribution simulation's
    payment_date is a COUNTERFACTUAL date computed relative to the
    invoice's own due_date -- which is very often chronologically EARLIER
    than Aug 27. Using payment_date as-is would make this closing entry
    sort BEFORE the real assessment it's meant to supersede, defeating the
    entire point (confirmed live: this exact bug shipped once already).
    Guaranteed instead to sort after every existing entry for this
    invoice, so it's always the last word in the timeline."""
    latest_existing = session.execute(
        select(func.max(DecisionLog.timestamp)).where(DecisionLog.invoice_id == invoice_id)
    ).scalar_one_or_none()
    timestamp = _to_utc_datetime(payment_date)
    if latest_existing is not None and latest_existing >= timestamp:
        timestamp = latest_existing + timedelta(minutes=1)

    return DecisionLog(
        invoice_id=invoice_id,
        decision=ActionType.STOP.value,
        model_scores={"recovery_probability": None, "ptp_probability": None, "root_cause": None},
        evidence={"trigger_event": {"event_type": "attribution.simulated_recovery", "payload": {}}},
        policy_checks={
            "is_disputed": False,
            "is_actually_paid": True,
            "selected_action": ActionType.STOP.value,
            "policy_result": PolicyResult.ALLOWED.value,
            "state_transition_path": [AccountCurrentState.CLOSED_PAID.value],
        },
        reason=(
            f"Invoice recovered via the {CLOSING_ENTRY_MARKER}, not a fresh decision-engine "
            "assessment -- the entries above reflect the last real decision made before this "
            "payment was recorded."
        ),
        timestamp=timestamp,
    )


def _apply_ledger_write_back(outcome: SimulatedOutcome, session) -> None:
    """Only ever called when outcome.recovered is True -- see module
    docstring for why the not-recovered case is a deliberate no-op here."""
    payment_date = outcome.ledger_payment_date

    existing_completed_total = session.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.invoice_id == outcome.invoice_id,
            Payment.status == PaymentStatus.COMPLETED,
        )
    ).scalar_one()

    remaining_balance = _to_decimal(outcome.recovered_amount) - existing_completed_total
    if remaining_balance > 0:
        session.add(
            Payment(
                invoice_id=outcome.invoice_id,
                amount=remaining_balance,
                payment_date=payment_date,
                method=LEDGER_PAYMENT_METHOD,
            )
        )

    invoice = session.get(Invoice, outcome.invoice_id)
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = _to_utc_datetime(payment_date)

    account_state = session.get(AccountState, outcome.invoice_id)
    account_state.current_state = AccountCurrentState.CLOSED_PAID
    account_state.recoverability_score = outcome.base_probability
    account_state.revenue_at_risk = Decimal("0.00")
    account_state.expected_payment_date = payment_date
    account_state.next_action = ActionType.STOP

    # 2026-09-02 fix: without this, account_state (updated here) and
    # decision_logs (only ever updated by a real decision-engine
    # assessment, which never runs again once an invoice leaves the open
    # pool) silently diverge -- the invoice-detail page's header would show
    # "CLOSED - PAID" while "Why this decision?"/Timeline kept showing
    # whatever was decided BEFORE this payment, with no indication that a
    # payment happened in between.
    session.add(build_closing_decision_log(outcome.invoice_id, payment_date, session))


def persist_experiment_outcome(outcome: SimulatedOutcome, session) -> None:
    session.add(build_attribution_record(outcome))
    if outcome.recovered:
        _apply_ledger_write_back(outcome, session)


def persist_experiment_outcomes(outcomes: list[SimulatedOutcome]) -> dict:
    session = SessionLocal()
    n_recovered = 0
    try:
        for outcome in outcomes:
            persist_experiment_outcome(outcome, session)
            if outcome.recovered:
                n_recovered += 1
        session.commit()
    finally:
        session.close()
    return {"n_records": len(outcomes), "n_recovered_write_back": n_recovered}


if __name__ == "__main__":
    from app.attribution.simulate_outcomes import run_experiment_simulation

    print(
        "Running the full experiment simulation (real decision engine for the "
        "treatment arm, ~405 invoices with retrieval -- expect several minutes)..."
    )
    outcomes = run_experiment_simulation()
    print(f"Simulated {len(outcomes)} outcomes. Persisting for real...")

    result = persist_experiment_outcomes(outcomes)
    print(
        f"Persisted {result['n_records']} attribution_records rows; "
        f"wrote back {result['n_recovered_write_back']} recovered invoices "
        f"to invoices/payments/account_state."
    )
