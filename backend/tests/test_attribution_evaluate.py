"""app/attribution/evaluate.py tests: pure compute_slice()/compute_all_slices()
checks on a hand-built DataFrame (matching load_attribution_data()'s
post-processing shape -- plain .value strings, not enum objects), plus one
integration test against the real persisted attribution_records."""
import math

import pandas as pd
import pytest

from app.attribution.evaluate import (
    AttributionSlice,
    _two_proportion_se_and_z,
    check_aggregation_consistency,
    compute_all_slices,
    compute_slice,
    diagnostic_action_by_archetype,
    diagnostic_amount_by_archetype,
    load_attribution_data,
    persist_slices,
)
from app.decision.config import INTERVENTION_COST_INR
from app.decision.economics import friction_cost
from app.models.enums import ActionType, TreatmentGroup


def _row(
    group,
    action=None,
    counterfactual_action=None,
    segment="SMB",
    archetype="chronic_late",
    amount=10_000.0,
    observed_recovery=0.0,
):
    return {
        "treatment_group": group,
        "action": action,
        "counterfactual_action": counterfactual_action,
        "segment": segment,
        "archetype": archetype,
        "amount": amount,
        "observed_recovery": observed_recovery,
        "recovered": observed_recovery > 0,
    }


ACTED = TreatmentGroup.ACTED.value
CONTROL = TreatmentGroup.CONTROL.value


def test_matched_rates_give_zero_incremental_recovery():
    df = pd.DataFrame(
        [
            _row(ACTED, action="whatsapp", amount=10_000.0, observed_recovery=10_000.0),
            _row(ACTED, action="whatsapp", amount=10_000.0, observed_recovery=0.0),
            _row(CONTROL, counterfactual_action="whatsapp", amount=10_000.0, observed_recovery=10_000.0),
            _row(CONTROL, counterfactual_action="whatsapp", amount=10_000.0, observed_recovery=0.0),
        ]
    )
    s = compute_slice(df, segment=None, action=None)
    assert s.treatment_recovery_rate == 0.5
    assert s.control_recovery_rate == 0.5
    assert s.incremental_recovery_rate == 0.0
    assert s.incremental_recovered_amount == 0.0


def test_positive_lift_produces_positive_incremental_amount():
    df = pd.DataFrame(
        [
            _row(ACTED, action="escalate", amount=100_000.0, observed_recovery=100_000.0),
            _row(ACTED, action="escalate", amount=100_000.0, observed_recovery=100_000.0),
            _row(CONTROL, counterfactual_action="escalate", amount=100_000.0, observed_recovery=100_000.0),
            _row(CONTROL, counterfactual_action="escalate", amount=100_000.0, observed_recovery=0.0),
        ]
    )
    s = compute_slice(df, segment=None, action=None)
    assert s.treatment_recovery_rate == 1.0
    assert s.control_recovery_rate == 0.5
    # incremental = treatment_recovered(200,000) - control_rate(0.5)*treatment_total_amount(200,000) = 100,000
    assert s.incremental_recovered_amount == 100_000.0
    assert s.incremental_recovery_rate == pytest.approx(0.5)


def test_recovery_rate_is_amount_weighted_not_count_weighted():
    """Regression test for the exact bug the real run's numbers caught:
    mixing a count-based rate into the dollar-amount formula can make a
    POSITIVE rate lift imply a NEGATIVE incremental amount, if recovered
    invoices skew small relative to the whole population. Constructed so a
    naive count-based rate would read as a positive ~16.7% lift (2/3 vs
    1/2), while the true dollar-weighted picture is a loss."""
    df = pd.DataFrame(
        [
            # treatment: 2 small invoices recover, 1 huge one does not --
            # count-rate = 2/3 = 66.7%, amount-rate = 20,000 / 1,020,000 = ~2.0%
            _row(ACTED, action="escalate", amount=10_000.0, observed_recovery=10_000.0),
            _row(ACTED, action="escalate", amount=10_000.0, observed_recovery=10_000.0),
            _row(ACTED, action="escalate", amount=1_000_000.0, observed_recovery=0.0),
            # control: 1 of 2 equally-sized invoices recovers -- count-rate
            # = amount-rate = 50%
            _row(CONTROL, counterfactual_action="escalate", amount=10_000.0, observed_recovery=10_000.0),
            _row(CONTROL, counterfactual_action="escalate", amount=10_000.0, observed_recovery=0.0),
        ]
    )
    s = compute_slice(df, segment=None, action="escalate")

    # amount-weighted treatment rate is ~2%, nowhere near a naive 66.7% count rate
    assert s.treatment_recovery_rate == pytest.approx(20_000 / 1_020_000)
    assert s.control_recovery_rate == 0.5
    assert s.incremental_recovery_rate < 0  # a real loss, not the positive count-rate would suggest
    assert s.incremental_recovered_amount < 0
    # internally consistent: rate sign and dollar sign must always agree
    assert (s.incremental_recovery_rate < 0) == (s.incremental_recovered_amount < 0)


