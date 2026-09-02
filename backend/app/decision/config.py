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

# Day-5 correction (app/attribution/'s randomized-holdout experiment):
# ESCALATE's flat +14% uplift assumption was not supported for large
# invoices -- ~73% of ESCALATE decisions in the experiment went to
# strategic_enterprise-shaped invoices with a true (hidden ground truth)
# ESCALATE uplift of exactly 0.00. amount is used as an OBSERVABLE proxy
# for that archetype (a real system can condition on amount, never on
# archetype) -- checked against real amount-by-archetype distributions,
# not assumed clean; see app/decision/DECISIONS.md for the full evidence
# chain, the threshold derivation, and the known limitation (the proxy has
# genuine tail overlap, so this will misclassify a minority of invoices in
# both directions).
ESCALATE_LARGE_AMOUNT_THRESHOLD_INR = 100_000.0
ESCALATE_LARGE_AMOUNT_UPLIFT = 0.02

# Root-cause-conditioned uplift nudge (app/ml/train_root_cause.py's
# cash_flow_stress-vs-oversight classifier, non-disputed invoices only).
# Deliberately small and additive, and only applied when the model's own
# confidence clears ROOT_CAUSE_CONFIDENCE_THRESHOLD -- this is context for
# Economics, not an action selector: it's sized to tip a genuinely close EV
# comparison, never large enough on its own to make a clearly-dominated
# action win. Economics + the Policy Gate remain the sole decision
# authority; root cause only perturbs one input to Economics.
ROOT_CAUSE_CONFIDENCE_THRESHOLD = 0.6

ROOT_CAUSE_UPLIFT_ADJUSTMENT: dict[str, dict[ActionType, float]] = {
    "cash_flow_stress": {
        ActionType.PAYMENT_LINK: 0.03,  # can't pay without friction removed -- favor a direct payment link
    },
    "oversight": {
        ActionType.EMAIL: 0.02,  # just forgot -- a cheap reminder is probably enough
        ActionType.WHATSAPP: 0.02,
    },
}
