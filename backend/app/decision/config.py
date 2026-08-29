from app.models.enums import ActionType

INTERVENTION_COST_INR: dict[ActionType, float] = {
    ActionType.WAIT: 0.0,
    ActionType.EMAIL: 5.0,
    ActionType.WHATSAPP: 10.0,
    ActionType.PAYMENT_LINK: 2.0,
    ActionType.VOICE: 200.0,
    ActionType.ESCALATE: 650.0,
    ActionType.STOP: 0.0,
}

ACTION_UPLIFT: dict[ActionType, float] = {
    ActionType.WAIT: 0.0,
    ActionType.STOP: 0.0,
    ActionType.EMAIL: 0.03,
    ActionType.WHATSAPP: 0.075,
    ActionType.PAYMENT_LINK: 0.06,
    ActionType.VOICE: 0.10,
    ActionType.ESCALATE: 0.14,
}

FRICTION_BASE_INR: dict[ActionType, float] = {
    ActionType.WAIT: 0.0,
    ActionType.EMAIL: 2.0,
    ActionType.WHATSAPP: 4.0,
    ActionType.PAYMENT_LINK: 2.0,
    ActionType.VOICE: 20.0,
    ActionType.ESCALATE: 80.0,
    ActionType.STOP: 0.0,
}

FRICTION_GROWTH_PER_PRIOR_CONTACT = 0.5


MATERIALITY_FLOOR_INR = 50.0
MATERIALITY_FRACTION_OF_AMOUNT = 0.01
