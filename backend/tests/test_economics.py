"""app/decision/economics.py tests: pure EV formula, no DB required."""
from app.decision.economics import (
    CANDIDATE_ACTIONS,
    compute_action_ev,
    generate_candidate_actions,
    materiality_threshold,
    probability_given_action,
    rank_actions,
    recommend_action,
)
from app.models.enums import ActionType


def test_probability_given_action_increases_with_action_uplift():
    base = 0.5
    wait = probability_given_action(base, ActionType.WAIT)
    email = probability_given_action(base, ActionType.EMAIL)
    escalate = probability_given_action(base, ActionType.ESCALATE)
    assert wait == base
    assert wait < email < escalate


def test_probability_given_action_clipped_to_calibration_band():
    assert probability_given_action(0.999, ActionType.ESCALATE) <= 0.99
    assert probability_given_action(0.0, ActionType.WAIT) >= 0.01


def test_probability_uplift_shrinks_as_base_probability_approaches_one():
    low_base_gain = probability_given_action(0.2, ActionType.ESCALATE) - 0.2
    high_base_gain = probability_given_action(0.95, ActionType.ESCALATE) - 0.95
    assert low_base_gain > high_base_gain


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
    # un-disputed (see test below) -- disputed must never surface it at all.
    ranked = rank_actions(base_probability=0.5, amount=300_000.0, is_disputed=True)
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


def test_large_invoice_moderate_risk_prefers_escalate_over_payment_link():
    # A large invoice at moderate confidence (e.g. a promise just broke,
    # dropping confidence from high to moderate) -- ESCALATE's higher uplift
    # is worth far more than its extra cost once amount is large enough,
    # so PAYMENT_LINK should not win by default here.
    ranked = rank_actions(base_probability=0.5, amount=300_000.0)
    top = ranked[0]
    assert top.action_type == ActionType.ESCALATE
    payment_link_ev = compute_action_ev(0.5, 300_000.0, ActionType.PAYMENT_LINK)
    assert top.expected_value > payment_link_ev.expected_value


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
