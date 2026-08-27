"""Deterministic synthetic data generator for the Day-1 dataset.

Produces two separate invoice pools:
  - historical/closed: fully resolved (paid or written_off), carries full
    history (recovery_actions/promises/interactions/payments), trains models
    and fills the retrieval corpus. Drawn only from the 7 non-false-alarm
    archetypes, since "already paid false alarm" is a live phenomenon, not a
    resolved historical pattern.
  - live/open: unresolved, no history yet (a blank slate for the live
    decision engine / demo / attribution holdout), except for the
    already-paid-false-alarm archetype, which gets a real payment row that
    just hasn't been reconciled into invoices.status yet -- that's the whole
    point of the scenario.

Run with: python -m synthetic.generator
"""
from __future__ import annotations

import itertools
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from faker import Faker
from sqlalchemy import text

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
from app.models.enums import (
    AccountCurrentState,
    ActionType,
    InvoiceStatus,
    PaymentStatus,
    PolicyResult,
    PromiseStatus,
)
from synthetic.archetypes import ARCHETYPES, DISPUTE_RATE, INTERVENTION_COSTS

SEED = 42

# Fixed anchor date so the dataset is identical no matter what day this script
# actually runs -- required for the "same seed -> same dataset" reproducibility check.
REFERENCE_DATE = date(2026, 8, 27)

N_MERCHANTS = 15
N_CUSTOMERS = 600
N_HISTORICAL_INVOICES = 9000
N_LIVE_INVOICES = 900

# 12-month historical window ending 11 months before "today" -- guarantees even
# the slowest case (120-day terms + up to 180-day written-off wait, ~10 months)
# has fully resolved by REFERENCE_DATE. Also what supports the Day-2
# "train months 1-9 / evaluate months 10-11" split.
HISTORICAL_WINDOW_END = REFERENCE_DATE - timedelta(days=11 * 30)
HISTORICAL_WINDOW_START = HISTORICAL_WINDOW_END - timedelta(days=365)

LIVE_WINDOW_START = REFERENCE_DATE - timedelta(days=90)
LIVE_WINDOW_END = REFERENCE_DATE - timedelta(days=1)

PAYMENT_TERMS_CHOICES = [30, 45, 60, 90, 120]
PAYMENT_TERMS_WEIGHTS = [0.15, 0.10, 0.30, 0.30, 0.15]

INDUSTRIES = ["Manufacturing", "Retail", "Logistics", "IT Services", "Construction", "Pharma", "FMCG", "Textiles"]
SEGMENTS = ["SMB", "Mid-Market", "Enterprise"]

PROMISE_PRONE_ARCHETYPES = {"promise_keeper", "promise_breaker", "chronic_late", "cash_constrained"}

# A couple of plausible historical escalation ladders per archetype -- not the
# real Day-4 policy engine, just enough variety to generate believable
# recovery_actions/interactions history for training data.
ESCALATION_LADDERS: dict[str, list[list[ActionType]]] = {
    "reliable_payer": [[], [ActionType.EMAIL]],
    "slightly_late": [[ActionType.EMAIL], [ActionType.EMAIL, ActionType.WHATSAPP]],
    "chronic_late": [
        [ActionType.EMAIL, ActionType.WHATSAPP],
        [ActionType.EMAIL, ActionType.WHATSAPP, ActionType.PAYMENT_LINK, ActionType.ESCALATE],
    ],
    "promise_keeper": [[ActionType.WHATSAPP], [ActionType.WHATSAPP, ActionType.VOICE]],
    "promise_breaker": [[ActionType.WHATSAPP], [ActionType.WHATSAPP, ActionType.VOICE, ActionType.ESCALATE]],
    "strategic_enterprise": [[], [ActionType.EMAIL]],
    "cash_constrained": [
        [ActionType.EMAIL, ActionType.PAYMENT_LINK],
        [ActionType.EMAIL, ActionType.WHATSAPP, ActionType.PAYMENT_LINK],
    ],
}


def _weighted_choice(rng: random.Random, choices: list, weights: list[float]):
    return rng.choices(choices, weights=weights, k=1)[0]


def _random_date(rng: random.Random, start: date, end: date) -> date:
    span = max((end - start).days, 0)
    return start + timedelta(days=rng.randint(0, span))


def _to_utc_datetime(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)


