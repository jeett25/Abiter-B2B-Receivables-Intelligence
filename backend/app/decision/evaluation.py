"""Evaluation: naive baseline vs. decision engine, run over the same 900
live invoices.

Framing, stated once here rather than left implicit: the live pool is
UNRESOLVED (status='open') -- there is no real observed outcome to compare
either strategy against yet. That comparison, against actual simulated
resolution via a randomized holdout, is Day 5's Attribution Engine. This
module is an EXPECTED-VALUE comparison: both strategies' "recovered revenue"
figures are probability-weighted estimates using the same calibrated
recovery-model probabilities and the same Economics Engine formulas
(probability_given_action/INTERVENTION_COST_INR/friction_cost) already used
for decision-making -- not a claim about what will actually happen.

Baseline: every live invoice gets the same generic EMAIL reminder,
regardless of economics, dispute status, or already-paid status -- the
pitch's own naive strawman. Reuses the SAME recovery-probability estimate
already computed for each invoice by run_full_live_pass() so the comparison
isolates the value the decision-intelligence layer itself contributes, not a
difference in probability estimates between the two "strategies".
"""
from __future__ import annotations

from dataclasses import dataclass

from app.decision.config import INTERVENTION_COST_INR
from app.decision.economics import friction_cost, probability_given_action
from app.decision.service import Decision
from app.models.enums import ActionType

# Both WAIT ("still monitoring, hoping for organic recovery") and STOP
# ("gave up") are "no active intervention sent" for cost/count purposes, but
# kept as separate reported buckets rather than one "abstained" bucket --
# same reasoning as subtask 6's CLOSED_PAID/CLOSED_ABANDONED split: collapsing
# them loses a real distinction a dashboard reader would want.
NO_INTERVENTION_ACTIONS = {ActionType.WAIT, ActionType.STOP}

# Diagnostic only (see evaluate_escalation_appropriateness) -- true ESCALATE
# uplift from synthetic/archetypes.py's hidden ground truth, read here purely
# to VERIFY the engine's choices, never as a decision input. chronic_late's
# 0.18 is by far the highest true escalate-uplift; these three are all ~0.00.
HIGH_ESCALATE_UPLIFT_ARCHETYPE = "chronic_late"
LOW_ESCALATE_UPLIFT_ARCHETYPES = {"reliable_payer", "strategic_enterprise", "already_paid_false_alarm"}


@dataclass(frozen=True)
class StrategyOutcome:
    invoice_id: object
    action: ActionType
    base_probability: float
    amount: float


def baseline_outcomes(engine_decisions: list[Decision]) -> list[StrategyOutcome]:
    return [
        StrategyOutcome(d.invoice_id, ActionType.EMAIL, d.base_probability, d.amount) for d in engine_decisions
    ]


def engine_outcomes(engine_decisions: list[Decision]) -> list[StrategyOutcome]:
    return [
        StrategyOutcome(d.invoice_id, d.final_action, d.base_probability, d.amount) for d in engine_decisions
    ]


@dataclass(frozen=True)
class EvaluationSummary:
    strategy_name: str
    n_invoices: int
    n_interventions: int
    n_wait: int
    n_stop: int
    total_amount: float
    gross_expected_recovered: float
    total_cost: float
    total_friction: float
    net_expected_recovered: float
    recovery_rate: float


def summarize_strategy(name: str, outcomes: list[StrategyOutcome]) -> EvaluationSummary:
    """prior_contact_count is hardcoded to 0 for friction purposes -- both
    strategies are being evaluated on the live pool's first-ever assessment
    (a true blank slate, confirmed in subtask 5: zero existing
    recovery_actions rows), so this matches today's actual data, not an
    approximation."""
    n = len(outcomes)
    total_amount = sum(o.amount for o in outcomes)
    gross = 0.0
    cost = 0.0
    friction = 0.0
    n_interventions = 0
    n_wait = 0
    n_stop = 0

    for outcome in outcomes:
        probability = probability_given_action(outcome.base_probability, outcome.action)
        gross += probability * outcome.amount
        cost += INTERVENTION_COST_INR[outcome.action]
        friction += friction_cost(outcome.action, prior_contact_count=0)

        if outcome.action == ActionType.WAIT:
            n_wait += 1
        elif outcome.action == ActionType.STOP:
            n_stop += 1
        else:
            n_interventions += 1

    net = gross - cost - friction
    return EvaluationSummary(
        strategy_name=name,
        n_invoices=n,
        n_interventions=n_interventions,
        n_wait=n_wait,
        n_stop=n_stop,
        total_amount=total_amount,
        gross_expected_recovered=gross,
        total_cost=cost,
        total_friction=friction,
        net_expected_recovered=net,
        recovery_rate=gross / total_amount if total_amount else 0.0,
    )