def test_segment_filter_isolates_the_right_rows():
    df = pd.DataFrame(
        [
            _row(ACTED, action="wait", segment="Enterprise", observed_recovery=0.0),
            _row(CONTROL, counterfactual_action="wait", segment="Enterprise", observed_recovery=0.0),
            _row(ACTED, action="wait", segment="SMB", observed_recovery=10_000.0),
            _row(CONTROL, counterfactual_action="wait", segment="SMB", observed_recovery=10_000.0),
        ]
    )
    smb = compute_slice(df, segment="SMB", action=None)
    assert smb.treatment_n == 1
    assert smb.treatment_recovery_rate == 1.0

    enterprise = compute_slice(df, segment="Enterprise", action=None)
    assert enterprise.treatment_n == 1
    assert enterprise.treatment_recovery_rate == 0.0


def test_action_filter_matches_control_by_counterfactual_not_whole_pool():
    df = pd.DataFrame(
        [
            _row(ACTED, action="escalate", observed_recovery=10_000.0),
            # control matched to escalate: recovers
            _row(CONTROL, counterfactual_action="escalate", observed_recovery=10_000.0),
            # control matched to a DIFFERENT counterfactual action: never recovers,
            # must NOT be included in escalate's control_n/control_recovery_rate
            _row(CONTROL, counterfactual_action="wait", observed_recovery=0.0),
        ]
    )
    s = compute_slice(df, segment=None, action="escalate")
    assert s.treatment_n == 1
    assert s.control_n == 1  # not 2 -- the "wait"-matched control row is excluded
    assert s.control_recovery_rate == 1.0


def test_treatment_cost_and_friction_match_the_real_economics_config():
    df = pd.DataFrame(
        [
            _row(ACTED, action="whatsapp", observed_recovery=0.0),
            _row(ACTED, action="whatsapp", observed_recovery=0.0),
        ]
    )
    s = compute_slice(df, segment=None, action="whatsapp")
    expected_cost = 2 * INTERVENTION_COST_INR[ActionType.WHATSAPP]
    expected_friction = 2 * friction_cost(ActionType.WHATSAPP, prior_contact_count=0)
    assert s.treatment_cost == expected_cost
    assert s.treatment_friction == expected_friction


def test_compute_all_slices_includes_portfolio_every_segment_and_every_action():
    df = pd.DataFrame(
        [
            _row(ACTED, action="wait", segment="SMB", observed_recovery=0.0),
            _row(ACTED, action="escalate", segment="Enterprise", observed_recovery=10_000.0),
            _row(CONTROL, counterfactual_action="wait", segment="SMB", observed_recovery=0.0),
            _row(CONTROL, counterfactual_action="escalate", segment="Enterprise", observed_recovery=0.0),
        ]
    )
    slices = compute_all_slices(df)

    assert slices[0].segment is None and slices[0].action is None  # portfolio first

    segments = {s.segment for s in slices if s.segment is not None and s.action is None}
    assert segments == {"SMB", "Enterprise"}

    actions = {s.action for s in slices if s.action is not None}
    assert actions == {"wait", "escalate"}


def test_two_proportion_se_and_z_matches_hand_computation():
    # p1=0.6, n1=100, p2=0.5, n2=100
    se, z = _two_proportion_se_and_z(0.6, 100, 0.5, 100)
    expected_se = math.sqrt((0.6 * 0.4 / 100) + (0.5 * 0.5 / 100))
    assert se == pytest.approx(expected_se)
    assert z == pytest.approx((0.6 - 0.5) / expected_se)


def test_two_proportion_se_and_z_undefined_when_either_arm_empty():
    assert _two_proportion_se_and_z(0.5, 0, 0.5, 10) == (None, None)
    assert _two_proportion_se_and_z(0.5, 10, 0.5, 0) == (None, None)


def test_compute_slice_populates_count_based_rate_and_z_separately_from_amount_rate():
    """The exact split subtask 5 was built to enforce: WAIT's true effect is
    zero by construction (no archetype action_effects entry), so a
    non-trivial z here would flag noise, not signal -- verified structurally
    (fields exist and are internally consistent), not by asserting a
    specific z value (which depends on the random data)."""
    df = pd.DataFrame(
        [
            _row(ACTED, action="wait", observed_recovery=10_000.0),
            _row(ACTED, action="wait", observed_recovery=0.0),
            _row(CONTROL, counterfactual_action="wait", observed_recovery=10_000.0),
            _row(CONTROL, counterfactual_action="wait", observed_recovery=0.0),
        ]
    )
    s = compute_slice(df, segment=None, action="wait")
    assert s.treatment_count_recovery_rate == 0.5
    assert s.control_count_recovery_rate == 0.5
    assert s.recovery_rate_diff_se is not None
    assert s.recovery_rate_diff_z == pytest.approx(0.0)
    # count-based and amount-weighted happen to match here (equal amounts),
    # but they are still two structurally separate fields, not one value
    # read twice.
    assert s.treatment_count_recovery_rate == s.treatment_recovery_rate


