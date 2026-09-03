"""Recovery Economics Engine: candidate action generation, action-specific
expected value, and ranking.

EV(a) = P(recovery|a,x) * Amount - InterventionCost(a) - FrictionCost(a)

"""
from __future__ import annotations

from dataclasses import dataclass

from app.decision.config import (
    ACTION_UPLIFT,
    ESCALATE_LARGE_AMOUNT_THRESHOLD_INR,
    ESCALATE_LARGE_AMOUNT_UPLIFT,
    FRICTION_BASE_INR,
    FRICTION_GROWTH_PER_PRIOR_CONTACT,
    INTERVENTION_COST_INR,
    MATERIALITY_FLOOR_INR,
    MATERIALITY_FRACTION_OF_AMOUNT,
    ROOT_CAUSE_CONFIDENCE_THRESHOLD,
    ROOT_CAUSE_UPLIFT_ADJUSTMENT,
)
from app.ml.config import CALIBRATED_PROBABILITY_CEILING, CALIBRATED_PROBABILITY_FLOOR
from app.models.enums import ActionType

CANDIDATE_ACTIONS: list[ActionType] = [
    ActionType.WAIT,
    ActionType.EMAIL,
    ActionType.WHATSAPP,
    ActionType.PAYMENT_LINK,
    ActionType.VOICE,
    ActionType.ESCALATE,
]

DISPUTE_EXCLUDED_ACTIONS = {ActionType.ESCALATE, ActionType.VOICE}


@dataclass(frozen=True)
class ActionEV:
    action_type: ActionType
    probability: float
    cost: float
    friction: float
    expected_value: float


def action_uplift(
    action_type: ActionType,
    amount: float,
    root_cause_label: str | None = None,
    root_cause_probability: float = 0.0,
) -> float:
    """ACTION_UPLIFT's flat per-action value, with two conditioned
    exceptions: ESCALATE above ESCALATE_LARGE_AMOUNT_THRESHOLD_INR (Day-5
    evidence, see docs/decision-DECISIONS.md), and a small root-cause nudge
    (root_cause_label in {"cash_flow_stress", "oversight"}, from the
    non-disputed-only classifier in app/ml/train_root_cause.py) applied only
    when root_cause_probability clears ROOT_CAUSE_CONFIDENCE_THRESHOLD. Both
    are narrow, evidence- or design-scoped corrections, not a general
    "action x context" framework -- every other action/context combination
    stays a flat lookup."""
    if action_type == ActionType.ESCALATE and amount >= ESCALATE_LARGE_AMOUNT_THRESHOLD_INR:
        base = ESCALATE_LARGE_AMOUNT_UPLIFT
    else:
        base = ACTION_UPLIFT[action_type]

    if root_cause_label and root_cause_probability >= ROOT_CAUSE_CONFIDENCE_THRESHOLD:
        base += ROOT_CAUSE_UPLIFT_ADJUSTMENT.get(root_cause_label, {}).get(action_type, 0.0)

    return base


def probability_given_action(
    base_probability: float,
    action_type: ActionType,
    amount: float,
    root_cause_label: str | None = None,
    root_cause_probability: float = 0.0,
) -> float:
    uplift = action_uplift(action_type, amount, root_cause_label, root_cause_probability)
    raw = base_probability + uplift * (1 - base_probability)
    return min(max(raw, CALIBRATED_PROBABILITY_FLOOR), CALIBRATED_PROBABILITY_CEILING)


def friction_cost(action_type: ActionType, prior_contact_count: int = 0) -> float:
    base = FRICTION_BASE_INR[action_type]
    return base * (1 + FRICTION_GROWTH_PER_PRIOR_CONTACT * max(prior_contact_count, 0))


def generate_candidate_actions(is_disputed: bool = False) -> list[ActionType]:
    if is_disputed:
        return [a for a in CANDIDATE_ACTIONS if a not in DISPUTE_EXCLUDED_ACTIONS]
    return list(CANDIDATE_ACTIONS)


def compute_action_ev(
    base_probability: float,
    amount: float,
    action_type: ActionType,
    prior_contact_count: int = 0,
    root_cause_label: str | None = None,
    root_cause_probability: float = 0.0,
) -> ActionEV:
    probability = probability_given_action(base_probability, action_type, amount, root_cause_label, root_cause_probability)
    cost = INTERVENTION_COST_INR[action_type]
    friction = friction_cost(action_type, prior_contact_count)
    expected_value = probability * amount - cost - friction
    return ActionEV(action_type, probability, cost, friction, expected_value)


def rank_actions(
    base_probability: float,
    amount: float,
    prior_contact_count: int = 0,
    is_disputed: bool = False,
    root_cause_label: str | None = None,
    root_cause_probability: float = 0.0,
) -> list[ActionEV]:
    """Highest EV first; ties broken toward the cheaper action.
    root_cause_label/root_cause_probability are context ONLY (see
    action_uplift's docstring) -- they nudge each candidate's uplift before
    ranking, never bypass the ranking itself."""
    candidates = generate_candidate_actions(is_disputed)
    evs = [
        compute_action_ev(base_probability, amount, action_type, prior_contact_count, root_cause_label, root_cause_probability)
        for action_type in candidates
    ]
    return sorted(evs, key=lambda ev: (-ev.expected_value, ev.cost))


def materiality_threshold(amount: float) -> float:
    return max(MATERIALITY_FLOOR_INR, MATERIALITY_FRACTION_OF_AMOUNT * amount)


def recommend_action(
    base_probability: float,
    amount: float,
    prior_contact_count: int = 0,
    is_disputed: bool = False,
    root_cause_label: str | None = None,
    root_cause_probability: float = 0.0,
) -> ActionEV:
    """Top of the raw EV ranking, unless its edge over WAIT doesn't clear
    materiality_threshold(amount) -- see config.py's MATERIALITY_* constants
    for why. rank_actions() itself stays pure/raw-EV-sorted (used as-is for
    the explainability screen); this abstention rule only applies here."""
    ranked = rank_actions(base_probability, amount, prior_contact_count, is_disputed, root_cause_label, root_cause_probability)
    top = ranked[0]
    if top.action_type == ActionType.WAIT:
        return top

    wait_ev = next(ev for ev in ranked if ev.action_type == ActionType.WAIT)
    if top.expected_value - wait_ev.expected_value < materiality_threshold(amount):
        return wait_ev
    return top
