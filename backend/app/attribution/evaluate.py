
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine

from app.attribution.config import EXPERIMENT_ID
from app.core.db import SessionLocal
from app.core.db import engine as default_engine
from app.decision.config import INTERVENTION_COST_INR
from app.decision.economics import friction_cost
from app.models import AttributionExperimentResult, AttributionRecord, Customer, Invoice
from app.models.enums import ActionType, TreatmentGroup


def _enum_values(series: pd.Series) -> pd.Series:
    return series.apply(lambda v: v.value if hasattr(v, "value") else v)


def load_attribution_data(engine: Engine | None = None) -> pd.DataFrame:
    """`archetype` is included here for diagnostic_action_by_archetype()'s
    use only -- every non-diagnostic function in this module (compute_slice,
    persist_slices) ignores it entirely. See module docstring."""
    engine = engine or default_engine

    records = pd.read_sql(select(AttributionRecord.__table__), engine)
    invoices = pd.read_sql(select(Invoice.__table__), engine)[["id", "customer_id", "amount"]]
    customers = pd.read_sql(select(Customer.__table__), engine)[["id", "segment", "archetype"]]

    records["treatment_group"] = _enum_values(records["treatment_group"])
    records["action"] = _enum_values(records["action"])
    records["counterfactual_action"] = _enum_values(records["counterfactual_action"])
    invoices["amount"] = invoices["amount"].astype(float)

    df = records.merge(invoices, left_on="invoice_id", right_on="id", how="left", suffixes=("", "_invoice"))
    df = df.merge(customers, left_on="customer_id", right_on="id", how="left", suffixes=("", "_customer"))

    df["observed_recovery"] = df["observed_recovery"].astype(float)
    df["baseline_predicted_recovery"] = df["baseline_predicted_recovery"].astype(float)
    df["recovered"] = df["observed_recovery"] > 0
    return df


@dataclass(frozen=True)
class AttributionSlice:
    segment: str | None
    action: str | None
    treatment_n: int
    control_n: int
    treatment_recovery_rate: float
    control_recovery_rate: float
    incremental_recovery_rate: float
    treatment_recovered_amount: float
    control_recovered_amount: float
    incremental_recovered_amount: float
    treatment_cost: float
    treatment_friction: float
    incremental_net_recovery: float
    # COUNT-based, for the SE/z calibration only -- see module docstring.
    treatment_count_recovery_rate: float | None
    control_count_recovery_rate: float | None
    recovery_rate_diff_se: float | None
    recovery_rate_diff_z: float | None


def _cost_and_friction(treatment_df: pd.DataFrame) -> tuple[float, float]:
    """prior_contact_count=0 for every treatment invoice here -- same fact
    Day 3's evaluation.py already relies on (a true blank slate for the
    live pool's first-ever assessment)."""
    cost = sum(INTERVENTION_COST_INR[ActionType(a)] for a in treatment_df["action"])
    friction = sum(friction_cost(ActionType(a), prior_contact_count=0) for a in treatment_df["action"])
    return cost, friction


def _two_proportion_se_and_z(
    p1: float, n1: int, p2: float, n2: int
) -> tuple[float | None, float | None]:
    """Unpooled two-proportion standard error (estimating the precision of
    the observed difference, not a strict equal-proportions null test) --
    deliberately lightweight, informal noise-floor calibration per
    DECISIONS.md, not a formal hypothesis-testing framework with a declared
    alpha or multiple-comparisons correction. None when undefined (either
    arm empty)."""
    if n1 == 0 or n2 == 0:
        return None, None
    variance = (p1 * (1 - p1) / n1) + (p2 * (1 - p2) / n2)
    se = math.sqrt(variance)
    z = (p1 - p2) / se if se > 0 else 0.0
    return se, z


