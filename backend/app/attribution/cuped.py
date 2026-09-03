"""CUPED (Controlled-experiment Using Pre-Existing Data) variance reduction
for the Day-5 attribution experiment.

Covariate: the Day-2 recovery model's calibrated probability, computed as
of due_date -- strictly before any treatment action (see
app/attribution/DECISIONS.md's "baseline_predicted_recovery" entry: "the
Day-2 ML model's own prediction, identical for both arms of a given
invoice"). base_probability = baseline_predicted_recovery / amount for the
count metric; baseline_predicted_recovery itself (already probability *
amount) for the amount metric.

**Important scope note on the "amount" metric**: CUPED's clean bias/
variance guarantees apply to a simple difference-in-means. `evaluate.py`'s
existing "amount-weighted recovery rate" is a RATIO-of-sums estimator
(sum(recovered)/sum(amount) per arm), which needs a different variance
treatment (delta method) that's out of scope for this build. What
AMOUNT_METRIC computes here instead is CUPED applied to the simple
per-invoice mean of `observed_recovery` (average rupees recovered per
invoice, treatment minus control) -- a real, well-defined, complementary
statistic, but NOT the same number as evaluate.py's amount-weighted rate.
Report it labeled as "average recovered amount per invoice", never as
"amount-weighted recovery rate" -- conflating the two would misrepresent
which statistic CUPED actually adjusted.

theta is fit ONCE, globally, from the full pooled experiment population --
standard CUPED practice, and deliberately NOT re-fit per slice, which would
reintroduce exactly the small-n noise CUPED is meant to reduce (many slices
already run under the 15-per-arm floor app/attribution's own low-n dimming
guards against elsewhere).

Centering constant is irrelevant to both the resulting effect and its SE --
CUPED's treatment/control difference-in-means is invariant to the additive
constant used to center X (the constant cancels in the subtraction), so any
fixed value works; the global mean is used purely for interpretability.

**Never used to select a preferred sign or replace the raw estimate.**
Every function here returns raw and CUPED-adjusted figures side by side --
see the "CUPED: report both, never replace" rule in DECISIONS.md. A
CUPED-adjusted effect existing alongside a raw effect of a different
apparent magnitude is expected (unbiased, not identical -- see the
unbiasedness test in tests/test_attribution_cuped.py) and is never grounds
to prefer one over the other when deciding what to report.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.models.enums import TreatmentGroup

COUNT_METRIC = "count"
AMOUNT_METRIC = "amount"


@dataclass(frozen=True)
class CupedTheta:
    """Global, population-level adjustment coefficients -- fit once from the
    full experiment population, reused for every slice."""

    count_theta: float
    count_corr: float
    count_x_mean: float
    amount_theta: float
    amount_corr: float
    amount_x_mean: float


def _covariate_columns(df: pd.DataFrame, metric: str) -> tuple[pd.Series, pd.Series]:
    """Returns (X, Y) for the given metric. X is always pre-treatment
    (baseline_predicted_recovery derives from decide_from_feature_row's
    due_date-cutoff scoring, computed identically regardless of the row's
    eventual treatment_group -- see module docstring)."""
    if metric == COUNT_METRIC:
        x = df["baseline_predicted_recovery"] / df["amount"]
        y = df["recovered"].astype(float)
    elif metric == AMOUNT_METRIC:
        x = df["baseline_predicted_recovery"].astype(float)
        y = df["observed_recovery"].astype(float)
    else:
        raise ValueError(f"unknown metric {metric!r}, expected {COUNT_METRIC!r} or {AMOUNT_METRIC!r}")
    return x, y


def fit_cuped_theta(df: pd.DataFrame) -> CupedTheta:
    """Fit theta/corr for both metrics from the full pooled experiment
    population (both arms together -- theta is a population-level
    covariate-outcome relationship, not something treatment assignment
    should influence under a correctly-randomized experiment)."""
    x_count, y_count = _covariate_columns(df, COUNT_METRIC)
    x_amount, y_amount = _covariate_columns(df, AMOUNT_METRIC)

    x_count_a, y_count_a = x_count.to_numpy(float), y_count.to_numpy(float)
    x_amount_a, y_amount_a = x_amount.to_numpy(float), y_amount.to_numpy(float)

    count_theta = float(np.cov(x_count_a, y_count_a, ddof=1)[0, 1] / np.var(x_count_a, ddof=1))
    count_corr = float(np.corrcoef(x_count_a, y_count_a)[0, 1])
    amount_theta = float(np.cov(x_amount_a, y_amount_a, ddof=1)[0, 1] / np.var(x_amount_a, ddof=1))
    amount_corr = float(np.corrcoef(x_amount_a, y_amount_a)[0, 1])

    return CupedTheta(
        count_theta=count_theta,
        count_corr=count_corr,
        count_x_mean=float(x_count_a.mean()),
        amount_theta=amount_theta,
        amount_corr=amount_corr,
        amount_x_mean=float(x_amount_a.mean()),
    )


@dataclass(frozen=True)
class CupedSliceResult:
    segment: str | None
    action: str | None
    metric: str
    treatment_n: int
    control_n: int
    raw_effect: float
    raw_se: float | None
    cuped_effect: float
    cuped_se: float | None
    se_reduction_pct: float | None
    theta: float
    corr: float


def _welch_se(y_t: np.ndarray, y_c: np.ndarray) -> float | None:
    """General two-sample SE (not the codebase's existing binomial
    p(1-p)/n formula) -- used uniformly for raw AND CUPED here so the
    before/after comparison is apples-to-apples on the same formula family.
    For a 0/1 count-metric Y this is numerically almost identical to the
    binomial formula (differs only by the ddof=1 vs ddof=0 population/sample
    variance convention); it's required (not just convenient) for the
    CUPED-adjusted values, which are no longer strictly 0/1."""
    if len(y_t) < 2 or len(y_c) < 2:
        return None
    variance = y_t.var(ddof=1) / len(y_t) + y_c.var(ddof=1) / len(y_c)
    if variance <= 0:
        return None
    return float(np.sqrt(variance))


def compute_cuped_slice(
    df: pd.DataFrame, theta: CupedTheta, segment: str | None, action: str | None, metric: str
) -> CupedSliceResult | None:
    """Mirrors app/attribution/evaluate.py's compute_slice() population-
    selection rule exactly (action slices match control by
    counterfactual_action, not the whole control pool) so the raw figures
    computed here reproduce compute_slice()'s own raw_effect -- this is
    what keeps 'raw vs. CUPED' an honest same-population comparison rather
    than two different populations that happen to share a label. Returns
    None for an empty slice (mirrors compute_slice()'s 0.0 fallback
    conceptually, but None is more honest here -- there is no meaningful
    variance-reduction claim to make about zero rows)."""
    treatment_df = df[df["treatment_group"] == TreatmentGroup.ACTED.value]
    control_df = df[df["treatment_group"] == TreatmentGroup.CONTROL.value]

    if segment is not None:
        treatment_df = treatment_df[treatment_df["segment"] == segment]
        control_df = control_df[control_df["segment"] == segment]
    if action is not None:
        treatment_df = treatment_df[treatment_df["action"] == action]
        control_df = control_df[control_df["counterfactual_action"] == action]

    treatment_n, control_n = len(treatment_df), len(control_df)
    if treatment_n == 0 or control_n == 0:
        return None

    if metric == COUNT_METRIC:
        th, corr, x_mean = theta.count_theta, theta.count_corr, theta.count_x_mean
    else:
        th, corr, x_mean = theta.amount_theta, theta.amount_corr, theta.amount_x_mean

    x_t, y_t = _covariate_columns(treatment_df, metric)
    x_c, y_c = _covariate_columns(control_df, metric)
    x_t_a, y_t_a = x_t.to_numpy(float), y_t.to_numpy(float)
    x_c_a, y_c_a = x_c.to_numpy(float), y_c.to_numpy(float)

    # Centering constant (x_mean, the GLOBAL pooled mean) is arbitrary --
    # cancels out of the treatment-vs-control difference regardless of what
    # constant is used. Kept for interpretability of the per-unit adjusted
    # values only, never load-bearing for the effect/SE below.
    y_t_adj = y_t_a - th * (x_t_a - x_mean)
    y_c_adj = y_c_a - th * (x_c_a - x_mean)

    raw_effect = float(y_t_a.mean() - y_c_a.mean())
    cuped_effect = float(y_t_adj.mean() - y_c_adj.mean())
    raw_se = _welch_se(y_t_a, y_c_a)
    cuped_se = _welch_se(y_t_adj, y_c_adj)
    se_reduction_pct = (1 - cuped_se / raw_se) * 100 if raw_se and cuped_se else None

    return CupedSliceResult(
        segment=segment,
        action=action,
        metric=metric,
        treatment_n=treatment_n,
        control_n=control_n,
        raw_effect=raw_effect,
        raw_se=raw_se,
        cuped_effect=cuped_effect,
        cuped_se=cuped_se,
        se_reduction_pct=se_reduction_pct,
        theta=th,
        corr=corr,
    )


def compute_pooled_cuped(df: pd.DataFrame) -> tuple[CupedSliceResult, CupedSliceResult]:
    """Convenience entry point for the headline (portfolio-level) figures --
    fits theta from the full population, then returns (count_result,
    amount_result) for the pooled slice. Per-segment/per-action slices can
    be computed by calling fit_cuped_theta() once and compute_cuped_slice()
    per cut, reusing the same theta throughout (see module docstring on why
    theta is global, not re-fit per slice)."""
    theta = fit_cuped_theta(df)
    count_result = compute_cuped_slice(df, theta, segment=None, action=None, metric=COUNT_METRIC)
    amount_result = compute_cuped_slice(df, theta, segment=None, action=None, metric=AMOUNT_METRIC)
    assert count_result is not None and amount_result is not None, "pooled slice can't be empty on a real experiment"
    return count_result, amount_result