def _lognormal_amount(rng: random.Random, mean: float, sigma: float) -> Decimal:
    from synthetic.archetypes import AMOUNT_MAX, AMOUNT_MIN

    value = rng.lognormvariate(mean, sigma)
    value = min(max(value, AMOUNT_MIN), AMOUNT_MAX)
    return Decimal(str(round(value, 2)))


def _draw_root_cause(rng: random.Random, archetype) -> str:
    if rng.random() < DISPUTE_RATE:
        return "dispute"
    weights = archetype.root_cause_weights
    return _weighted_choice(rng, list(weights.keys()), list(weights.values()))


def _draw_intervention_cost(rng: random.Random, action: ActionType) -> Decimal:
    cost = INTERVENTION_COSTS[action]
    if isinstance(cost, tuple):
        low, high = cost
        cost = rng.uniform(low, high)
    return Decimal(str(round(cost, 2)))


def _pick_escalation_ladder(rng: random.Random, archetype_name: str) -> list[ActionType]:
    options = ESCALATION_LADDERS.get(archetype_name, [[]])
    return rng.choice(options)


def reset_database(session) -> None:
    session.execute(
        text(
            "TRUNCATE TABLE attribution_records, decision_logs, feature_snapshots, "
            "recovery_actions, interactions, payment_promises, payments, account_state, "
            "invoices, customers, merchants RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


def generate_merchants(rng: random.Random, fake: Faker) -> list[Merchant]:
    merchants = []
    for _ in range(N_MERCHANTS):
        start = _random_date(rng, date(2021, 1, 1), date(2024, 6, 1))
        merchants.append(
            Merchant(
                id=uuid.uuid4(),
                company_name=fake.company(),
                industry=rng.choice(INDUSTRIES),
                segment=rng.choice(SEGMENTS),
                relationship_start_date=start,
            )
        )
    return merchants


def generate_customers(rng: random.Random, fake: Faker, merchants: list[Merchant]) -> list[Customer]:
    archetype_names = list(ARCHETYPES.keys())
    archetype_weights = [ARCHETYPES[name].population_share for name in archetype_names]

    customers = []
    for _ in range(N_CUSTOMERS):
        archetype_name = _weighted_choice(rng, archetype_names, archetype_weights)
        archetype = ARCHETYPES[archetype_name]
        merchant = rng.choice(merchants)
        start = _random_date(rng, merchant.relationship_start_date, HISTORICAL_WINDOW_END)
        is_false_alarm = archetype_name == "already_paid_false_alarm"
        customers.append(
            Customer(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                company_name=fake.company(),
                industry=rng.choice(INDUSTRIES),
                segment=rng.choice(SEGMENTS),
                relationship_start_date=start,
                archetype=archetype_name,
                true_recovery_probability=archetype.organic_recovery_probability,
                true_promise_keep_probability=None if is_false_alarm else archetype.promise_keep_probability,
            )
        )
    return customers


def _build_base_invoice(rng: random.Random, customer: Customer, counter, historical: bool) -> Invoice:
    archetype = ARCHETYPES[customer.archetype]
    amount = _lognormal_amount(rng, archetype.amount_lognormal_mean, archetype.amount_lognormal_sigma)
    term = _weighted_choice(rng, PAYMENT_TERMS_CHOICES, PAYMENT_TERMS_WEIGHTS)

    if historical:
        issue_date = _random_date(rng, HISTORICAL_WINDOW_START, HISTORICAL_WINDOW_END)
        due_date = issue_date + timedelta(days=term)
    else:
        # Guarantee the live-pool invoice is already overdue as of REFERENCE_DATE.
        due_date = _random_date(rng, LIVE_WINDOW_START, LIVE_WINDOW_END)
        issue_date = due_date - timedelta(days=term)

    root_cause = _draw_root_cause(rng, archetype)

    return Invoice(
        id=uuid.uuid4(),
        merchant_id=customer.merchant_id,
        customer_id=customer.id,
        invoice_number=f"INV-{next(counter)}",
        amount=amount,
        issue_date=issue_date,
        due_date=due_date,
        status=InvoiceStatus.OPEN,
        true_root_cause=root_cause,
    )


def _simulate_historical_invoice(rng: random.Random, customer: Customer, invoice: Invoice):
    archetype = ARCHETYPES[customer.archetype]

    recovery_actions: list[RecoveryAction] = []
    promises: list[PaymentPromise] = []
    interactions: list[Interaction] = []
    payments: list[Payment] = []

    ladder = _pick_escalation_ladder(rng, archetype.name)

    cumulative_uplift = 0.0
    cumulative_delay_reduction = 0
    contact_date = invoice.due_date
    for action in ladder:
        contact_date = contact_date + timedelta(days=rng.randint(3, 10))
        effect = archetype.action_effects.get(action)
        if effect is None:
            continue
        cumulative_uplift += effect.recovery_uplift
        cumulative_delay_reduction += effect.delay_reduction_days
        cost = _draw_intervention_cost(rng, action)
        recovery_prob_estimate = min(archetype.organic_recovery_probability + cumulative_uplift, 0.99)
        expected_value = (invoice.amount * Decimal(str(recovery_prob_estimate))) - cost
        recovery_actions.append(
            RecoveryAction(
                invoice_id=invoice.id,
                action_type=action,
                expected_value=expected_value.quantize(Decimal("0.01")),
                cost=cost,
                policy_result=PolicyResult.ALLOWED,
                result="sent",
                timestamp=_to_utc_datetime(contact_date),
            )
        )
        interactions.append(
            Interaction(
                customer_id=invoice.customer_id,
                invoice_id=invoice.id,
                channel=action.value,
                content=f"Payment reminder for invoice {invoice.invoice_number} via {action.value}.",
                intent="payment_reminder",
                outcome="acknowledged" if rng.random() < 0.6 else "no_response",
                cost=cost,
                timestamp=_to_utc_datetime(contact_date),
            )
        )

    recovered = rng.random() < min(archetype.organic_recovery_probability + cumulative_uplift, 0.99)
    if archetype.delay_days_range != (0, 0):
        delay = max(rng.randint(*archetype.delay_days_range) - cumulative_delay_reduction, 1)
    else:
        delay = 0

    attempt_promise = False
    if ladder:
        promise_chance = 0.5 if archetype.name in PROMISE_PRONE_ARCHETYPES else 0.2
        attempt_promise = rng.random() < promise_chance

    if attempt_promise:
        promised_date = contact_date + timedelta(days=rng.randint(3, 15))
        kept = rng.random() < archetype.promise_keep_probability
        promises.append(
            PaymentPromise(
                invoice_id=invoice.id,
                promised_amount=invoice.amount,
                promised_date=promised_date,
                source=rng.choice(ladder).value,
                confidence_score=round(
                    min(max(archetype.promise_keep_probability + rng.uniform(-0.05, 0.05), 0.0), 1.0), 2
                ),
                status=PromiseStatus.KEPT if kept else PromiseStatus.BROKEN,
            )
        )
        if kept:
            recovered = True
            delay = max((promised_date - invoice.due_date).days, 0)

    if recovered:
        pay_date = invoice.due_date + timedelta(days=delay)
        if pay_date > REFERENCE_DATE:
            pay_date = REFERENCE_DATE - timedelta(days=1)

        if archetype.name == "cash_constrained" and rng.random() < 0.3:
            first_amount = (invoice.amount * Decimal("0.5")).quantize(Decimal("0.01"))
            payments.append(
                Payment(
                    invoice_id=invoice.id,
                    amount=first_amount,
                    payment_date=pay_date - timedelta(days=rng.randint(5, 15)),
                    method=rng.choice(["bank_transfer", "upi"]),
                    status=PaymentStatus.COMPLETED,
                )
            )
            payments.append(
                Payment(
                    invoice_id=invoice.id,
                    amount=invoice.amount - first_amount,
                    payment_date=pay_date,
                    method=rng.choice(["bank_transfer", "upi"]),
                    status=PaymentStatus.COMPLETED,
                )
            )
        else:
            payments.append(
                Payment(
                    invoice_id=invoice.id,
                    amount=invoice.amount,
                    payment_date=pay_date,
                    method=rng.choice(["bank_transfer", "upi", "cheque", "card"]),
                    status=PaymentStatus.COMPLETED,
                )
            )

        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = _to_utc_datetime(pay_date)
        current_state = AccountCurrentState.CLOSED
        revenue_at_risk = Decimal("0.00")
        expected_payment_date = pay_date
    else:
        # Historical window guarantees enough time has elapsed for this to be final.
        invoice.status = InvoiceStatus.WRITTEN_OFF
        current_state = AccountCurrentState.CLOSED
        revenue_at_risk = invoice.amount
        expected_payment_date = None

    account_state = AccountState(
        invoice_id=invoice.id,
        merchant_id=invoice.merchant_id,
        customer_id=invoice.customer_id,
        current_state=current_state,
        recoverability_score=round(
            min(archetype.organic_recovery_probability + cumulative_uplift, 0.99) + rng.uniform(-0.02, 0.02), 4
        ),
        promise_score=round(archetype.promise_keep_probability + rng.uniform(-0.02, 0.02), 4),
        expected_payment_date=expected_payment_date,
        revenue_at_risk=revenue_at_risk,
        next_action=ActionType.STOP,
    )

    return recovery_actions, promises, interactions, payments, account_state


def _simulate_live_invoice(rng: random.Random, customer: Customer, invoice: Invoice):
    archetype = ARCHETYPES[customer.archetype]
    payments: list[Payment] = []

    if archetype.name == "already_paid_false_alarm":
        pay_date = invoice.due_date - timedelta(days=rng.randint(0, 5))
        payments.append(
            Payment(
                invoice_id=invoice.id,
                amount=invoice.amount,
                payment_date=pay_date,
                method=rng.choice(["bank_transfer", "upi", "cheque"]),
                status=PaymentStatus.COMPLETED,
            )
        )
        # invoice.status/paid_at intentionally left as OPEN/None -- reconciliation lag.
        promise_score = 0.0
    else:
        promise_score = round(archetype.promise_keep_probability + rng.uniform(-0.03, 0.03), 4)

    account_state = AccountState(
        invoice_id=invoice.id,
        merchant_id=invoice.merchant_id,
        customer_id=invoice.customer_id,
        current_state=AccountCurrentState.OVERDUE,
        recoverability_score=round(
            min(archetype.organic_recovery_probability + rng.uniform(-0.03, 0.03), 0.99), 4
        ),
        promise_score=promise_score,
        expected_payment_date=None,
        revenue_at_risk=invoice.amount,
        next_action=None,
    )
    return payments, account_state


def main() -> None:
    rng = random.Random(SEED)
    fake = Faker()
    fake.seed_instance(SEED)

    session = SessionLocal()
    try:
        reset_database(session)

        merchants = generate_merchants(rng, fake)
        session.add_all(merchants)
        session.flush()  # force merchants to insert before anything references merchant_id

        customers = generate_customers(rng, fake, merchants)
        session.add_all(customers)
        session.flush()  # force customers to insert before anything references customer_id

        invoice_counter = itertools.count(1001)

        historical_customers_pool = [c for c in customers if c.archetype != "already_paid_false_alarm"]

        invoices: list[Invoice] = []
        recovery_actions: list[RecoveryAction] = []
        promises: list[PaymentPromise] = []
        interactions: list[Interaction] = []
        payments: list[Payment] = []
        account_states: list[AccountState] = []

        for _ in range(N_HISTORICAL_INVOICES):
            customer = rng.choice(historical_customers_pool)
            invoice = _build_base_invoice(rng, customer, invoice_counter, historical=True)
            actions, prom, inter, pay, acct = _simulate_historical_invoice(rng, customer, invoice)
            invoices.append(invoice)
            recovery_actions.extend(actions)
            promises.extend(prom)
            interactions.extend(inter)
            payments.extend(pay)
            account_states.append(acct)

        for _ in range(N_LIVE_INVOICES):
            customer = rng.choice(customers)
            invoice = _build_base_invoice(rng, customer, invoice_counter, historical=False)
            pay, acct = _simulate_live_invoice(rng, customer, invoice)
            invoices.append(invoice)
            payments.extend(pay)
            account_states.append(acct)

        session.add_all(invoices)
        session.flush()  # force invoices to insert before anything references invoice_id

        session.add_all(recovery_actions)
        session.add_all(promises)
        session.add_all(interactions)
        session.add_all(payments)
        session.add_all(account_states)
        session.commit()

        print(
            f"Generated {len(merchants)} merchants, {len(customers)} customers, "
            f"{len(invoices)} invoices ({N_HISTORICAL_INVOICES} historical + {N_LIVE_INVOICES} live), "
            f"{len(payments)} payments, {len(promises)} promises, "
            f"{len(interactions)} interactions, {len(recovery_actions)} recovery actions, "
            f"{len(account_states)} account states."
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
