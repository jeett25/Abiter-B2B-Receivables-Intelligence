"""Ground-truth behavior parameters for the 8 synthetic customer archetypes.

Every probability/effect here is deliberately fabricated ground truth for the
synthetic dataset -- it is what the Day-2 ML models are graded against, never
something a real system would know in advance. See the Day-1 plan for the
reasoning behind each number.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import ActionType

ACTIONABLE_TYPES = [
    ActionType.EMAIL,
    ActionType.WHATSAPP,
    ActionType.PAYMENT_LINK,
    ActionType.VOICE,
    ActionType.ESCALATE,
]

# Flat rate applied to ALL invoices regardless of archetype.
DISPUTE_RATE = 0.06

# Generation-time intervention costs (INR). A tuple means "sample uniformly in this range".
INTERVENTION_COSTS: dict[ActionType, float | tuple[float, float]] = {
    ActionType.WAIT: 0.0,
    ActionType.EMAIL: 5.0,
    ActionType.WHATSAPP: 10.0,
    ActionType.PAYMENT_LINK: 0.0,
    ActionType.VOICE: (150.0, 300.0),
    ActionType.ESCALATE: (500.0, 800.0),
    ActionType.STOP: 0.0,
}

AMOUNT_MIN = 5_000.0
AMOUNT_MAX = 500_000.0

WRITTEN_OFF_DAYS_RANGE = (150, 180)


@dataclass(frozen=True)
class ActionEffect:
    recovery_uplift: float
    delay_reduction_days: int


@dataclass(frozen=True)
class Archetype:
    name: str
    population_share: float
    organic_recovery_probability: float
    promise_keep_probability: float
    delay_days_range: tuple[int, int]
    amount_lognormal_mean: float
    amount_lognormal_sigma: float
    root_cause_weights: dict[str, float]  # {"cash_flow_stress": x, "oversight": y} -- dispute handled globally
    action_effects: dict[ActionType, ActionEffect]


ARCHETYPES: dict[str, Archetype] = {
    "reliable_payer": Archetype(
        name="reliable_payer",
        population_share=0.20,
        organic_recovery_probability=0.95,
        promise_keep_probability=0.95,
        delay_days_range=(2, 5),
        amount_lognormal_mean=9.90,
        amount_lognormal_sigma=0.5,
        root_cause_weights={"cash_flow_stress": 0.15, "oversight": 0.85},
        action_effects={
            ActionType.EMAIL: ActionEffect(0.01, 1),
            ActionType.WHATSAPP: ActionEffect(0.01, 1),
            ActionType.PAYMENT_LINK: ActionEffect(0.02, 2),
            ActionType.VOICE: ActionEffect(0.01, 1),
            ActionType.ESCALATE: ActionEffect(0.00, 0),
        },
    ),
    "slightly_late": Archetype(
        name="slightly_late",
        population_share=0.20,
        organic_recovery_probability=0.85,
        promise_keep_probability=0.80,
        delay_days_range=(10, 20),
        amount_lognormal_mean=9.90,
        amount_lognormal_sigma=0.5,
        root_cause_weights={"cash_flow_stress": 0.25, "oversight": 0.75},
        action_effects={
            ActionType.EMAIL: ActionEffect(0.05, 3),
            ActionType.WHATSAPP: ActionEffect(0.07, 4),
            ActionType.PAYMENT_LINK: ActionEffect(0.08, 5),
            ActionType.VOICE: ActionEffect(0.05, 3),
            ActionType.ESCALATE: ActionEffect(0.03, 2),
        },
    ),
    "chronic_late": Archetype(
        name="chronic_late",
        population_share=0.15,
        organic_recovery_probability=0.55,
        promise_keep_probability=0.45,
        delay_days_range=(40, 70),
        amount_lognormal_mean=10.30,
        amount_lognormal_sigma=0.6,
        root_cause_weights={"cash_flow_stress": 0.65, "oversight": 0.35},
        action_effects={
            ActionType.EMAIL: ActionEffect(0.05, 3),
            ActionType.WHATSAPP: ActionEffect(0.08, 5),
            ActionType.PAYMENT_LINK: ActionEffect(0.10, 7),
            ActionType.VOICE: ActionEffect(0.15, 10),
            ActionType.ESCALATE: ActionEffect(0.18, 14),
        },
    ),
    "promise_keeper": Archetype(
        name="promise_keeper",
        population_share=0.10,
        organic_recovery_probability=0.60,
        promise_keep_probability=0.90,
        delay_days_range=(15, 40),
        amount_lognormal_mean=10.30,
        amount_lognormal_sigma=0.6,
        root_cause_weights={"cash_flow_stress": 0.50, "oversight": 0.50},
        action_effects={
            ActionType.EMAIL: ActionEffect(0.05, 3),
            ActionType.WHATSAPP: ActionEffect(0.15, 7),
            ActionType.PAYMENT_LINK: ActionEffect(0.10, 5),
            ActionType.VOICE: ActionEffect(0.20, 10),
            ActionType.ESCALATE: ActionEffect(0.10, 5),
        },
    ),
    "promise_breaker": Archetype(
        name="promise_breaker",
        population_share=0.10,
        organic_recovery_probability=0.50,
        promise_keep_probability=0.20,
        delay_days_range=(20, 50),
        amount_lognormal_mean=10.30,
        amount_lognormal_sigma=0.6,
        root_cause_weights={"cash_flow_stress": 0.70, "oversight": 0.30},
        action_effects={
            ActionType.EMAIL: ActionEffect(0.02, 1),
            ActionType.WHATSAPP: ActionEffect(0.03, 2),
            ActionType.PAYMENT_LINK: ActionEffect(0.04, 2),
            ActionType.VOICE: ActionEffect(0.05, 2),
            ActionType.ESCALATE: ActionEffect(0.08, 4),
        },
    ),
    "strategic_enterprise": Archetype(
        name="strategic_enterprise",
        population_share=0.10,
        organic_recovery_probability=0.90,
        promise_keep_probability=0.75,
        delay_days_range=(60, 90),
        amount_lognormal_mean=12.20,
        amount_lognormal_sigma=0.5,
        root_cause_weights={"cash_flow_stress": 0.40, "oversight": 0.60},
        action_effects={
            ActionType.EMAIL: ActionEffect(0.01, 1),
            ActionType.WHATSAPP: ActionEffect(0.01, 1),
            ActionType.PAYMENT_LINK: ActionEffect(0.02, 2),
            ActionType.VOICE: ActionEffect(0.02, 2),
            ActionType.ESCALATE: ActionEffect(0.00, 0),
        },
    ),
    "cash_constrained": Archetype(
        name="cash_constrained",
        population_share=0.10,
        organic_recovery_probability=0.45,
        promise_keep_probability=0.55,
        delay_days_range=(30, 90),
        amount_lognormal_mean=9.60,
        amount_lognormal_sigma=0.6,
        root_cause_weights={"cash_flow_stress": 0.90, "oversight": 0.10},
        action_effects={
            ActionType.EMAIL: ActionEffect(0.02, 2),
            ActionType.WHATSAPP: ActionEffect(0.03, 3),
            ActionType.PAYMENT_LINK: ActionEffect(0.12, 10),
            ActionType.VOICE: ActionEffect(0.05, 4),
            ActionType.ESCALATE: ActionEffect(0.02, 1),
        },
    ),
    "already_paid_false_alarm": Archetype(
        name="already_paid_false_alarm",
        population_share=0.05,
        organic_recovery_probability=1.0,
        promise_keep_probability=0.0,  # not meaningful for this archetype
        delay_days_range=(0, 0),
        amount_lognormal_mean=10.30,
        amount_lognormal_sigma=0.5,
        root_cause_weights={"cash_flow_stress": 0.10, "oversight": 0.90},
        action_effects={a: ActionEffect(0.0, 0) for a in ACTIONABLE_TYPES},
    ),
}

assert abs(sum(a.population_share for a in ARCHETYPES.values()) - 1.0) < 1e-9
