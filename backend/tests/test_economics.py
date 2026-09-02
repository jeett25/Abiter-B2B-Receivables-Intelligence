"""app/decision/economics.py tests: pure EV formula, no DB required."""
from app.decision.config import ESCALATE_LARGE_AMOUNT_THRESHOLD_INR, ESCALATE_LARGE_AMOUNT_UPLIFT
from app.decision.economics import (
    CANDIDATE_ACTIONS,
    action_uplift,
    compute_action_ev,
    generate_candidate_actions,
    materiality_threshold,
    probability_given_action,
    rank_actions,
    recommend_action,
)
from app.models.enums import ActionType

# A small, below-threshold amount for tests that are about generic uplift
# behavior, not the ESCALATE large-amount correction specifically -- keeps
# those tests' intent unchanged by the Day-5 amount-conditioned exception.
SMALL_AMOUNT = 20_000.0


def test_probability_given_action_increases_with_action_uplift():
    base = 0.5
    wait = probability_given_action(base, ActionType.WAIT, SMALL_AMOUNT)
    email = probability_given_action(base, ActionType.EMAIL, SMALL_AMOUNT)
    escalate = probability_given_action(base, ActionType.ESCALATE, SMALL_AMOUNT)
    assert wait == base
    assert wait < email < escalate


def test_probability_given_action_clipped_to_calibration_band():
    assert probability_given_action(0.999, ActionType.ESCALATE, SMALL_AMOUNT) <= 0.99
    assert probability_given_action(0.0, ActionType.WAIT, SMALL_AMOUNT) >= 0.01


def test_probability_uplift_shrinks_as_base_probability_approaches_one():
    low_base_gain = probability_given_action(0.2, ActionType.ESCALATE, SMALL_AMOUNT) - 0.2
    high_base_gain = probability_given_action(0.95, ActionType.ESCALATE, SMALL_AMOUNT) - 0.95
    assert low_base_gain > high_base_gain


def test_action_uplift_flat_for_every_action_below_the_escalate_threshold():
    assert action_uplift(ActionType.ESCALATE, ESCALATE_LARGE_AMOUNT_THRESHOLD_INR - 1) == 0.14


def test_action_uplift_reduced_for_escalate_at_or_above_the_threshold():
    assert action_uplift(ActionType.ESCALATE, ESCALATE_LARGE_AMOUNT_THRESHOLD_INR) == ESCALATE_LARGE_AMOUNT_UPLIFT
    assert action_uplift(ActionType.ESCALATE, 500_000.0) == ESCALATE_LARGE_AMOUNT_UPLIFT


def test_action_uplift_unaffected_for_every_other_action_regardless_of_amount():
    for action in (ActionType.EMAIL, ActionType.WHATSAPP, ActionType.PAYMENT_LINK, ActionType.VOICE):
        assert action_uplift(action, 1_000_000.0) == action_uplift(action, SMALL_AMOUNT)


def test_stop_never_in_candidate_set():
    assert ActionType.STOP not in generate_candidate_actions()
    assert ActionType.STOP not in generate_candidate_actions(is_disputed=True)
    assert ActionType.STOP not in CANDIDATE_ACTIONS


def test_disputed_invoice_excludes_escalate_and_voice():
    candidates = generate_candidate_actions(is_disputed=True)
    assert ActionType.ESCALATE not in candidates
    assert ActionType.VOICE not in candidates
    assert ActionType.EMAIL in candidates
    assert ActionType.WHATSAPP in candidates
    assert ActionType.PAYMENT_LINK in candidates
    assert ActionType.WAIT in candidates


def test_disputed_flag_removes_escalate_from_ranking_even_when_it_would_win():
    # Same large-invoice/moderate-risk scenario that makes ESCALATE win
    # un-disputed below the Day-5 large-amount threshold (see test below) --
    # disputed must never surface it at all, regardless of amount.
    ranked = rank_actions(base_probability=0.5, amount=90_000.0, is_disputed=True)
    assert ActionType.ESCALATE not in [ev.action_type for ev in ranked]


def test_pitch_example_low_value_low_odds_prefers_wait_over_voice():
    # From the project pitch: a ~Rs800 invoice at 12% recovery odds is a net
    # loss to chase with a ~Rs250 intervention (VOICE, cost=200 here).
    top = recommend_action(base_probability=0.12, amount=800.0)
    assert top.action_type == ActionType.WAIT
    voice_ev = compute_action_ev(0.12, 800.0, ActionType.VOICE)
    assert voice_ev.expected_value < top.expected_value


def test_high_confidence_customer_recommends_wait():
    # Reliable-payer-like base probability: little headroom left for any
    # action's uplift to be worth its cost.
    top = recommend_action(base_probability=0.95, amount=50_000.0)
    assert top.action_type == ActionType.WAIT


def test_moderate_invoice_moderate_risk_prefers_escalate_over_payment_link():
    # A moderately-large invoice (below the Day-5 ESCALATE large-amount
    # threshold, so its full uplift still applies) at moderate confidence
    # (e.g. a promise just broke, dropping confidence from high to
    # moderate) -- ESCALATE's higher uplift is worth far more than its
    # extra cost, so PAYMENT_LINK should not win by default here.
    amount = 90_000.0
    ranked = rank_actions(base_probability=0.5, amount=amount)
    top = ranked[0]
    assert top.action_type == ActionType.ESCALATE
    payment_link_ev = compute_action_ev(0.5, amount, ActionType.PAYMENT_LINK)
    assert top.expected_value > payment_link_ev.expected_value


