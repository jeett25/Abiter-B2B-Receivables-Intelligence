"""Validation suite for the synthetic dataset.

Checks whatever is CURRENTLY in the database -- not the generator's internal
state -- so it catches real data problems regardless of how the data got
there. Run standalone for a human-readable report; the pytest suite imports
these same functions and asserts on them.

Run with: python -m synthetic.validators
          python -m synthetic.validators --fingerprint   (reproducibility check)
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import (
    AccountState,
    Customer,
    Interaction,
    Invoice,
    Merchant,
    Payment,
    PaymentPromise,
    RecoveryAction,
)
from app.models.enums import InvoiceStatus
from synthetic.archetypes import AMOUNT_MAX, AMOUNT_MIN, ARCHETYPES, DISPUTE_RATE, WRITTEN_OFF_DAYS_RANGE
from synthetic.generator import REFERENCE_DATE

# How far observed archetype population shares may drift from target before
# it's flagged -- pure sampling noise at n=600 easily produces +/-30-40% on
# the smallest (5%) archetype, so this stays generous on purpose.
ARCHETYPE_TOLERANCE = 0.5


def _count(session: Session, query) -> int:
    return session.execute(select(func.count()).select_from(query.subquery())).scalar_one()


def check_referential_integrity(session: Session) -> list[str]:
    """Also covers orphan-record validation -- same check, from the child-row side."""
    violations = []

    checks = [
        ("customers.merchant_id", select(Customer.id).outerjoin(Merchant, Customer.merchant_id == Merchant.id).where(Merchant.id.is_(None))),
        ("invoices.merchant_id", select(Invoice.id).outerjoin(Merchant, Invoice.merchant_id == Merchant.id).where(Merchant.id.is_(None))),
        ("invoices.customer_id", select(Invoice.id).outerjoin(Customer, Invoice.customer_id == Customer.id).where(Customer.id.is_(None))),
        ("payments.invoice_id", select(Payment.id).outerjoin(Invoice, Payment.invoice_id == Invoice.id).where(Invoice.id.is_(None))),
        ("payment_promises.invoice_id", select(PaymentPromise.id).outerjoin(Invoice, PaymentPromise.invoice_id == Invoice.id).where(Invoice.id.is_(None))),
        ("interactions.customer_id", select(Interaction.id).outerjoin(Customer, Interaction.customer_id == Customer.id).where(Customer.id.is_(None))),
        (
            "interactions.invoice_id (where set)",
            select(Interaction.id)
            .outerjoin(Invoice, Interaction.invoice_id == Invoice.id)
            .where(Interaction.invoice_id.is_not(None), Invoice.id.is_(None)),
        ),
        ("recovery_actions.invoice_id", select(RecoveryAction.id).outerjoin(Invoice, RecoveryAction.invoice_id == Invoice.id).where(Invoice.id.is_(None))),
        ("account_state.invoice_id", select(AccountState.invoice_id).outerjoin(Invoice, AccountState.invoice_id == Invoice.id).where(Invoice.id.is_(None))),
        ("account_state.merchant_id", select(AccountState.invoice_id).outerjoin(Merchant, AccountState.merchant_id == Merchant.id).where(Merchant.id.is_(None))),
        ("account_state.customer_id", select(AccountState.invoice_id).outerjoin(Customer, AccountState.customer_id == Customer.id).where(Customer.id.is_(None))),
    ]

    for label, query in checks:
        count = _count(session, query)
        if count:
            violations.append(f"{label}: {count} row(s) reference a non-existent parent")

    missing_account_state = _count(
        session, select(Invoice.id).outerjoin(AccountState, AccountState.invoice_id == Invoice.id).where(AccountState.invoice_id.is_(None))
    )
    if missing_account_state:
        violations.append(f"{missing_account_state} invoice(s) have no account_state row")

    return violations


def check_temporal_consistency(session: Session) -> list[str]:
    violations = []

    due_before_issue = _count(session, select(Invoice.id).where(Invoice.due_date < Invoice.issue_date))
    if due_before_issue:
        violations.append(f"{due_before_issue} invoice(s) have due_date before issue_date")

    payment_before_issue = _count(
        session,
        select(Payment.id).join(Invoice, Payment.invoice_id == Invoice.id).where(Payment.payment_date < Invoice.issue_date),
    )
    if payment_before_issue:
        violations.append(f"{payment_before_issue} payment(s) dated before their invoice's issue_date")

    paid_without_timestamp = _count(
        session, select(Invoice.id).where(Invoice.status == InvoiceStatus.PAID, Invoice.paid_at.is_(None))
    )
    if paid_without_timestamp:
        violations.append(f"{paid_without_timestamp} invoice(s) marked PAID with no paid_at timestamp")

    timestamp_without_paid = _count(
        session, select(Invoice.id).where(Invoice.status != InvoiceStatus.PAID, Invoice.paid_at.is_not(None))
    )
    if timestamp_without_paid:
        violations.append(f"{timestamp_without_paid} invoice(s) have a paid_at timestamp but status != PAID")

    future_payments = _count(session, select(Payment.id).where(Payment.payment_date > REFERENCE_DATE))
    if future_payments:
        violations.append(f"{future_payments} payment(s) dated after the dataset's reference date ({REFERENCE_DATE})")

    return violations


def check_business_rules(session: Session) -> list[str]:
    violations = []

    min_writeoff_days = WRITTEN_OFF_DAYS_RANGE[0]
    threshold_date = REFERENCE_DATE - timedelta(days=min_writeoff_days)
    premature_writeoffs = _count(
        session, select(Invoice.id).where(Invoice.status == InvoiceStatus.WRITTEN_OFF, Invoice.due_date > threshold_date)
    )
    if premature_writeoffs:
        violations.append(
            f"{premature_writeoffs} invoice(s) are WRITTEN_OFF but due_date is less than "
            f"{min_writeoff_days} days before the reference date"
        )

    paid_sum_subq = (
        select(Payment.invoice_id.label("invoice_id"), func.sum(Payment.amount).label("total_paid"))
        .group_by(Payment.invoice_id)
        .subquery()
    )
    mismatched_paid = _count(
        session,
        select(Invoice.id)
        .outerjoin(paid_sum_subq, Invoice.id == paid_sum_subq.c.invoice_id)
        .where(
            Invoice.status == InvoiceStatus.PAID,
            or_(
                paid_sum_subq.c.total_paid.is_(None),
                func.abs(paid_sum_subq.c.total_paid - Invoice.amount) > Decimal("0.01"),
            ),
        ),
    )
    if mismatched_paid:
        violations.append(f"{mismatched_paid} PAID invoice(s) have no payments row, or payments not summing to the invoice amount")

    false_alarm_customer_ids = select(Customer.id).where(Customer.archetype == "already_paid_false_alarm")

    false_alarm_without_payment = _count(
        session,
        select(Invoice.id)
        .outerjoin(Payment, Payment.invoice_id == Invoice.id)
        .where(Invoice.customer_id.in_(false_alarm_customer_ids), Payment.id.is_(None)),
    )
    if false_alarm_without_payment:
        violations.append(f"{false_alarm_without_payment} already_paid_false_alarm invoice(s) have no payments row")

    false_alarm_wrong_status = _count(
        session,
        select(Invoice.id).where(Invoice.customer_id.in_(false_alarm_customer_ids), Invoice.status != InvoiceStatus.OPEN),
    )
    if false_alarm_wrong_status:
        violations.append(
            f"{false_alarm_wrong_status} already_paid_false_alarm invoice(s) have status != OPEN "
            f"(should stay OPEN to represent the reconciliation lag)"
        )

    total_invoices = _count(session, select(Invoice.id))
    disputed = _count(session, select(Invoice.id).where(Invoice.true_root_cause == "dispute"))
    dispute_rate = disputed / total_invoices if total_invoices else 0
    if not (DISPUTE_RATE * 0.5 <= dispute_rate <= DISPUTE_RATE * 1.5):
        violations.append(f"dispute rate {dispute_rate:.2%} is far from the {DISPUTE_RATE:.0%} target")

    return violations


def check_duplicates(session: Session) -> list[str]:
    violations = []
    dup_invoice_numbers = session.execute(
        select(Invoice.invoice_number, func.count()).group_by(Invoice.invoice_number).having(func.count() > 1)
    ).all()
    if dup_invoice_numbers:
        violations.append(f"{len(dup_invoice_numbers)} duplicate invoice_number value(s) found")
    return violations


def check_missing_values(session: Session) -> list[str]:
    violations = []

    missing_archetype = _count(session, select(Customer.id).where(Customer.archetype.is_(None)))
    if missing_archetype:
        violations.append(f"{missing_archetype} customer(s) missing archetype")

    missing_recovery_prob = _count(session, select(Customer.id).where(Customer.true_recovery_probability.is_(None)))
    if missing_recovery_prob:
        violations.append(f"{missing_recovery_prob} customer(s) missing true_recovery_probability")

    missing_root_cause = _count(session, select(Invoice.id).where(Invoice.true_root_cause.is_(None)))
    if missing_root_cause:
        violations.append(f"{missing_root_cause} invoice(s) missing true_root_cause")

    return violations


def check_amount_and_date_bounds(session: Session) -> list[str]:
    violations = []

    out_of_bounds_amount = _count(
        session, select(Invoice.id).where(or_(Invoice.amount < AMOUNT_MIN, Invoice.amount > AMOUNT_MAX))
    )
    if out_of_bounds_amount:
        violations.append(f"{out_of_bounds_amount} invoice(s) have amount outside [{AMOUNT_MIN}, {AMOUNT_MAX}]")

    negative_costs = _count(session, select(RecoveryAction.id).where(RecoveryAction.cost < 0))
    if negative_costs:
        violations.append(f"{negative_costs} recovery_action(s) have a negative cost")

    negative_payments = _count(session, select(Payment.id).where(Payment.amount < 0))
    if negative_payments:
        violations.append(f"{negative_payments} payment(s) have a negative amount")

    return violations


def check_archetypes_present(session: Session) -> list[str]:
    violations = []
    total_customers = _count(session, select(Customer.id))
    counts = dict(session.execute(select(Customer.archetype, func.count()).group_by(Customer.archetype)).all())

    for name, archetype in ARCHETYPES.items():
        observed = counts.get(name, 0)
        if observed == 0:
            violations.append(f"archetype '{name}' has zero customers")
            continue
        expected = archetype.population_share * total_customers
        lower = expected * (1 - ARCHETYPE_TOLERANCE)
        upper = expected * (1 + ARCHETYPE_TOLERANCE)
        if not (lower <= observed <= upper):
            violations.append(
                f"archetype '{name}': observed {observed}, expected ~{expected:.0f} "
                f"(outside +/-{ARCHETYPE_TOLERANCE:.0%} tolerance)"
            )

    return violations


def run_all_validations(session: Session) -> dict[str, list[str]]:
    return {
        "referential_integrity_and_orphans": check_referential_integrity(session),
        "temporal_consistency": check_temporal_consistency(session),
        "business_rules": check_business_rules(session),
        "duplicates": check_duplicates(session),
        "missing_values": check_missing_values(session),
        "amount_and_date_bounds": check_amount_and_date_bounds(session),
        "archetypes_present": check_archetypes_present(session),
    }


def generate_summary(session: Session) -> dict:
    status_counts = dict(session.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
    archetype_counts = dict(session.execute(select(Customer.archetype, func.count()).group_by(Customer.archetype)).all())
    root_cause_counts = dict(
        session.execute(select(Invoice.true_root_cause, func.count()).group_by(Invoice.true_root_cause)).all()
    )
    promise_status_counts = dict(
        session.execute(select(PaymentPromise.status, func.count()).group_by(PaymentPromise.status)).all()
    )
    total_invoice_value = session.execute(select(func.coalesce(func.sum(Invoice.amount), 0))).scalar_one()
    revenue_at_risk = session.execute(select(func.coalesce(func.sum(AccountState.revenue_at_risk), 0))).scalar_one()

    return {
        "merchants": _count(session, select(Merchant.id)),
        "customers": _count(session, select(Customer.id)),
        "invoices_total": _count(session, select(Invoice.id)),
        "invoices_by_status": status_counts,
        "customers_by_archetype": archetype_counts,
        "invoices_by_root_cause": root_cause_counts,
        "payments": _count(session, select(Payment.id)),
        "promises": _count(session, select(PaymentPromise.id)),
        "promises_by_status": promise_status_counts,
        "interactions": _count(session, select(Interaction.id)),
        "recovery_actions": _count(session, select(RecoveryAction.id)),
        "total_invoice_value": float(total_invoice_value),
        "total_revenue_at_risk": float(revenue_at_risk),
    }


def compute_dataset_fingerprint(session: Session) -> str:
    """Hash of business-meaningful content only -- excludes UUIDs (not seeded by
    SEED=42) and insert timestamps (reflect wall-clock run time, not generated
    content). Two runs of the generator with the same SEED should produce the
    same fingerprint.
    """
    hasher = hashlib.sha256()

    invoice_rows = session.execute(
        select(
            Invoice.invoice_number,
            Invoice.amount,
            Invoice.issue_date,
            Invoice.due_date,
            Invoice.status,
            Invoice.true_root_cause,
        ).order_by(Invoice.invoice_number)
    ).all()
    hasher.update(repr(invoice_rows).encode())

    archetype_counts = session.execute(
        select(Customer.archetype, func.count()).group_by(Customer.archetype).order_by(Customer.archetype)
    ).all()
    hasher.update(repr(archetype_counts).encode())

    promise_status_counts = session.execute(
        select(PaymentPromise.status, func.count()).group_by(PaymentPromise.status).order_by(PaymentPromise.status)
    ).all()
    hasher.update(repr(promise_status_counts).encode())

    return hasher.hexdigest()


def print_report(results: dict[str, list[str]]) -> bool:
    all_passed = True
    for name, violations in results.items():
        if violations:
            all_passed = False
            print(f"[FAIL] {name} ({len(violations)} issue(s)):")
            for v in violations:
                print(f"    - {v}")
        else:
            print(f"[PASS] {name}")
    return all_passed


def print_summary(summary: dict) -> None:
    print("\n--- Dataset summary ---")
    for key, value in summary.items():
        print(f"{key}: {value}")


def main() -> None:
    session = SessionLocal()
    try:
        results = run_all_validations(session)
        passed = print_report(results)
        summary = generate_summary(session)
        print_summary(summary)
        if not passed:
            raise SystemExit(1)
    finally:
        session.close()


if __name__ == "__main__":
    import sys

    if "--fingerprint" in sys.argv:
        _session = SessionLocal()
        try:
            print(compute_dataset_fingerprint(_session))
        finally:
            _session.close()
    else:
        main()
