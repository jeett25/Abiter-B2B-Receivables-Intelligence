"""Day 3 subtask 9: the six curated demo scenarios (synthetic/demo_fixtures.json,
pinned on Day 1) actually run through the real Decision Service and produce
sensible decisions.

Day 1's expected_action labels predate Economics Engine/Policy Gate/Decision
Service entirely -- some (reassess, act, stop_suppress) aren't literal
ActionType values, since they were written anticipating the FULL eventual
system (including Day 4's state machine and promise-broken reassessment),
not just Day 3's slice of it. Each scenario below states explicitly what a
Day-3-correct outcome looks like and why, rather than asserting literal
string equality against a label that predates this layer.
"""
import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import engine
from app.decision.service import decide
from app.models import Invoice
from app.models.enums import ActionType, PolicyResult

FIXTURES_PATH = Path(__file__).parent.parent / "synthetic" / "demo_fixtures.json"
ACTIVE_INTERVENTIONS = {ActionType.EMAIL, ActionType.WHATSAPP, ActionType.PAYMENT_LINK, ActionType.VOICE, ActionType.ESCALATE}


def _load_fixtures() -> dict:
    return json.loads(FIXTURES_PATH.read_text())


def _decide_by_invoice_number(db_session, invoice_number: str):
    invoice_id = db_session.execute(
        select(Invoice.id).where(Invoice.invoice_number == invoice_number)
    ).scalar_one()
    return decide(invoice_id, engine=engine)


def test_reliable_payer_scenario_waits(db_session):
    fixtures = _load_fixtures()
    decision = _decide_by_invoice_number(db_session, fixtures["reliable_payer_wait"]["invoice_number"])
    assert decision.final_action == ActionType.WAIT


def test_chronic_late_scenario_now_gets_voice_not_escalate(db_session):
    """Was ESCALATE at Day-3 time. Reframed after Day 5, subtask 6's
    ESCALATE amount-threshold fix (see app/decision/DECISIONS.md): this
    fixture is Rs.118,361, above ESCALATE_LARGE_AMOUNT_THRESHOLD_INR
    (Rs.100,000), so its uplift is now correctly reduced and VOICE wins
    instead -- direct, concrete proof of the Day-5 correction, not a
    regression. See synthetic/seed_demo.py's check_chronic_late_escalate."""
    fixtures = _load_fixtures()
    decision = _decide_by_invoice_number(db_session, fixtures["chronic_late_escalate"]["invoice_number"])
    assert decision.final_action == ActionType.VOICE


def test_promise_breaker_scenario_gets_an_initial_action_not_reassess(db_session):
    """Day 1's 'reassess' label refers to a POST-promise-broken account state
    Day 4's orchestration will produce once a promise exists and breaks.
    This live invoice is a blank slate (no promise yet, confirmed in
    subtask 5) -- Day 3's Decision Service can only ever produce a first-ever
    action (never AccountCurrentState.REASSESS, which isn't even a valid
    ActionType), so the Day-3-correct outcome here is any real ActionType,
    not a literal match to the Day-1 label."""
    fixtures = _load_fixtures()
    decision = _decide_by_invoice_number(db_session, fixtures["promise_breaker_reassess"]["invoice_number"])
    assert isinstance(decision.final_action, ActionType)


def test_low_value_scenario_gets_a_cheap_nudge_not_a_blind_stop(db_session):
    """This fixture was selected on Day 1 purely by smallest amount among
    three archetypes, blind to the model's actual predicted probability --
    "small amount -> not worth chasing" as a blunt heuristic. Checked
    directly: INV-10040 is exactly AMOUNT_MIN (Rs.5,000), cash_constrained,
    predicted probability 0.50 (not particularly low). EV(WAIT) = 0.5*5000 =
    Rs.2,500, just above MIN_PURSUIT_VALUE_INR (Rs.2,000), so the low-value
    STOP-conversion rule correctly does not fire -- WHATSAPP (cost Rs.14)
    raises expected recovery to Rs.2,673, a genuine +Rs.159 net gain, not a
    wasteful action. Retuning MIN_PURSUIT_VALUE_INR to force this one pinned
    case to STOP would be curve-fitting the config to a label written before
    the real economics existed, not a defensible fix -- so the Day-3-correct
    outcome here is a cheap active nudge, not a blind stop."""
    fixtures = _load_fixtures()
    decision = _decide_by_invoice_number(db_session, fixtures["low_value_stop"]["invoice_number"])
    assert decision.final_action in ACTIVE_INTERVENTIONS
    assert decision.policy_verdict.result == PolicyResult.ALLOWED


def test_high_value_scenario_takes_an_active_intervention(db_session):
    """Day 1's 'act' label is shorthand for "some active intervention", not
    a specific ActionType -- any of the five real actionable types satisfies it."""
    fixtures = _load_fixtures()
    decision = _decide_by_invoice_number(db_session, fixtures["high_value_act"]["invoice_number"])
    assert decision.final_action in ACTIVE_INTERVENTIONS


def test_already_paid_scenario_stops_and_suppresses(db_session):
    fixtures = _load_fixtures()
    decision = _decide_by_invoice_number(db_session, fixtures["already_paid_suppress"]["invoice_number"])
    assert decision.final_action == ActionType.STOP
    assert decision.policy_verdict.result == PolicyResult.BLOCKED
    assert decision.is_actually_paid is True
    assert "already paid" in decision.policy_verdict.reason
