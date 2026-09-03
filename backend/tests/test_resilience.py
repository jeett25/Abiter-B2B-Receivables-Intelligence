"""Subtask 6 checkpoint: retry, fallback, invalid/duplicate events.

call_with_retry tests are pure (no DB). dispatch_action's fallback test is
pure too (monkeypatches app.agent.nodes' tool imports directly). The last
two tests are full-graph integration tests against the real dev DB: one is
the literal "break something on purpose" demo script for the video's
failure-handling moment, the other proves reprocessing the same event twice
stays safe (though not deduplicated -- see DECISIONS.md).
"""
import json
import uuid
from pathlib import Path

from sqlalchemy import select

from app.agent import nodes
from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.agent.resilience import MAX_TOOL_ATTEMPTS, call_with_retry
from app.decision.service import DEFAULT_AS_OF
from app.models import Invoice
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus

FIXTURES_PATH = Path(__file__).parent.parent / "synthetic" / "demo_fixtures.json"
FIXTURES = json.loads(FIXTURES_PATH.read_text())


# -- pure: call_with_retry ---------------------------------------------------


def test_call_with_retry_succeeds_on_first_attempt():
    calls = []

    def fn():
        calls.append(1)
        return {"success": True}

    result, attempts = call_with_retry(fn, is_success=lambda r: r["success"])
    assert attempts == 1
    assert len(calls) == 1


def test_call_with_retry_succeeds_on_second_attempt():
    calls = []

    def fn():
        calls.append(1)
        return {"success": len(calls) >= 2}

    result, attempts = call_with_retry(fn, is_success=lambda r: r["success"])
    assert attempts == 2
    assert result["success"] is True


def test_call_with_retry_exhausts_and_returns_last_failure():
    calls = []

    def fn():
        calls.append(1)
        return {"success": False}

    result, attempts = call_with_retry(fn, is_success=lambda r: r["success"], max_attempts=3)
    assert attempts == 3
    assert len(calls) == 3
    assert result["success"] is False


def test_call_with_retry_is_agnostic_to_result_shape():
    """Proves the generic contract: works on any object with a caller-
    defined notion of success, not just ToolResult dicts -- exactly what
    lets Subtask 7 reuse this for a differently-shaped LLM response without
    any change here."""

    class FakeLLMResponse:
        def __init__(self, ok):
            self.ok = ok

    result, attempts = call_with_retry(lambda: FakeLLMResponse(True), is_success=lambda r: r.ok)
    assert attempts == 1
    assert result.ok is True


# -- pure: dispatch_action's fallback (caller-owned, not call_with_retry's) --


def test_dispatch_action_falls_back_to_wait_after_exhausting_retries(monkeypatch):
    call_count = {"n": 0}

    def _always_fails(*, invoice_number, amount, now, failure_mode=False):
        call_count["n"] += 1
        return {
            "success": False,
            "action": "email",
            "external_id": None,
            "message": "simulated persistent failure",
            "timestamp": now.isoformat(),
        }

    monkeypatch.setattr(nodes, "execute_email", _always_fails)

    state = {
        "invoice_id": uuid.uuid4(),
        "selected_action": ActionType.EMAIL,
        "event": Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=None, occurred_at=DEFAULT_AS_OF),
        "features": {"invoice_number": "INV-77777", "amount": 20000.0},
    }
    result = nodes.dispatch_action(state)

    assert call_count["n"] == MAX_TOOL_ATTEMPTS
    assert result["selected_action"] == ActionType.WAIT
    assert result["retry_count"] == MAX_TOOL_ATTEMPTS - 1
    assert "failed after" in result["error"]
    assert result["tool_result"]["success"] is False


