"""Subtask 2: forward-resolve the treatment/control experiment against the
synthetic environment's own hidden ground truth.

This is the ONE module in app/ (outside synthetic/ itself) allowed to
import synthetic.archetypes.ARCHETYPES directly -- the master doc's explicit
"the attribution engine can also be evaluated against [the simulator's] own
known treatment effect" exception, not a leakage bug. app/decision/,
app/ml/, and app/agent/ must never import from here or from synthetic/.

Two-stage outcome mechanism, mirroring synthetic/generator.py's own
_simulate_historical_invoice() reapplied forward from "now" instead of from
an already-fully-elapsed historical window:
  1. recovered_ever ~ Bernoulli(organic_recovery_probability [+ action
     uplift for treatment]) -- unconditional on time.
  2. IF recovered_ever, true_delay_days ~ Uniform(archetype.delay_days_range)
     [- action's delay_reduction_days for treatment].

recovered/recovered_amount (the fields subtask 4 aggregates) are then a
PURE function of the true, uncapped (recovered_ever, true_delay_days) pair,
gated at ATTRIBUTION_HORIZON_DAYS -- computed identically for both arms,
with zero dependency on whatever ledger-date capping happens afterward. See
DECISIONS.md's "recovered must not be derived from a capped date" entry for
why this separation is structural, not just documented discipline.

base_probability is carried through too (needed by subtask 3's
baseline_predicted_recovery = base_probability * amount): reused directly
from the treatment arm's own Decision (already computed via the real
decide() call, no redundant re-scoring), and scored separately via the
lightweight score_recovery_probability() for the control arm (which never
calls decide() at all, so has no Decision to reuse it from).

counterfactual_action (control arm only) is "what the engine would have
picked" -- computed via recommend_action()+evaluate_policy() directly
(NO retrieval call: retrieval never feeds the action choice, confirmed by
reading economics.py/policy.py's own signatures, so this costs nothing extra
at scale). Used purely as a reporting/stratification label for subtask 4/5's
per-action breakdown -- it is never fed back into control's simulated
outcome, which stays governed by organic probability alone, exactly as
before. See DECISIONS.md's "counterfactual action" entry.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy.engine import Engine

from app.attribution.assignment import assign_treatment_groups, build_experiment_population
from app.attribution.config import ATTRIBUTION_EXPERIMENT_SEED, ATTRIBUTION_HORIZON_DAYS
from app.decision.economics import recommend_action
from app.decision.policy import PolicyContext, evaluate_policy
from app.decision.service import DEFAULT_AS_OF, Decision, decide_from_feature_row, score_recovery_probability
from app.ml.features import build_live_feature_table, load_raw_tables
from app.models.enums import ActionType, TreatmentGroup
from synthetic.archetypes import ARCHETYPES


def _as_of_naive(as_of) -> pd.Timestamp:
    ts = pd.Timestamp(as_of)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _counterfactual_action(base_probability: float, amount: float, as_of: datetime) -> ActionType:
    """What the engine would have chosen for an eligible (not disputed, not
    already-paid, zero prior contacts -- all guaranteed by eligibility for
    the live pool today) invoice, without ever calling retrieval. Reporting
    label only -- see module docstring."""
    proposed = recommend_action(base_probability, amount, prior_contact_count=0, is_disputed=False)
    context = PolicyContext(
        proposed_action=proposed.action_type,
        base_probability=base_probability,
        amount=amount,
        is_actually_paid=False,
        is_disputed=False,
        prior_contact_count=0,
        days_since_last_contact=None,
        now=as_of,
    )
    return evaluate_policy(context).final_action


@dataclass(frozen=True)
class RawOutcomeDraw:
    """The stochastic part, independent of horizon_days -- computed once so
    the horizon-sensitivity checkpoint can compare several candidate
    horizons against the SAME draws instead of re-simulating (and
    introducing fresh sampling noise) per candidate."""

    invoice_id: object
    group: TreatmentGroup
    action: ActionType
    counterfactual_action: ActionType | None
    amount: float
    due_date: date
    archetype: str
    base_probability: float
    recovered_ever: bool
    true_delay_days: int | None


@dataclass(frozen=True)
class SimulatedOutcome:
    invoice_id: object
    group: TreatmentGroup
    action: ActionType
    counterfactual_action: ActionType | None
    amount: float
    base_probability: float
    # Horizon-gated -- the only field subtask 4 aggregates over.
    recovered: bool
    recovered_amount: float
    # TRUE, uncapped resolution date whenever recovered_ever -- set even if
    # recovered=False because true_delay_days exceeded the horizon (that
    # case is genuinely "would recover, just outside this experiment's
    # measurement window", not "never recovers"; analysis/time-to-recovery
    # reporting needs to be able to tell those apart).
    recovery_date: date | None
    # Capped at DEFAULT_AS_OF - 1 day (mirrors generator.py's own
    # REFERENCE_DATE - 1d rule for exactly this situation) -- set ONLY when
    # recovered=True. What subtask 3 will actually write to
    # payments.payment_date; never read back into `recovered` above.
    ledger_payment_date: date | None


def _build_treatment_decisions(
    treatment_ids: set,
    live_table: pd.DataFrame,
    tables: dict,
    as_of: datetime,
    limit: int | None = None,
) -> dict[object, Decision]:
    """The only place this subtask invokes the real ML+retrieval+economics+
    policy pipeline (decide_from_feature_row, reused unmodified from
    app/decision/service.py) -- and only for the treatment arm. Control
    never touches it, by design (see docs/attribution-DECISIONS.md)."""
    treatment_table = live_table[live_table["invoice_id"].isin(treatment_ids)]
    if limit is not None:
        treatment_table = treatment_table.head(limit)

    decisions: dict[object, Decision] = {}
    for _, row in treatment_table.iterrows():
        decisions[row["invoice_id"]] = decide_from_feature_row(row, tables, as_of)
    return decisions


def draw_raw_outcomes(
    seed: int = ATTRIBUTION_EXPERIMENT_SEED,
    as_of: datetime = DEFAULT_AS_OF,
    engine: Engine | None = None,
    limit: int | None = None,
) -> list[RawOutcomeDraw]:
    """limit restricts the TREATMENT arm to its first `limit` invoices (a
    testing convenience, mirrors run_full_live_pass's own `limit` param) --
    control draws are cheap (no decide() call) and always cover the full
    eligible control population regardless."""
    candidates = build_experiment_population(engine, as_of)
    assignment = assign_treatment_groups(candidates, seed=seed)

    tables = load_raw_tables(engine)
    invoices = tables["invoices"].set_index("id")
    customers = tables["customers"].set_index("id")
    live_table = build_live_feature_table(engine)

    treatment_ids = {inv_id for inv_id, g in assignment.items() if g == TreatmentGroup.ACTED}
    control_ids = {inv_id for inv_id, g in assignment.items() if g == TreatmentGroup.CONTROL}

    treatment_decisions = _build_treatment_decisions(treatment_ids, live_table, tables, as_of, limit=limit)

    control_table = live_table[live_table["invoice_id"].isin(control_ids)]
    control_probabilities = {
        row["invoice_id"]: score_recovery_probability(row) for _, row in control_table.iterrows()
    }

    # Sorted for determinism -- dict iteration order over `assignment` is
    # insertion order in Python, but that insertion order itself traces back
    # to a DataFrame iteration order this function doesn't control; sorting
    # here is what actually guarantees a rerun consumes the RNG identically.
    ordered_ids = sorted(
        (inv_id for inv_id in assignment if inv_id in treatment_decisions or inv_id in control_probabilities),
        key=str,
    )
    rng = random.Random(f"{seed}:outcomes")

    draws: list[RawOutcomeDraw] = []
    for invoice_id in ordered_ids:
        group = assignment[invoice_id]
        invoice_row = invoices.loc[invoice_id]
        amount = float(invoice_row["amount"])
        due_date = invoice_row["due_date"]
        due_date = due_date.date() if hasattr(due_date, "date") else due_date
        archetype_name = customers.loc[invoice_row["customer_id"]]["archetype"]
        archetype = ARCHETYPES[archetype_name]

        if group == TreatmentGroup.ACTED:
            decision = treatment_decisions[invoice_id]
            action = decision.final_action
            base_probability = decision.base_probability
            counterfactual_action = None
            effect = archetype.action_effects.get(action)
        else:
            action = ActionType.WAIT
            base_probability = control_probabilities[invoice_id]
            counterfactual_action = _counterfactual_action(base_probability, amount, as_of)
            effect = None

        uplift = effect.recovery_uplift if effect else 0.0
        delay_reduction = effect.delay_reduction_days if effect else 0

        recovery_prob = min(archetype.organic_recovery_probability + uplift, 0.99)
        recovered_ever = rng.random() < recovery_prob

        true_delay_days = None
        if recovered_ever:
            if archetype.delay_days_range != (0, 0):
                raw_delay = rng.randint(*archetype.delay_days_range)
                true_delay_days = max(raw_delay - delay_reduction, 1)
            else:
                true_delay_days = 0

        draws.append(
            RawOutcomeDraw(
                invoice_id=invoice_id,
                group=group,
                action=action,
                counterfactual_action=counterfactual_action,
                amount=amount,
                due_date=due_date,
                archetype=archetype_name,
                base_probability=base_probability,
                recovered_ever=recovered_ever,
                true_delay_days=true_delay_days,
            )
        )

    return draws


def gate_at_horizon(
    draws: list[RawOutcomeDraw], horizon_days: int, as_of: datetime = DEFAULT_AS_OF
) -> list[SimulatedOutcome]:
    """Pure function, no randomness -- lets the checkpoint compare several
    horizon_days candidates against the same draws."""
    as_of_cap = _as_of_naive(as_of).date() - timedelta(days=1)

    outcomes = []
    for d in draws:
        true_recovery_date = d.due_date + timedelta(days=d.true_delay_days) if d.recovered_ever else None
        recovered = d.recovered_ever and d.true_delay_days is not None and d.true_delay_days <= horizon_days
        recovered_amount = d.amount if recovered else 0.0
        ledger_payment_date = min(true_recovery_date, as_of_cap) if recovered else None

        outcomes.append(
            SimulatedOutcome(
                invoice_id=d.invoice_id,
                group=d.group,
                action=d.action,
                counterfactual_action=d.counterfactual_action,
                amount=d.amount,
                base_probability=d.base_probability,
                recovered=recovered,
                recovered_amount=recovered_amount,
                recovery_date=true_recovery_date,
                ledger_payment_date=ledger_payment_date,
            )
        )
    return outcomes


def run_experiment_simulation(
    seed: int = ATTRIBUTION_EXPERIMENT_SEED,
    as_of: datetime = DEFAULT_AS_OF,
    horizon_days: int = ATTRIBUTION_HORIZON_DAYS,
    engine: Engine | None = None,
    limit: int | None = None,
) -> list[SimulatedOutcome]:
    draws = draw_raw_outcomes(seed, as_of, engine, limit=limit)
    return gate_at_horizon(draws, horizon_days, as_of)


def _print_checkpoint(engine: Engine | None = None) -> None:
    draws = draw_raw_outcomes(engine=engine)
    control_draws = [d for d in draws if d.group == TreatmentGroup.CONTROL]

    print("Horizon sensitivity (control arm only -- pure organic basis, no action uplift):")
    for h in (30, 45, 60, 90):
        gated = gate_at_horizon(control_draws, h)
        rate = sum(o.recovered for o in gated) / len(gated) if gated else 0.0
        marker = "  <-- ATTRIBUTION_HORIZON_DAYS" if h == ATTRIBUTION_HORIZON_DAYS else ""
        print(f"  H={h:>3}d: {rate:.1%}{marker}")

    print(f"\nPer-archetype at H={ATTRIBUTION_HORIZON_DAYS}d (control arm only):")
    by_archetype: dict[str, list[RawOutcomeDraw]] = {}
    for d in control_draws:
        by_archetype.setdefault(d.archetype, []).append(d)
    gated_final = {name: gate_at_horizon(group, ATTRIBUTION_HORIZON_DAYS) for name, group in by_archetype.items()}
    for name in sorted(gated_final):
        gated = gated_final[name]
        rate = sum(o.recovered for o in gated) / len(gated) if gated else 0.0
        print(f"  {name:<24} n={len(gated):>4}  recovered={rate:.1%}")

    outcomes = gate_at_horizon(draws, ATTRIBUTION_HORIZON_DAYS)
    treatment = [o for o in outcomes if o.group == TreatmentGroup.ACTED]
    control = [o for o in outcomes if o.group == TreatmentGroup.CONTROL]

    def _rate(group):
        return sum(o.recovered for o in group) / len(group) if group else 0.0

    print(f"\nTreatment: n={len(treatment)}  recovered rate={_rate(treatment):.1%}")
    print(f"Control:   n={len(control)}  recovered rate={_rate(control):.1%}")

    print("\nSample rows:")
    header = (
        f"  {'invoice_id':<38} {'group':<10} {'action':<12} {'amount':>10} {'base_prob':>9} "
        f"{'recovered':<10} {'recovered_amount':>16} {'recovery_date'}"
    )
    print(header)
    for o in outcomes[:10]:
        print(
            f"  {str(o.invoice_id):<38} {o.group.value:<10} {o.action.value:<12} {o.amount:>10,.0f} "
            f"{o.base_probability:>9.3f} {str(o.recovered):<10} {o.recovered_amount:>16,.0f} {o.recovery_date}"
        )


if __name__ == "__main__":
    _print_checkpoint()