def test_compute_all_slices_includes_segment_by_action_cells():
    df = pd.DataFrame(
        [
            _row(ACTED, action="escalate", segment="Enterprise", observed_recovery=0.0),
            _row(CONTROL, counterfactual_action="escalate", segment="Enterprise", observed_recovery=10_000.0),
            _row(ACTED, action="whatsapp", segment="SMB", observed_recovery=10_000.0),
            _row(CONTROL, counterfactual_action="whatsapp", segment="SMB", observed_recovery=10_000.0),
        ]
    )
    slices = compute_all_slices(df)
    combo_slices = {(s.segment, s.action) for s in slices if s.segment is not None and s.action is not None}
    assert ("Enterprise", "escalate") in combo_slices
    assert ("SMB", "whatsapp") in combo_slices
    # a combination that never occurs in treatment must not be fabricated
    assert ("Enterprise", "whatsapp") not in combo_slices


def test_diagnostic_action_by_archetype_isolates_the_failing_archetype():
    """Constructed so ESCALATE looks fine for one archetype and clearly
    negative for another -- diagnostic_action_by_archetype must surface
    that split, not average it away."""
    df = pd.DataFrame(
        [
            _row(ACTED, action="escalate", archetype="chronic_late", observed_recovery=10_000.0),
            _row(CONTROL, counterfactual_action="escalate", archetype="chronic_late", observed_recovery=0.0),
            _row(ACTED, action="escalate", archetype="strategic_enterprise", observed_recovery=0.0),
            _row(CONTROL, counterfactual_action="escalate", archetype="strategic_enterprise", observed_recovery=10_000.0),
        ]
    )
    result = diagnostic_action_by_archetype(df, "escalate")
    by_archetype = result.set_index("archetype")

    assert by_archetype.loc["chronic_late", "incremental_recovery_rate"] > 0
    assert by_archetype.loc["strategic_enterprise", "incremental_recovery_rate"] < 0


def _slice(incremental_recovered_amount, treatment_n=10, control_n=10):
    """check_aggregation_consistency only reads incremental_recovered_amount
    -- other fields are placeholders."""
    return AttributionSlice(
        segment=None,
        action="escalate",
        treatment_n=treatment_n,
        control_n=control_n,
        treatment_recovery_rate=0.0,
        control_recovery_rate=0.0,
        incremental_recovery_rate=0.0,
        treatment_recovered_amount=0.0,
        control_recovered_amount=0.0,
        incremental_recovered_amount=incremental_recovered_amount,
        treatment_cost=0.0,
        treatment_friction=0.0,
        incremental_net_recovery=0.0,
        treatment_count_recovery_rate=None,
        control_count_recovery_rate=None,
        recovery_rate_diff_se=None,
        recovery_rate_diff_z=None,
    )


def test_check_aggregation_consistency_flags_sign_disagreement():
    pooled = _slice(-797_115.0)
    stratified = [_slice(980_732.0), _slice(-84_522.0), _slice(-260_640.0)]
    warning = check_aggregation_consistency(pooled, stratified, "escalate")
    assert warning is not None
    assert "escalate" in warning
    assert "SIGN" in warning


def test_check_aggregation_consistency_no_warning_when_signs_agree():
    pooled = _slice(50_000.0)
    stratified = [_slice(30_000.0), _slice(20_000.0)]
    assert check_aggregation_consistency(pooled, stratified, "whatsapp") is None


def test_check_aggregation_consistency_ignores_trivially_small_amounts():
    pooled = _slice(-10.0)
    stratified = [_slice(5.0), _slice(5.0)]
    assert check_aggregation_consistency(pooled, stratified, "voice") is None


def test_diagnostic_amount_by_archetype_groups_by_archetype():
    df = pd.DataFrame(
        [
            _row(ACTED, archetype="strategic_enterprise", amount=200_000.0),
            _row(ACTED, archetype="strategic_enterprise", amount=220_000.0),
            _row(ACTED, archetype="chronic_late", amount=30_000.0),
            _row(ACTED, archetype="chronic_late", amount=35_000.0),
        ]
    )
    result = diagnostic_amount_by_archetype(df)
    assert set(result.index) == {"strategic_enterprise", "chronic_late"}
    assert result.loc["strategic_enterprise", "min"] > result.loc["chronic_late", "max"]


def test_load_attribution_data_and_persist_against_real_db(db_session):
    df = load_attribution_data()
    assert len(df) > 0
    assert set(df["treatment_group"].unique()) <= {"acted", "control"}
    # control rows always have a counterfactual_action, never a real action
    control = df[df["treatment_group"] == "control"]
    assert control["action"].isna().all()
    assert control["counterfactual_action"].notna().all()

    treatment = df[df["treatment_group"] == "acted"]
    assert treatment["action"].notna().all()
    assert treatment["counterfactual_action"].isna().all()

    assert df["archetype"].notna().all()  # present for diagnostic_action_by_archetype()

    slices = compute_all_slices(df)
    n = persist_slices(slices)  # DELETE-then-INSERT for EXPERIMENT_ID -- safe to rerun
    assert n == len(slices)

    escalate_by_archetype = diagnostic_action_by_archetype(df, "escalate")
    assert len(escalate_by_archetype) > 0
    assert "strategic_enterprise" in escalate_by_archetype["archetype"].values
