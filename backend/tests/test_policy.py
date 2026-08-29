"""app/decision/policy.py tests: pure, no DB required."""
from datetime import datetime

from app.decision.policy import (
    BUSINESS_HOURS_END,
    BUSINESS_HOURS_START,
    COOLDOWN_DAYS,
    HUMAN_APPROVAL_AMOUNT_THRESHOLD,
    IST,
    MAX_CONTACT_ATTEMPTS,
    MIN_PURSUIT_VALUE_INR,
    PolicyContext,
    detect_already_paid,
    detect_dispute,
    evaluate_policy,
    is_business_hours,
)
from app.models.enums import ActionType, PolicyResult

MONDAY_NOON_IST = datetime(2026, 8, 24, 12, 0, tzinfo=IST)
SUNDAY_NOON_IST = datetime(2026, 8, 23, 12, 0, tzinfo=IST)


def _context(**overrides) -> PolicyContext:
    defaults = dict(
        proposed_action=ActionType.EMAIL,
        base_probability=0.5,
        amount=50_000.0,
        is_actually_paid=False,
        is_disputed=False,
        prior_contact_count=0,
        days_since_last_contact=None,
        now=MONDAY_NOON_IST,
    )
    defaults.update(overrides)
    return PolicyContext(**defaults)


# -- pure helpers --------------------------------------------------------


def test_detect_dispute_only_true_for_dispute_root_cause():
    assert detect_dispute("dispute") is True
    assert detect_dispute("cash_flow_stress") is False
    assert detect_dispute(None) is False


def test_detect_already_paid_compares_completed_payment_total_to_amount():
    assert detect_already_paid(invoice_amount=10_000.0, completed_payment_total=10_000.0) is True
    assert detect_already_paid(invoice_amount=10_000.0, completed_payment_total=9_999.0) is False


def test_is_business_hours_true_on_weekday_within_window():
    assert is_business_hours(MONDAY_NOON_IST) is True


def test_is_business_hours_false_on_sunday():
    assert is_business_hours(SUNDAY_NOON_IST) is False


def test_is_business_hours_false_outside_window():
    late_night = MONDAY_NOON_IST.replace(hour=(BUSINESS_HOURS_END + 1) % 24)
    early_morning = MONDAY_NOON_IST.replace(hour=(BUSINESS_HOURS_START - 1) % 24)
    assert is_business_hours(late_night) is False
    assert is_business_hours(early_morning) is False


# -- rule 1: already paid -------------------------------------------------


def test_already_paid_blocks_and_forces_stop_regardless_of_everything_else():
    context = _context(
        is_actually_paid=True,
        is_disputed=True,
        proposed_action=ActionType.ESCALATE,
        prior_contact_count=99,
        amount=1_000_000.0,
    )
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.STOP


# -- rule 2: disputed + escalate/voice ------------------------------------


def test_disputed_escalate_blocked_by_policy_even_if_economics_should_have_excluded_it():
    # Economics Engine (app/decision/economics.py) already excludes
    # ESCALATE/VOICE from a disputed invoice's candidates, so this branch
    # should essentially never fire via the normal end-to-end path. Calling
    # evaluate_policy directly with a context Economics should never itself
    # produce is the only way to prove this backstop actually works, rather
    # than trusting an untested defense-in-depth rule.
    context = _context(is_disputed=True, proposed_action=ActionType.ESCALATE)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.WAIT


def test_disputed_voice_also_blocked():
    context = _context(is_disputed=True, proposed_action=ActionType.VOICE)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.WAIT


def test_disputed_email_not_blocked_by_dispute_rule():
    context = _context(is_disputed=True, proposed_action=ActionType.EMAIL, base_probability=0.9, amount=100_000.0)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ALLOWED


# -- rule 3: WAIT + low EV -> STOP, except when disputed ------------------


def test_wait_below_pursuit_floor_converts_to_stop():
    # base_probability * amount = 0.1 * 10_000 = 1_000 < MIN_PURSUIT_VALUE_INR
    context = _context(proposed_action=ActionType.WAIT, base_probability=0.1, amount=10_000.0)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.STOP


def test_wait_above_pursuit_floor_stays_allowed():
    context = _context(proposed_action=ActionType.WAIT, base_probability=0.9, amount=10_000.0)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ALLOWED
    assert verdict.final_action == ActionType.WAIT


def test_disputed_low_value_wait_is_exempt_from_stop_conversion():
    # The real product decision from planning: a disputed invoice needs
    # resolution regardless of size -- STOP would mean giving up on
    # investigating it, not just giving up on chasing payment.
    context = _context(
        proposed_action=ActionType.WAIT, is_disputed=True, base_probability=0.1, amount=10_000.0
    )
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ALLOWED
    assert verdict.final_action == ActionType.WAIT


# -- rule 4: max contact attempts ------------------------------------------


def test_max_contact_attempts_reached_blocks_and_stops():
    context = _context(proposed_action=ActionType.WHATSAPP, prior_contact_count=MAX_CONTACT_ATTEMPTS)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.STOP


def test_below_max_contact_attempts_not_blocked_by_this_rule():
    context = _context(proposed_action=ActionType.WHATSAPP, prior_contact_count=MAX_CONTACT_ATTEMPTS - 1)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ALLOWED


# -- rule 5: cooldown -------------------------------------------------------


def test_cooldown_active_blocks_contact_action():
    context = _context(proposed_action=ActionType.EMAIL, days_since_last_contact=COOLDOWN_DAYS - 1)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.WAIT


def test_cooldown_elapsed_not_blocked():
    context = _context(proposed_action=ActionType.EMAIL, days_since_last_contact=COOLDOWN_DAYS)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ALLOWED


# -- rule 6: business hours -------------------------------------------------


def test_voice_outside_business_hours_blocked():
    context = _context(proposed_action=ActionType.VOICE, now=SUNDAY_NOON_IST)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.WAIT


def test_email_outside_business_hours_not_blocked_by_this_rule():
    # Async channels aren't gated by business hours.
    context = _context(proposed_action=ActionType.EMAIL, now=SUNDAY_NOON_IST)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ALLOWED


# -- rule 7: human-approval threshold ---------------------------------------


def test_large_amount_escalate_requires_human_approval():
    context = _context(proposed_action=ActionType.ESCALATE, amount=HUMAN_APPROVAL_AMOUNT_THRESHOLD)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ESCALATED
    assert verdict.final_action == ActionType.ESCALATE


def test_large_amount_disputed_invoice_never_reaches_human_approval_rule():
    # Dispute-blocking (rule 2) fires first and converts to WAIT, so a large
    # disputed invoice never reaches the human-approval-threshold rule as an
    # ESCALATE action -- dispute-blocking takes priority by construction of
    # the ordering, not by accident.
    context = _context(proposed_action=ActionType.ESCALATE, is_disputed=True, amount=HUMAN_APPROVAL_AMOUNT_THRESHOLD)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.BLOCKED
    assert verdict.final_action == ActionType.WAIT


def test_small_amount_escalate_allowed_without_human_approval():
    context = _context(proposed_action=ActionType.ESCALATE, amount=HUMAN_APPROVAL_AMOUNT_THRESHOLD - 1)
    verdict = evaluate_policy(context)
    assert verdict.result == PolicyResult.ALLOWED


# -- default / no rules triggered -------------------------------------------


def test_ordinary_context_is_allowed():
    verdict = evaluate_policy(_context())
    assert verdict.result == PolicyResult.ALLOWED
    assert verdict.final_action == ActionType.EMAIL
