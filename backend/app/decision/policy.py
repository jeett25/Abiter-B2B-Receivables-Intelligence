from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models.enums import ActionType, PolicyResult

MAX_CONTACT_ATTEMPTS = 5
COOLDOWN_DAYS = 3

# Gates WAIT -> STOP: is even passive monitoring worth continued attention?
# Independent of Economics Engine's MATERIALITY_FLOOR_INR (WAIT -> an action)
# only because this rule is itself gated on proposed_action == WAIT -- see
# the note at MATERIALITY_FLOOR_INR in app/decision/config.py.
MIN_PURSUIT_VALUE_INR = 2000.0

HUMAN_APPROVAL_AMOUNT_THRESHOLD = 200_000.0

# India-focused B2B product -- business hours defined in IST, Mon-Sat.
IST = timezone(timedelta(hours=5, minutes=30))
BUSINESS_HOURS_START = 9
BUSINESS_HOURS_END = 19

CONTACT_ACTIONS = {
    ActionType.EMAIL,
    ActionType.WHATSAPP,
    ActionType.PAYMENT_LINK,
    ActionType.VOICE,
    ActionType.ESCALATE,
}
# Mirrors economics.DISPUTE_EXCLUDED_ACTIONS -- kept as its own constant here
# since this module must not import from economics.py to check it (Policy
# Gate is a backstop that must work even if Economics Engine's own exclusion
# were ever removed or buggy).
DISPUTE_BLOCKED_ACTIONS = {ActionType.ESCALATE, ActionType.VOICE}
BUSINESS_HOURS_ACTIONS = {ActionType.VOICE, ActionType.ESCALATE}


@dataclass(frozen=True)
class PolicyContext:
    proposed_action: ActionType
    base_probability: float  # same P(recovery) Economics Engine used, unconditional on action
    amount: float
    is_actually_paid: bool
    is_disputed: bool
    prior_contact_count: int
    days_since_last_contact: int | None
    now: datetime


@dataclass(frozen=True)
class PolicyVerdict:
    result: PolicyResult
    final_action: ActionType
    reason: str


def detect_dispute(true_root_cause: str | None) -> bool:
    """Synthetic stand-in for a live "disputed" flag from a real context
    aggregator -- same convention already agreed for Economics Engine's
    is_disputed parameter (see app/decision/economics.py's module docstring).

    Why this is a different category of read than customers.archetype/
    true_recovery_probability/true_promise_keep_probability (all explicitly
    hidden-from-ML-models ground truth, per CLAUDE.md) or account_state's
    seed-time recoverability_score/promise_score (noisy copies of that same
    hidden ground truth): the test that matters is whether the field has a
    real-world analogue a production system could legitimately observe, not
    whether its name starts with true_. archetype has no real-world
    analogue at all -- no production system has a literal "archetype" field.
    true_recovery_probability/true_promise_keep_probability (and the
    account_state placeholders derived from them) ARE the target variables
    the ML models predict -- reading them bypasses the modeling exercise
    entirely. true_root_cause == "dispute" is different: a customer
    disputing an invoice is an observable business fact (a support ticket,
    a complaint email, a human ops note) a real system would eventually
    learn, even though this project didn't build the NLP/classification
    step to detect it from raw text -- and it is not the answer to "will
    this invoice recover" (a disputed invoice can still eventually pay or
    not), just context about the situation.

    Honest caveat, not hidden: this skips the detection LATENCY and
    imperfect ACCURACY a real dispute-flagging mechanism would have (a
    support ticket takes time to triage; a classifier has false negatives).
    Reading true_root_cause gives instant, noise-free certainty a real
    system wouldn't have -- an accepted simplification of fidelity for the
    one-week build, not a leak of a prediction target.
    """
    return true_root_cause == "dispute"


def detect_already_paid(invoice_amount: float, completed_payment_total: float) -> bool:
    """Cross-references actual payments, not invoices.status -- the
    already_paid_false_alarm archetype exists specifically to test that this
    checks the ledger directly rather than trusting a stale status field."""
    return completed_payment_total >= invoice_amount


def is_business_hours(now: datetime) -> bool:
    local = now.astimezone(IST)
    if local.weekday() == 6:  # Sunday
        return False
    return BUSINESS_HOURS_START <= local.hour < BUSINESS_HOURS_END


def evaluate_policy(context: PolicyContext) -> PolicyVerdict:
    if context.is_actually_paid:
        return PolicyVerdict(PolicyResult.BLOCKED, ActionType.STOP, "already paid -- ledger not yet reconciled")

    if context.is_disputed and context.proposed_action in DISPUTE_BLOCKED_ACTIONS:
        return PolicyVerdict(
            PolicyResult.BLOCKED, ActionType.WAIT, "disputed invoice -- collections pressure blocked pending resolution"
        )

    if (
        context.proposed_action == ActionType.WAIT
        and not context.is_disputed
        and context.base_probability * context.amount < MIN_PURSUIT_VALUE_INR
    ):
        return PolicyVerdict(
            PolicyResult.BLOCKED, ActionType.STOP, "expected recovery value too small to justify continued tracking"
        )

    if context.prior_contact_count >= MAX_CONTACT_ATTEMPTS and context.proposed_action in CONTACT_ACTIONS:
        return PolicyVerdict(PolicyResult.BLOCKED, ActionType.STOP, f"max contact attempts ({MAX_CONTACT_ATTEMPTS}) reached")

    if (
        context.days_since_last_contact is not None
        and context.days_since_last_contact < COOLDOWN_DAYS
        and context.proposed_action in CONTACT_ACTIONS
    ):
        return PolicyVerdict(
            PolicyResult.BLOCKED,
            ActionType.WAIT,
            f"cooldown active -- contacted {context.days_since_last_contact}d ago, minimum {COOLDOWN_DAYS}d",
        )

    if context.proposed_action in BUSINESS_HOURS_ACTIONS and not is_business_hours(context.now):
        return PolicyVerdict(PolicyResult.BLOCKED, ActionType.WAIT, "outside business hours for this channel")

    if context.amount >= HUMAN_APPROVAL_AMOUNT_THRESHOLD and context.proposed_action == ActionType.ESCALATE:
        return PolicyVerdict(
            PolicyResult.ESCALATED,
            context.proposed_action,
            f"amount >= Rs.{HUMAN_APPROVAL_AMOUNT_THRESHOLD:,.0f} -- requires human approval before escalation",
        )

    return PolicyVerdict(PolicyResult.ALLOWED, context.proposed_action, "no policy constraints triggered")
