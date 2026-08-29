"""app/decision/persist.py tests: pure builders, plus an end-to-end
decision-trace proof against the real DB."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import engine
from app.decision.economics import ActionEV
from app.decision.persist import (
    NO_ACTIVE_PROMISE_SCORE,
    _resolve_account_state,
    build_account_state_updates,
    build_decision_log,
    persist_decision,
)
from app.decision.policy import PolicyVerdict
from app.decision.service import Decision, decide
from app.models import AccountState, Customer, DecisionLog, Invoice
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus, PolicyResult

FAKE_AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _decision(**overrides) -> Decision:
    defaults = dict(
        invoice_id="inv-fake",
        base_probability=0.4,
        amount=20_000.0,
        is_disputed=False,
        is_actually_paid=False,
        economics_ranking=[
            ActionEV(ActionType.ESCALATE, 0.5, 650.0, 80.0, 9270.0),
            ActionEV(ActionType.WAIT, 0.4, 0.0, 0.0, 8000.0),
        ],
        proposed_action=ActionType.ESCALATE,
        retrieved_cases=[],
        policy_verdict=PolicyVerdict(PolicyResult.ALLOWED, ActionType.ESCALATE, "no policy constraints triggered"),
        final_action=ActionType.ESCALATE,
    )
    defaults.update(overrides)
    return Decision(**defaults)


# -- build_account_state_updates ------------------------------------------


def test_revenue_at_risk_is_amount_times_one_minus_probability():
    decision = _decision(base_probability=0.3, amount=10_000.0)
    updates = build_account_state_updates(decision)
    assert updates["revenue_at_risk"] == 10_000.0 * 0.7


def test_promise_score_is_the_documented_sentinel_not_a_prediction():
    updates = build_account_state_updates(_decision())
    assert updates["promise_score"] == NO_ACTIVE_PROMISE_SCORE


def test_expected_payment_date_is_null_not_fabricated():
    updates = build_account_state_updates(_decision())
    assert updates["expected_payment_date"] is None


def test_next_action_matches_final_action():
    decision = _decision(final_action=ActionType.WHATSAPP)
    updates = build_account_state_updates(decision)
    assert updates["next_action"] == ActionType.WHATSAPP


# -- account state resolution: the CLOSED split ----------------------------


def test_stop_already_paid_maps_to_closed_paid():
    decision = _decision(final_action=ActionType.STOP, is_actually_paid=True)
    assert _resolve_account_state(decision) == AccountCurrentState.CLOSED_PAID


def test_stop_not_paid_maps_to_closed_abandoned():
    decision = _decision(final_action=ActionType.STOP, is_actually_paid=False)
    assert _resolve_account_state(decision) == AccountCurrentState.CLOSED_ABANDONED


def test_wait_maps_to_wait_state():
    assert _resolve_account_state(_decision(final_action=ActionType.WAIT)) == AccountCurrentState.WAIT


def test_contact_actions_map_to_remind_state():
    for action in [ActionType.EMAIL, ActionType.WHATSAPP, ActionType.PAYMENT_LINK, ActionType.VOICE]:
        assert _resolve_account_state(_decision(final_action=action)) == AccountCurrentState.REMIND


def test_escalate_maps_to_escalate_state():
    assert _resolve_account_state(_decision(final_action=ActionType.ESCALATE)) == AccountCurrentState.ESCALATE


# -- build_decision_log -----------------------------------------------------


def test_decision_log_captures_full_candidate_ranking_and_policy_trace():
    decision = _decision()
    log = build_decision_log(decision, FAKE_AS_OF)

    assert log.decision == "escalate"
    assert log.model_scores["recovery_probability"] == 0.4
    assert len(log.model_scores["candidate_actions"]) == 2
    assert log.policy_checks["proposed_action"] == "escalate"
    assert log.policy_checks["final_action"] == "escalate"
    assert log.policy_checks["result"] == "allowed"
    assert log.reason == "no policy constraints triggered"
    assert log.timestamp == FAKE_AS_OF


# -- end-to-end decision trace, against the real DB -------------------------


def test_already_paid_false_alarm_decision_trace_is_reconstructible_from_db(db_session):
    """The concrete "decision trace verified" proof: decide() -> persist ->
    read back from decision_logs/account_state, and confirm the persisted
    trace actually explains what happened -- not just that the tables got
    some row written to them."""
    live_invoice_id = db_session.execute(
        select(Invoice.id)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Customer.archetype == "already_paid_false_alarm")
        .where(Invoice.status == InvoiceStatus.OPEN)
        .limit(1)
    ).scalar_one()

    decision = decide(live_invoice_id, engine=engine)
    persist_decision(decision, FAKE_AS_OF, session=db_session)
    db_session.commit()

    log = (
        db_session.execute(
            select(DecisionLog)
            .where(DecisionLog.invoice_id == live_invoice_id)
            .order_by(DecisionLog.timestamp.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    assert log is not None
    assert log.decision == "stop"
    assert log.policy_checks["result"] == "blocked"
    assert log.policy_checks["is_actually_paid"] is True
    assert "already paid" in log.reason

    account_state = db_session.get(AccountState, live_invoice_id)
    assert account_state.current_state == AccountCurrentState.CLOSED_PAID
    assert account_state.next_action == ActionType.STOP
    assert account_state.recoverability_score == decision.base_probability
    assert account_state.promise_score == NO_ACTIVE_PROMISE_SCORE
    assert account_state.expected_payment_date is None