def test_dispatch_action_does_not_fall_back_if_a_retry_succeeds(monkeypatch):
    call_count = {"n": 0}

    def _fails_once_then_succeeds(*, invoice_number, amount, now, failure_mode=False):
        call_count["n"] += 1
        if call_count["n"] < 2:
            return {"success": False, "action": "whatsapp", "external_id": None, "message": "transient", "timestamp": now.isoformat()}
        return {"success": True, "action": "whatsapp", "external_id": "sim-x", "message": "sent", "timestamp": now.isoformat()}

    monkeypatch.setattr(nodes, "execute_whatsapp", _fails_once_then_succeeds)

    state = {
        "invoice_id": uuid.uuid4(),
        "selected_action": ActionType.WHATSAPP,
        "event": Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=None, occurred_at=DEFAULT_AS_OF),
        "features": {"invoice_number": "INV-77778", "amount": 20000.0},
    }
    result = nodes.dispatch_action(state)

    assert call_count["n"] == 2
    assert "selected_action" not in result  # no override -- the real action stands
    assert result["retry_count"] == 1
    assert result["tool_result"]["success"] is True


# -- invalid event routing ---------------------------------------------------


def test_invalid_event_routes_to_audit_without_running_the_pipeline():
    """No DB fixture needed -- LOAD_CONTEXT/BUILD_FEATURES (the DB-dependent
    nodes) never run for an invalid event, which is itself part of the
    point: this doesn't even touch the DB before recognizing the event as
    invalid."""
    invoice_id = uuid.uuid4()
    wrong_id = uuid.uuid4()
    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=wrong_id, occurred_at=DEFAULT_AS_OF)

    result = run_invoice(invoice_id, event=event)

    assert result["error"] is not None
    assert "invalid event" in result["error"]
    assert "recovery_probability" not in result
    assert "selected_action" not in result


# -- full-graph integration tests --------------------------------------------


def test_full_graph_survives_a_forced_tool_failure_and_falls_back_safely(monkeypatch, db_session):
    """The literal 'break something on purpose' demo moment. Uses the
    chronic_late_escalate demo fixture. Was ESCALATE at Day-3 time;
    reframed after Day 5 subtask 6's ESCALATE amount-threshold fix (see
    docs/decision-DECISIONS.md) -- INV-10184 (Rs.118,361) now correctly
    produces VOICE instead, so the forced failure targets execute_voice,
    not request_human_handoff. Still fully deterministic, still the same
    demo moment: economics wants an active intervention, the tool fails
    twice, the system falls back to WAIT rather than guessing a
    substitute channel."""
    invoice_number = FIXTURES["chronic_late_escalate"]["invoice_number"]
    invoice_id = db_session.execute(select(Invoice.id).where(Invoice.invoice_number == invoice_number)).scalar_one()

    def _forced_failure(*, invoice_number, amount, now, failure_mode=False):
        return {
            "success": False,
            "action": "voice",
            "external_id": None,
            "message": "[forced failure for demo]",
            "timestamp": now.isoformat(),
        }

    monkeypatch.setattr(nodes, "execute_voice", _forced_failure)

    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DEFAULT_AS_OF)
    result = run_invoice(invoice_id, event=event)

    assert result["proposed_action"] == ActionType.VOICE  # what economics originally wanted
    assert result["selected_action"] == ActionType.WAIT  # what actually happened after the forced failure
    assert result["next_state"] == AccountCurrentState.WAIT
    assert "voice failed after 2 attempt(s)" in result["error"]
    assert result["tool_result"]["success"] is False


def test_reprocessing_the_same_event_twice_is_safe_though_not_deduplicated(db_session):
    """No active dedup exists (see DECISIONS.md) -- this proves reprocessing
    stays operationally consistent rather than actively preventing it."""
    live_invoice_id = db_session.execute(
        select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).limit(1)
    ).scalar_one()
    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=live_invoice_id, occurred_at=DEFAULT_AS_OF)

    first = run_invoice(live_invoice_id, event=event)
    second = run_invoice(live_invoice_id, event=event)

    assert first["recovery_probability"] == second["recovery_probability"]
    assert first["next_state"] == second["next_state"]