def compute_slice(df: pd.DataFrame, segment: str | None, action: str | None) -> AttributionSlice:
    """Portfolio/segment rows (action=None) compare against the WHOLE
    control population in that segment. Action rows (and segment x action
    cells) compare against control invoices whose counterfactual_action
    matches -- the engine would also have picked this action for them --
    not the flat overall control rate. See DECISIONS.md's
    counterfactual_action entry for why that match costs nothing extra and
    is more honest than one pooled control baseline for every action."""
    treatment_df = df[df["treatment_group"] == TreatmentGroup.ACTED.value]
    control_df = df[df["treatment_group"] == TreatmentGroup.CONTROL.value]

    if segment is not None:
        treatment_df = treatment_df[treatment_df["segment"] == segment]
        control_df = control_df[control_df["segment"] == segment]

    if action is not None:
        treatment_df = treatment_df[treatment_df["action"] == action]
        control_df = control_df[control_df["counterfactual_action"] == action]

    treatment_n = len(treatment_df)
    control_n = len(control_df)

    treatment_recovered_amount = float(treatment_df["observed_recovery"].sum())
    control_recovered_amount = float(control_df["observed_recovery"].sum())
    treatment_total_amount_all = float(treatment_df["amount"].sum())
    control_total_amount_all = float(control_df["amount"].sum())

    # Amount-weighted, not a count-based fraction of invoices -- matches
    # app/decision/evaluation.py's own recovery_rate definition (gross /
    # total_amount) exactly. A count-based rate here would let recovered
    # invoices skew small relative to the whole population (which they do,
    # heavily, since large invoices correlate with archetypes whose delay
    # sits outside ATTRIBUTION_HORIZON_DAYS -- see DECISIONS.md) and produce
    # a rate/dollar sign contradiction: count-rate can rise while dollars
    # recovered fall. Keeping both figures on the same basis makes that
    # structurally impossible.
    treatment_recovery_rate = treatment_recovered_amount / treatment_total_amount_all if treatment_total_amount_all else 0.0
    control_recovery_rate = control_recovered_amount / control_total_amount_all if control_total_amount_all else 0.0

    # Incremental amount = what the treatment group actually recovered,
    # minus what that SAME group of invoices (their own amounts) would be
    # expected to recover organically, at the AMOUNT-WEIGHTED rate control
    # actually observed -- not a flat rate-difference times an arbitrary
    # population basis, and not a count-rate applied to a dollar figure
    # (see above). Applying control's rate to control's own amounts would
    # answer a different question ("how much did control recover") already
    # captured by control_recovered_amount above.
    expected_organic_for_treatment_group = control_recovery_rate * treatment_total_amount_all
    incremental_recovered_amount = treatment_recovered_amount - expected_organic_for_treatment_group

    cost, friction = _cost_and_friction(treatment_df)
    incremental_net_recovery = incremental_recovered_amount - cost - friction

    treatment_count_rate = float(treatment_df["recovered"].mean()) if treatment_n else None
    control_count_rate = float(control_df["recovered"].mean()) if control_n else None
    se, z = (
        _two_proportion_se_and_z(treatment_count_rate, treatment_n, control_count_rate, control_n)
        if treatment_count_rate is not None and control_count_rate is not None
        else (None, None)
    )

    return AttributionSlice(
        segment=segment,
        action=action,
        treatment_n=treatment_n,
        control_n=control_n,
        treatment_recovery_rate=treatment_recovery_rate,
        control_recovery_rate=control_recovery_rate,
        incremental_recovery_rate=treatment_recovery_rate - control_recovery_rate,
        treatment_recovered_amount=treatment_recovered_amount,
        control_recovered_amount=control_recovered_amount,
        incremental_recovered_amount=incremental_recovered_amount,
        treatment_cost=cost,
        treatment_friction=friction,
        incremental_net_recovery=incremental_net_recovery,
        treatment_count_recovery_rate=treatment_count_rate,
        control_count_recovery_rate=control_count_rate,
        recovery_rate_diff_se=se,
        recovery_rate_diff_z=z,
    )


def compute_all_slices(df: pd.DataFrame) -> list[AttributionSlice]:
    slices = [compute_slice(df, segment=None, action=None)]  # portfolio headline

    segments = sorted(s for s in df["segment"].dropna().unique())
    slices += [compute_slice(df, segment=seg, action=None) for seg in segments]

    treatment_actions = df[df["treatment_group"] == TreatmentGroup.ACTED.value]["action"]
    actions = sorted(a for a in treatment_actions.dropna().unique())
    slices += [compute_slice(df, segment=None, action=act) for act in actions]

    # Subtask 5: segment x action cells, only for combinations that actually
    # occur in the treatment arm (an empty cell tells us nothing).
    treatment_df = df[df["treatment_group"] == TreatmentGroup.ACTED.value]
    for seg in segments:
        seg_actions = sorted(
            a for a in treatment_df[treatment_df["segment"] == seg]["action"].dropna().unique()
        )
        slices += [compute_slice(df, segment=seg, action=act) for act in seg_actions]

    return slices


