from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.attribution.simulate_outcomes import SimulatedOutcome
from app.core.db import SessionLocal
from app.models import AccountState, AttributionRecord, Invoice, Payment
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus, PaymentStatus, TreatmentGroup

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