def unnecessary_interventions_avoided(baseline_summary: EvaluationSummary, engine_summary: EvaluationSummary) -> int:
    """Baseline sends an intervention to every invoice, so every invoice the
    engine instead resolved to WAIT or STOP is one intervention the naive
    strategy would have paid for and the engine correctly didn't."""
    return engine_summary.n_wait + engine_summary.n_stop


def evaluate_escalation_appropriateness(engine_decisions: list[Decision], archetype_by_invoice: dict) -> dict:
    """Diagnostic only, same methodology as subtask 3's archetype-cohesion
    check: hidden ground truth used purely to verify a choice already made,
    never fed into the decision itself."""
    escalated = [d for d in engine_decisions if d.final_action == ActionType.ESCALATE]
    if not escalated:
        return {"n_escalated": 0, "high_uplift_share": 0.0, "low_uplift_share": 0.0}

    archetypes = [archetype_by_invoice.get(d.invoice_id) for d in escalated]
    high_count = sum(1 for a in archetypes if a == HIGH_ESCALATE_UPLIFT_ARCHETYPE)
    low_count = sum(1 for a in archetypes if a in LOW_ESCALATE_UPLIFT_ARCHETYPES)

    return {
        "n_escalated": len(escalated),
        "high_uplift_share": high_count / len(escalated),
        "low_uplift_share": low_count / len(escalated),
    }


def _print_summary(summary: EvaluationSummary) -> None:
    print(f"\n{summary.strategy_name}")
    print(f"  invoices: {summary.n_invoices}  (interventions={summary.n_interventions}, wait={summary.n_wait}, stop={summary.n_stop})")
    print(f"  total amount:              Rs.{summary.total_amount:,.0f}")
    print(f"  gross expected recovered:  Rs.{summary.gross_expected_recovered:,.0f}")
    print(f"  total cost + friction:     Rs.{summary.total_cost + summary.total_friction:,.0f}  (cost Rs.{summary.total_cost:,.0f} + friction Rs.{summary.total_friction:,.0f})")
    print(f"  net expected recovered:    Rs.{summary.net_expected_recovered:,.0f}")
    print(f"  recovery rate:             {summary.recovery_rate:.1%}")


if __name__ == "__main__":
    from app.decision.service import run_full_live_pass
    from app.ml.features import load_raw_tables

    decisions = run_full_live_pass()

    baseline = summarize_strategy("Baseline (email everyone)", baseline_outcomes(decisions))
    engine = summarize_strategy("Decision engine", engine_outcomes(decisions))

    _print_summary(baseline)
    _print_summary(engine)

    print(f"\nUnnecessary interventions avoided: {unnecessary_interventions_avoided(baseline, engine)}")
    print(f"Net improvement (engine - baseline): Rs.{engine.net_expected_recovered - baseline.net_expected_recovered:,.0f}")

    customers = load_raw_tables()["customers"][["id", "archetype"]].rename(columns={"id": "customer_id"})
    invoices = load_raw_tables()["invoices"][["id", "customer_id"]].rename(columns={"id": "invoice_id"})
    joined = invoices.merge(customers, on="customer_id", how="left")
    archetype_by_invoice = dict(zip(joined["invoice_id"], joined["archetype"]))

    escalation_check = evaluate_escalation_appropriateness(decisions, archetype_by_invoice)
    print(f"\nEscalation-appropriateness diagnostic (n_escalated={escalation_check['n_escalated']}):")
    print(f"  share that are chronic_late (true high escalate-uplift): {escalation_check['high_uplift_share']:.1%}")
    print(f"  share that are near-zero-true-uplift archetypes:          {escalation_check['low_uplift_share']:.1%}")