def diagnostic_action_by_archetype(df: pd.DataFrame, action: str) -> pd.DataFrame:
    """Diagnostic-only, verification-only -- tests the specific falsifiable
    claim that a given action's portfolio-level effect is concentrated in
    one archetype rather than broadly negative/positive across all of them.
    Reads customers.archetype (hidden ground truth) exactly as
    app/decision/evaluation.py's own evaluate_escalation_appropriateness()
    already does for the same purpose -- never fed back into a decision,
    never persisted to attribution_experiment_results. See DECISIONS.md."""
    rows = []
    archetypes = sorted(df["archetype"].dropna().unique())
    for archetype in archetypes:
        sub = df[df["archetype"] == archetype]
        s = compute_slice(sub, segment=None, action=action)
        if s.treatment_n == 0:
            continue
        rows.append(
            {
                "archetype": archetype,
                "treatment_n": s.treatment_n,
                "control_n": s.control_n,
                "treatment_recovery_rate": s.treatment_recovery_rate,
                "control_recovery_rate": s.control_recovery_rate,
                "incremental_recovery_rate": s.incremental_recovery_rate,
                "incremental_recovered_amount": s.incremental_recovered_amount,
                "recovery_rate_diff_z": s.recovery_rate_diff_z,
            }
        )
    return pd.DataFrame(rows)


def check_aggregation_consistency(
    pooled: AttributionSlice, stratified: list[AttributionSlice], label: str
) -> str | None:
    """Guardrail against the exact Simpson's-paradox-style failure subtask 5
    caught by hand for ESCALATE: a pooled slice's incremental_recovered_amount
    can disagree in SIGN with the sum of its own stratified decomposition
    when the stratifying variable (e.g. archetype) is unevenly distributed
    across the pooled population and has a very different control rate per
    stratum -- the pooled figure then reflects the stratifying mix, not the
    action's real effect. Print-only guardrail, not a gate: returns a
    warning string when pooled and the stratified sum disagree in sign
    (both non-trivial in magnitude), else None. Reused across actions, not
    just ESCALATE -- the failure mode isn't specific to it.

    Deliberately compares against a HIDDEN-ground-truth stratification
    (archetype, via diagnostic_action_by_archetype) -- same allowlisted
    exception category as that function itself. See DECISIONS.md."""
    stratified_sum = sum(s.incremental_recovered_amount for s in stratified)
    pooled_amt = pooled.incremental_recovered_amount

    MATERIALITY_FLOOR = 1_000.0  # ignore sign flips on trivially small figures
    if abs(pooled_amt) < MATERIALITY_FLOOR or abs(stratified_sum) < MATERIALITY_FLOOR:
        return None

    if (pooled_amt < 0) != (stratified_sum < 0):
        return (
            f"WARNING: {label}'s pooled incremental_recovered_amount (Rs.{pooled_amt:+,.0f}) "
            f"disagrees in SIGN with its archetype-stratified sum (Rs.{stratified_sum:+,.0f}) -- "
            f"likely a compositional (Simpson's-paradox-style) effect from an uneven archetype "
            f"mix, not a real reversal. Do not trust the pooled figure alone; inspect the "
            f"stratified breakdown before drawing a conclusion."
        )
    return None


def diagnostic_amount_by_archetype(df: pd.DataFrame) -> pd.DataFrame:
    """Diagnostic-only, hidden ground truth: is `amount` actually a clean
    OBSERVABLE proxy for strategic_enterprise (the archetype driving
    ESCALATE's targeting problem -- see DECISIONS.md), or just
    correlated-but-noisy? A real system can condition ACTION_UPLIFT on
    amount, never on archetype -- this checks whether that substitution is
    defensible before subtask 6 relies on it, rather than assuming the
    ~6-7x lognormal-mean gap in archetypes.py translates cleanly to
    separated real-data distributions."""
    return df.groupby("archetype")["amount"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])