def test_large_invoice_no_longer_prefers_escalate_after_uplift_correction():
    """Day-5 finding: this exact scenario (base=0.5, amount=300,000) used to
    make ESCALATE win (EV~170,270 under the old flat 0.14 uplift) -- the
    randomized-holdout experiment found that assumption unsupported for
    large invoices (see app/decision/DECISIONS.md), so above
    ESCALATE_LARGE_AMOUNT_THRESHOLD_INR its uplift now correctly loses to
    VOICE, whose uplift was untouched by the correction."""
    amount = 300_000.0
    ranked = rank_actions(base_probability=0.5, amount=amount)
    assert ranked[0].action_type == ActionType.VOICE

    escalate_ev = next(ev for ev in ranked if ev.action_type == ActionType.ESCALATE)
    voice_ev = next(ev for ev in ranked if ev.action_type == ActionType.VOICE)
    assert voice_ev.expected_value > escalate_ev.expected_value
    # ESCALATE has fallen behind WHATSAPP and PAYMENT_LINK too, not just VOICE.
    assert ranked.index(escalate_ev) >= 3


def test_friction_grows_with_prior_contact_count_and_can_flip_ranking():
    ev_first_contact = compute_action_ev(0.4, 20_000.0, ActionType.ESCALATE, prior_contact_count=0)
    ev_after_many_contacts = compute_action_ev(0.4, 20_000.0, ActionType.ESCALATE, prior_contact_count=10)
    assert ev_after_many_contacts.friction > ev_first_contact.friction
    assert ev_after_many_contacts.expected_value < ev_first_contact.expected_value


def test_ranking_is_deterministic():
    first = rank_actions(base_probability=0.6, amount=45_000.0, prior_contact_count=2)
    second = rank_actions(base_probability=0.6, amount=45_000.0, prior_contact_count=2)
    assert first == second


def test_rank_actions_sorted_descending_by_expected_value():
    ranked = rank_actions(base_probability=0.4, amount=60_000.0)
    values = [ev.expected_value for ev in ranked]
    assert values == sorted(values, reverse=True)


def test_recommend_action_abstains_when_top_edge_over_wait_is_immaterial():
    # The top-ranked action's raw EV is technically above WAIT's here
    # (near-zero cost, small positive uplift), but the edge is a few rupees
    # on a Rs50,000 invoice -- below materiality_threshold(50_000), so
    # recommend_action must fall back to WAIT even though rank_actions()
    # ranks an actionable type first.
    ranked = rank_actions(base_probability=0.95, amount=50_000.0)
    assert ranked[0].action_type != ActionType.WAIT
    top_edge = ranked[0].expected_value - next(
        ev.expected_value for ev in ranked if ev.action_type == ActionType.WAIT
    )
    assert top_edge < materiality_threshold(50_000.0)

    recommended = recommend_action(base_probability=0.95, amount=50_000.0)
    assert recommended.action_type == ActionType.WAIT


def test_materiality_threshold_scales_with_amount_not_just_flat_floor():
    assert materiality_threshold(1_000.0) == 50.0  # flat floor dominates
    assert materiality_threshold(100_000.0) == 1_000.0  # 1% dominates


# --- Root-cause context (2026-09-02): a bounded nudge to specific actions'
# uplift, applied only above ROOT_CAUSE_CONFIDENCE_THRESHOLD -- context for
# Economics, never a selector. See app/decision/config.py's
# ROOT_CAUSE_UPLIFT_ADJUSTMENT for the exact deltas.


def test_action_uplift_unaffected_when_root_cause_confidence_below_threshold():
    baseline = action_uplift(ActionType.PAYMENT_LINK, SMALL_AMOUNT)
    low_confidence = action_uplift(ActionType.PAYMENT_LINK, SMALL_AMOUNT, "cash_flow_stress", 0.55)
    assert low_confidence == baseline


def test_action_uplift_nudged_for_cash_flow_stress_above_threshold():
    baseline = action_uplift(ActionType.PAYMENT_LINK, SMALL_AMOUNT)
    nudged = action_uplift(ActionType.PAYMENT_LINK, SMALL_AMOUNT, "cash_flow_stress", 0.8)
    assert nudged > baseline


def test_action_uplift_nudge_is_bounded_small_not_dominant():
    # The nudge must never be large enough to flip a clearly-dominated
    # action into the winner on its own -- confirmed here against the
    # actual gap between PAYMENT_LINK and a clearly stronger candidate.
    baseline = action_uplift(ActionType.PAYMENT_LINK, SMALL_AMOUNT)
    nudged = action_uplift(ActionType.PAYMENT_LINK, SMALL_AMOUNT, "cash_flow_stress", 0.99)
    assert nudged - baseline <= 0.05


def test_action_uplift_unaffected_for_actions_with_no_configured_root_cause_adjustment():
    baseline = action_uplift(ActionType.ESCALATE, SMALL_AMOUNT)
    with_context = action_uplift(ActionType.ESCALATE, SMALL_AMOUNT, "cash_flow_stress", 0.9)
    assert with_context == baseline


def test_rank_actions_defaults_preserve_prior_behavior_with_no_root_cause_context():
    with_context_none = rank_actions(base_probability=0.4, amount=60_000.0)
    explicit_none = rank_actions(base_probability=0.4, amount=60_000.0, root_cause_label=None, root_cause_probability=0.0)
    assert with_context_none == explicit_none


def test_recommend_action_still_authoritative_over_root_cause_context():
    # Economics + Policy remain the decision authority -- a confident
    # root-cause context must not bypass the materiality-gated abstention
    # rule that already sends this case to WAIT.
    baseline = recommend_action(base_probability=0.95, amount=50_000.0)
    with_context = recommend_action(base_probability=0.95, amount=50_000.0, root_cause_label="oversight", root_cause_probability=0.9)
    assert baseline.action_type == ActionType.WAIT
    assert with_context.action_type == ActionType.WAIT
