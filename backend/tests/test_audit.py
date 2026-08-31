"""Subtask 9 checkpoint: the full audit trail, persisted for real.

Every assertion here queries a FRESH session against the DB, never the
in-memory state run_invoice() returned -- proving "reconstruct the journey
without terminal logs" literally, not just that the returned dict looked
right. Each test uses its own dedicated invoice (distinct offset) and a
unique occurred_at timestamp so its DecisionLog row is unambiguously
identifiable among any other rows that invoice might have.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.core.db import SessionLocal
from app.models import AccountState, DecisionLog, Invoice
from app.models.enums import AccountCurrentState, InvoiceStatus


def _pick_live_invoice(offset: int):
    session = SessionLocal()
    try:
        return session.execute(
            select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).offset(offset).limit(1)
        ).scalar_one()
    finally:
        session.close()


def _pick_undisputed_live_invoice(offset: int):
    """PROMISE_CREATED on a disputed invoice correctly lands in
    DISPUTE_REVIEW, not PROMISE (dispute priority, see test_state_machine.py)
    -- excluded here since this test exercises the clean, undisputed path."""
    session = SessionLocal()
    try:
        return session.execute(
            select(Invoice.id)
            .where(Invoice.status == InvoiceStatus.OPEN)
            .where(Invoice.true_root_cause != "dispute")
            .offset(offset)
            .limit(1)
        ).scalar_one()
    finally:
        session.close()


def _fetch_decision_log(invoice_id, timestamp: datetime) -> DecisionLog:
    """decision_logs is deliberately append-only with no dedup (see
    app/agent/DECISIONS.md's Idempotency entry) -- rerunning the full test
    suite against the same persistent dev DB inserts another
    content-identical row for the same (invoice_id, timestamp) key every
    time. Fetches the most recently inserted matching row; which one is
    returned doesn't affect these tests' assertions, since the pipeline is
    deterministic and produces the same content on every rerun -- this
    just needs to tolerate >1 matching row instead of crashing on it."""
    session = SessionLocal()
    try:
        rows = session.execute(
            select(DecisionLog).where(DecisionLog.invoice_id == invoice_id, DecisionLog.timestamp == timestamp)
        ).scalars().all()
        return rows[-1]
    finally:
        session.close()


def _fetch_account_state(invoice_id) -> AccountState:
    session = SessionLocal()
    try:
        return session.get(AccountState, invoice_id)
    finally:
        session.close()


# -- shape 1: normal pipeline -------------------------------------------------


def test_normal_pipeline_reconstructs_fully_from_the_database(db_session):
    invoice_id = _pick_live_invoice(offset=200)
    as_of = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=as_of)

    in_memory = run_invoice(invoice_id, event=event, persist=True)

    log = _fetch_decision_log(invoice_id, as_of)
    account_state = _fetch_account_state(invoice_id)

    # model scores
    assert log.model_scores["recovery_probability"] == in_memory["recovery_probability"]
    assert len(log.model_scores["candidate_actions"]) == len(in_memory["economics_ranking"])

    # evidence: trigger event + retrieved cases
    assert log.evidence["trigger_event"]["event_type"] == "invoice.overdue"
    assert len(log.evidence["retrieved_cases"]) == len(in_memory["retrieved_cases"])

    # policy checks + final action
    assert log.policy_checks["is_disputed"] == in_memory["is_disputed"]
    assert log.policy_checks["policy_result"] == in_memory["policy_verdict"].result.value
    assert log.policy_checks["selected_action"] == in_memory["selected_action"].value
    assert log.policy_checks["tool_result"] == in_memory["tool_result"]
    assert log.decision == in_memory["selected_action"].value
    assert log.reason == in_memory["policy_verdict"].reason

    # account_state actually updated to match
    assert account_state.current_state == in_memory["next_state"]
    assert account_state.recoverability_score == in_memory["recovery_probability"]


def test_persist_defaults_to_off_so_normal_tests_stay_non_destructive():
    invoice_id = _pick_live_invoice(offset=201)
    as_of = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)
    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=as_of)

    run_invoice(invoice_id, event=event)  # persist defaults to False

    session = SessionLocal()
    try:
        row = session.execute(
            select(DecisionLog).where(DecisionLog.invoice_id == invoice_id, DecisionLog.timestamp == as_of)
        ).scalars().first()
    finally:
        session.close()
    assert row is None


# -- shape 2: promise-creation -------------------------------------------------


def test_promise_creation_shape_persists_ptp_score_and_promise_state(db_session):
    invoice_id = _pick_undisputed_live_invoice(offset=202)
    as_of = datetime(2026, 8, 27, 17, 0, tzinfo=timezone.utc)
    event = Event(
        event_type=EventType.PROMISE_CREATED,
        invoice_id=invoice_id,
        occurred_at=as_of,
        payload={"promised_amount": 40000.0, "promised_date": "2026-09-02", "source": "whatsapp"},
    )

    in_memory = run_invoice(invoice_id, event=event, persist=True)

    log = _fetch_decision_log(invoice_id, as_of)
    account_state = _fetch_account_state(invoice_id)

    assert log.model_scores["ptp_probability"] == in_memory["ptp_probability"]
    assert log.model_scores["recovery_probability"] is None
    assert "candidate_actions" not in log.model_scores or log.model_scores.get("candidate_actions") is None
    assert "selected_action" not in log.policy_checks
    assert log.decision == "promise"

    assert account_state.current_state == AccountCurrentState.PROMISE
    assert account_state.promise_score == in_memory["ptp_probability"]


# -- shape 3: invalid event ----------------------------------------------------


def test_invalid_event_shape_writes_decision_log_but_leaves_account_state_alone(db_session):
    invoice_id = _pick_live_invoice(offset=203)
    as_of = datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)
    wrong_invoice_id = uuid4()
    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=wrong_invoice_id, occurred_at=as_of)

    before = _fetch_account_state(invoice_id)
    before_state, before_updated_at = before.current_state, before.updated_at

    run_invoice(invoice_id, event=event, persist=True)

    log = _fetch_decision_log(invoice_id, as_of)
    after = _fetch_account_state(invoice_id)

    # the rejection is durably recorded -- the entire point of Subtask 6's
    # routing decision to send invalid events to AUDIT instead of crashing
    assert log.decision == "rejected"
    assert "invalid event" in log.reason
    assert log.policy_checks["error"] == log.reason

    # account_state is untouched, not fabricated
    assert after.current_state == before_state
    assert after.updated_at == before_updated_at