def _to_record(s: AttributionSlice) -> AttributionExperimentResult:
    return AttributionExperimentResult(
        experiment_id=EXPERIMENT_ID,
        segment=s.segment,
        action=ActionType(s.action) if s.action else None,
        treatment_n=s.treatment_n,
        control_n=s.control_n,
        treatment_recovery_rate=s.treatment_recovery_rate,
        control_recovery_rate=s.control_recovery_rate,
        incremental_recovery_rate=s.incremental_recovery_rate,
        treatment_recovered_amount=round(s.treatment_recovered_amount, 2),
        control_recovered_amount=round(s.control_recovered_amount, 2),
        incremental_recovered_amount=round(s.incremental_recovered_amount, 2),
        treatment_cost=round(s.treatment_cost, 2),
        treatment_friction=round(s.treatment_friction, 2),
        incremental_net_recovery=round(s.incremental_net_recovery, 2),
        treatment_count_recovery_rate=s.treatment_count_recovery_rate,
        control_count_recovery_rate=s.control_count_recovery_rate,
        recovery_rate_diff_se=s.recovery_rate_diff_se,
        recovery_rate_diff_z=s.recovery_rate_diff_z,
    )


def persist_slices(slices: list[AttributionSlice]) -> int:
    """DELETE-then-INSERT for this EXPERIMENT_ID -- unlike attribution_records
    (one immutable row per invoice, fails loudly on rerun by design), this
    table is a derived report meant to be safely regenerated (e.g. after
    subtask 6 corrects ACTION_UPLIFT and this gets re-run for the
    before/after comparison) -- each rerun should reflect the latest
    computation, not accumulate stale duplicate rows alongside it."""
    session = SessionLocal()
    try:
        session.execute(
            delete(AttributionExperimentResult).where(AttributionExperimentResult.experiment_id == EXPERIMENT_ID)
        )
        for s in slices:
            session.add(_to_record(s))
        session.commit()
        return len(slices)
    finally:
        session.close()


def _fmt_z(z: float | None) -> str:
    return f"{z:+.1f}se" if z is not None else "n/a"


def _print_report(slices: list[AttributionSlice]) -> None:
    def _row(s: AttributionSlice, label: str) -> None:
        print(
            f"  {label:<34} treat_n={s.treatment_n:>4} ctrl_n={s.control_n:>4}  "
            f"treat_rate={s.treatment_recovery_rate:>6.1%}  ctrl_rate={s.control_recovery_rate:>6.1%}  "
            f"incr_rate={s.incremental_recovery_rate:>+7.1%}  incr_amt=Rs.{s.incremental_recovered_amount:>+13,.0f}  "
            f"net=Rs.{s.incremental_net_recovery:>+13,.0f}  z={_fmt_z(s.recovery_rate_diff_z):>8}"
        )

    portfolio = slices[0]
    print("Portfolio headline:")
    _row(portfolio, "ALL")

    print("\nPer segment:")
    for s in slices:
        if s.segment is not None and s.action is None:
            _row(s, s.segment)

    print("\nPer action (control matched by counterfactual_action):")
    for s in slices:
        if s.segment is None and s.action is not None:
            _row(s, s.action)

    print("\nPer segment x action:")
    for s in slices:
        if s.segment is not None and s.action is not None:
            _row(s, f"{s.segment} / {s.action}")


if __name__ == "__main__":
    df = load_attribution_data()
    slices = compute_all_slices(df)
    _print_report(slices)

    action_slices = [s for s in slices if s.segment is None and s.action is not None]
    print("\nAggregation-consistency check (pooled action vs. its own archetype-stratified sum):")
    any_warning = False
    for s in action_slices:
        by_archetype = diagnostic_action_by_archetype(df, s.action)
        stratified = [compute_slice(df[df["archetype"] == a], segment=None, action=s.action) for a in by_archetype["archetype"]]
        warning = check_aggregation_consistency(s, stratified, s.action)
        if warning:
            any_warning = True
            print(f"  {warning}")
    if not any_warning:
        print("  (none -- every action's pooled figure agrees in sign with its stratified sum)")

    print("\nDiagnostic (verification-only, hidden ground truth): ESCALATE by archetype")
    escalate_by_archetype = diagnostic_action_by_archetype(df, "escalate")
    print(escalate_by_archetype.to_string(index=False))

    print("\nDiagnostic (verification-only, hidden ground truth): amount distribution by archetype")
    print("(checking whether `amount` cleanly separates strategic_enterprise -- a real system can")
    print(" condition on amount, never on archetype -- before subtask 6 relies on it as a proxy)")
    print(diagnostic_amount_by_archetype(df).to_string())

    n = persist_slices(slices)
    print(f"\nPersisted {n} attribution_experiment_results rows for experiment_id={EXPERIMENT_ID!r}.")
