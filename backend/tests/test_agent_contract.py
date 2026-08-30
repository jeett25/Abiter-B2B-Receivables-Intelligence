"""app/agent/{events,state}.py tests: pure, no DB required.

Proves the Day-4 state/event contract can actually hold Day-3's real
dataclasses unmodified (ActionEV, PolicyVerdict, RetrievedCase) -- not mocks
standing in for a shape that might not fit.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.agent.events import Event, EventType
from app.agent.state import GraphState, ToolResult
from app.decision.economics import ActionEV
from app.decision.policy import PolicyVerdict
from app.models.enums import AccountCurrentState, ActionType, PolicyResult
from app.retrieval.hybrid_search import RetrievedCase

INVOICE_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


# -- Event ----------------------------------------------------------------


@pytest.mark.parametrize("event_type", list(EventType))
def test_event_constructs_for_every_event_type(event_type):
    event = Event(event_type=event_type, invoice_id=INVOICE_ID, occurred_at=NOW)
    assert event.event_type == event_type
    assert event.invoice_id == INVOICE_ID
    assert event.payload == {}
    assert isinstance(event.event_id, uuid.UUID)


def test_event_id_is_unique_per_instance():
    a = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=INVOICE_ID, occurred_at=NOW)
    b = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=INVOICE_ID, occurred_at=NOW)
    assert a.event_id != b.event_id


def test_event_carries_type_specific_payload():
    event = Event(
        event_type=EventType.PROMISE_CREATED,
        invoice_id=INVOICE_ID,
        occurred_at=NOW,
        payload={"promised_amount": 200_000.0, "promised_date": "2026-09-04", "source": "whatsapp"},
    )
    assert event.payload["promised_amount"] == 200_000.0
    assert event.payload["source"] == "whatsapp"


def test_event_is_frozen():
    event = Event(event_type=EventType.PAYMENT_RECEIVED, invoice_id=INVOICE_ID, occurred_at=NOW)
    with pytest.raises(AttributeError):
        event.invoice_id = uuid.uuid4()


# -- GraphState -------------------------------------------------------------


def _sample_retrieved_case() -> RetrievedCase:
    return RetrievedCase(
        invoice_id=uuid.uuid4(),
        case_text="SMB segment, Retail industry customer...",
        status="paid",
        delay_days=12,
        amount=45_000.0,
        segment="SMB",
        industry="Retail",
        action_types=["whatsapp", "payment_link"],
        vector_rank=1,
        bm25_rank=2,
        amount_rank=1,
        rrf_score=0.045,
    )


def _sample_action_ev() -> ActionEV:
    return ActionEV(
        action_type=ActionType.WHATSAPP,
        probability=0.62,
        cost=10.0,
        friction=4.0,
        expected_value=27_876.0,
    )


def _sample_policy_verdict() -> PolicyVerdict:
    return PolicyVerdict(result=PolicyResult.ALLOWED, final_action=ActionType.WHATSAPP, reason="no policy constraints triggered")


def test_graph_state_holds_real_day3_objects_unmodified():
    state: GraphState = {
        "invoice_id": INVOICE_ID,
        "customer_id": CUSTOMER_ID,
        "event": Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=INVOICE_ID, occurred_at=NOW),
        "current_state": AccountCurrentState.OVERDUE,
        "next_state": None,
        "is_disputed": False,
        "is_actually_paid": False,
        "features": {"amount": 45_000.0, "payment_term_days": 60, "customer_segment": "SMB"},
        "recovery_probability": 0.62,
        "ptp_probability": None,
        "retrieved_cases": [_sample_retrieved_case()],
        "candidate_actions": [ActionType.WAIT, ActionType.EMAIL, ActionType.WHATSAPP],
        "economics_ranking": [_sample_action_ev()],
        "policy_verdict": _sample_policy_verdict(),
        "selected_action": ActionType.WHATSAPP,
        "tool_result": None,
        "error": None,
        "retry_count": 0,
    }

    assert state["economics_ranking"][0].action_type == ActionType.WHATSAPP
    assert state["policy_verdict"].result == PolicyResult.ALLOWED
    assert state["retrieved_cases"][0].segment == "SMB"
    assert isinstance(state["features"], dict)  # not a pandas Series


def test_graph_state_is_partial_by_default():
    # total=False: a node returning only the keys it touched is valid.
    partial: GraphState = {"invoice_id": INVOICE_ID, "retry_count": 1}
    assert partial["retry_count"] == 1
    assert "policy_verdict" not in partial


def test_tool_result_shape():
    result: ToolResult = {
        "success": True,
        "action": "WHATSAPP",
        "external_id": "wa_msg_123",
        "message": "sent",
        "timestamp": NOW.isoformat(),
    }
    assert result["success"] is True
    assert set(result.keys()) == {"success", "action", "external_id", "message", "timestamp"}
