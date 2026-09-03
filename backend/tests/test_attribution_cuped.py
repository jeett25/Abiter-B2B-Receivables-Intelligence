"""app/attribution/cuped.py tests: unbiasedness + real variance reduction
on synthetic data (controlled correlation, known true effect), covariate
pre-treatment-balance and real variance reduction on the live experiment
data, and a cross-check that compute_cuped_slice()'s raw figures match
evaluate.compute_slice()'s own population-selection rule exactly."""
import numpy as np
import pandas as pd
import pytest

from app.attribution.cuped import (
    AMOUNT_METRIC,
    COUNT_METRIC,
    compute_cuped_slice,
    compute_pooled_cuped,
    fit_cuped_theta,
)
from app.attribution.evaluate import compute_slice, load_attribution_data
from app.models.enums import TreatmentGroup

ACTED = TreatmentGroup.ACTED.value
CONTROL = TreatmentGroup.CONTROL.value


def _synthetic_experiment(n_per_arm: int, true_effect: float, seed: int = 42) -> pd.DataFrame:
    """Controlled correlation between X (a 'probability') and Y (a 0/1
    recovery outcome): p_i = clip(0.6*X_i + 0.1, 0, 1) + true_effect if
    treated. amount is fixed so baseline_predicted_recovery = X * amount
    reduces to a simple rescaling -- correlation carries through unchanged."""
    rng = np.random.default_rng(seed)
    amount = 10_000.0
    rows = []
    for group, is_treated in ((ACTED, True), (CONTROL, False)):
        x = rng.uniform(0.1, 0.9, size=n_per_arm)
        p = np.clip(0.6 * x + 0.1 + (true_effect if is_treated else 0.0), 0.0, 1.0)
        recovered = rng.random(n_per_arm) < p
        for xi, ri in zip(x, recovered):
            rows.append(
                {
                    "treatment_group": group,
                    "action": "whatsapp" if is_treated else None,
                    "counterfactual_action": None if is_treated else "whatsapp",
                    "segment": "SMB",
                    "amount": amount,
                    "baseline_predicted_recovery": xi * amount,
                    "observed_recovery": float(amount) if ri else 0.0,
                    "recovered": bool(ri),
                }
            )
    return pd.DataFrame(rows)


def test_cuped_is_unbiased_and_reduces_variance_on_synthetic_data():
    true_effect = 0.05
    df = _synthetic_experiment(n_per_arm=1500, true_effect=true_effect)
    theta = fit_cuped_theta(df)

    # Real, non-trivial correlation by construction -- otherwise the
    # variance-reduction assertion below would be a vacuous pass.
    assert theta.count_corr > 0.25

    result = compute_cuped_slice(df, theta, segment=None, action=None, metric=COUNT_METRIC)
    assert result is not None

    # Unbiasedness: both raw and CUPED-adjusted effects should land close to
    # the TRUE injected effect (well within their own standard errors) --
    # CUPED changes precision, not what's being estimated.
    assert abs(result.raw_effect - true_effect) < 4 * result.raw_se
    assert abs(result.cuped_effect - true_effect) < 4 * result.cuped_se

    # The actual point of CUPED: strictly smaller SE given real correlation.
    assert result.cuped_se < result.raw_se
    assert result.se_reduction_pct > 0


def test_cuped_with_zero_correlation_covariate_does_not_bias_the_effect():
    """A covariate with essentially no relationship to the outcome should
    leave the effect estimate close to unchanged (theta near 0) -- CUPED
    must never distort the result when the covariate isn't informative."""
    rng = np.random.default_rng(7)
    n = 1000
    amount = 10_000.0
    rows = []
    for group, is_treated in ((ACTED, True), (CONTROL, False)):
        x = rng.uniform(0.1, 0.9, size=n)  # independent of outcome by construction
        p = 0.5 + (0.04 if is_treated else 0.0)
        recovered = rng.random(n) < p
        for xi, ri in zip(x, recovered):
            rows.append(
                {
                    "treatment_group": group,
                    "action": "whatsapp" if is_treated else None,
                    "counterfactual_action": None if is_treated else "whatsapp",
                    "segment": "SMB",
                    "amount": amount,
                    "baseline_predicted_recovery": xi * amount,
                    "observed_recovery": float(amount) if ri else 0.0,
                    "recovered": bool(ri),
                }
            )
    df = pd.DataFrame(rows)
    theta = fit_cuped_theta(df)
    assert abs(theta.count_corr) < 0.1

    result = compute_cuped_slice(df, theta, segment=None, action=None, metric=COUNT_METRIC)
    assert result is not None
    assert abs(result.cuped_effect - result.raw_effect) < 0.02  # near-identical, not distorted


def test_cuped_slice_raw_effect_matches_compute_slice_population_selection():
    """Cross-check: compute_cuped_slice() must select the SAME
    treatment/control population evaluate.compute_slice() does (action
    slices matched by counterfactual_action) -- otherwise 'raw' here isn't
    the same population as the codebase's own reported raw figure."""
    df = _synthetic_experiment(n_per_arm=200, true_effect=0.05)
    theta = fit_cuped_theta(df)

    for action in ("whatsapp",):
        slice_result = compute_slice(df, segment=None, action=action)
        cuped_result = compute_cuped_slice(df, theta, segment=None, action=action, metric=COUNT_METRIC)
        assert cuped_result is not None
        expected_raw = slice_result.treatment_count_recovery_rate - slice_result.control_count_recovery_rate
        assert cuped_result.raw_effect == pytest.approx(expected_raw, abs=1e-9)
        assert cuped_result.treatment_n == slice_result.treatment_n
        assert cuped_result.control_n == slice_result.control_n


def test_covariate_is_balanced_across_treatment_and_control_on_real_data():
    """Pre-treatment-only-ness check on the real experiment: a covariate
    that's genuinely computed before treatment assignment (as
    baseline_predicted_recovery is -- see module docstring) should not
    differ systematically between arms under correct randomization. A
    material imbalance here would be a red flag for either a broken
    randomization or a covariate that secretly depends on treatment."""
    df = load_attribution_data()
    t = df[df["treatment_group"] == ACTED]
    c = df[df["treatment_group"] == CONTROL]

    t_prob = (t["baseline_predicted_recovery"] / t["amount"]).mean()
    c_prob = (c["baseline_predicted_recovery"] / c["amount"]).mean()
    pooled_std = (t["baseline_predicted_recovery"] / t["amount"]).std()

    # Loose, sanity-level bound (not a formal balance test) -- means should
    # be within a fraction of a standard deviation of each other on a truly
    # randomized, pre-treatment covariate.
    assert abs(t_prob - c_prob) < 0.5 * pooled_std


def test_cuped_reduces_variance_on_real_pooled_experiment_data():
    df = load_attribution_data()
    count_result, amount_result = compute_pooled_cuped(df)

    assert count_result.raw_se is not None and count_result.cuped_se is not None
    assert count_result.cuped_se < count_result.raw_se

    assert amount_result.raw_se is not None and amount_result.cuped_se is not None
    assert amount_result.cuped_se < amount_result.raw_se
