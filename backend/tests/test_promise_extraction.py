"""Subtask 7 checkpoint: LLM promise extraction + PTP activation.

_call_groq_once/extract_promise are tested via a fake Groq client (mirrors
test_tools.py's _FakeRazorpayClient pattern) so most of this file runs
offline/deterministically. One real-Groq test and two full-graph tests hit
the actual configured LLM_API_KEY -- skipped gracefully if it isn't set,
same non-blocking treatment the Razorpay key got in Subtask 5.
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.agent.promise_extraction import ExtractedPromise, _call_groq_once, extract_promise
from app.core.config import settings
from app.models import Invoice
from app.models.enums import AccountCurrentState, InvoiceStatus

REFERENCE_DATE = date(2026, 8, 24)  # a Monday
requires_groq_key = pytest.mark.skipif(not settings.llm_api_key, reason="LLM_API_KEY not configured")


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content=None, exc=None):
        self._content = content
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeGroqClient:
    def __init__(self, content=None, exc=None):
        self.chat = _FakeChat(_FakeCompletions(content=content, exc=exc))


# -- pure: _call_groq_once ---------------------------------------------------


def test_call_groq_once_parses_a_valid_promise():
    content = json.dumps({"promise_found": True, "promised_amount": 200000, "promised_date": "2026-08-28"})
    result = _call_groq_once("I'll pay 2 lakh on Friday", REFERENCE_DATE, client=_FakeGroqClient(content=content))
    assert result["ok"] is True
    assert result["promise_found"] is True
    assert result["promised_amount"] == Decimal("200000")
    assert result["promised_date"] == date(2026, 8, 28)


def test_call_groq_once_handles_no_promise_found():
    content = json.dumps({"promise_found": False, "promised_amount": None, "promised_date": None})
    result = _call_groq_once("I need more time", REFERENCE_DATE, client=_FakeGroqClient(content=content))
    assert result["ok"] is True
    assert result["promise_found"] is False


def test_call_groq_once_rejects_malformed_json():
    result = _call_groq_once("x", REFERENCE_DATE, client=_FakeGroqClient(content="not json"))
    assert result["ok"] is False


def test_call_groq_once_rejects_missing_promise_found_key():
    content = json.dumps({"promised_amount": 1000, "promised_date": "2026-08-28"})
    result = _call_groq_once("x", REFERENCE_DATE, client=_FakeGroqClient(content=content))
    assert result["ok"] is False


def test_call_groq_once_rejects_non_positive_amount():
    content = json.dumps({"promise_found": True, "promised_amount": -500, "promised_date": "2026-08-28"})
    result = _call_groq_once("x", REFERENCE_DATE, client=_FakeGroqClient(content=content))
    assert result["ok"] is False


def test_call_groq_once_rejects_invalid_date():
    content = json.dumps({"promise_found": True, "promised_amount": 1000, "promised_date": "not-a-date"})
    result = _call_groq_once("x", REFERENCE_DATE, client=_FakeGroqClient(content=content))
    assert result["ok"] is False


def test_call_groq_once_converts_api_exception_to_structured_failure():
    result = _call_groq_once("x", REFERENCE_DATE, client=_FakeGroqClient(exc=ConnectionError("timeout")))
    assert result["ok"] is False


# -- pure: extract_promise (retry + fallback) --------------------------------


def test_extract_promise_returns_extracted_promise_on_success():
    content = json.dumps({"promise_found": True, "promised_amount": 200000, "promised_date": "2026-08-28"})
    result = extract_promise("I'll pay 2 lakh on Friday", REFERENCE_DATE, client=_FakeGroqClient(content=content))
    assert result == ExtractedPromise(promised_amount=Decimal("200000"), promised_date=date(2026, 8, 28))


def test_extract_promise_returns_none_when_no_promise_found():
    content = json.dumps({"promise_found": False, "promised_amount": None, "promised_date": None})
    result = extract_promise("I need more time", REFERENCE_DATE, client=_FakeGroqClient(content=content))
    assert result is None


def test_extract_promise_returns_none_after_exhausting_retries_does_not_guess():
    """The exact thing this subtask's checkpoint cares about for the failure
    path: two failed attempts must never fabricate a promise."""
    result = extract_promise("x", REFERENCE_DATE, client=_FakeGroqClient(exc=ConnectionError("down")))
    assert result is None


# -- real Groq call -----------------------------------------------------------


@requires_groq_key
def test_extract_promise_resolves_a_relative_date_against_a_real_llm_call():
    result = extract_promise("I'll pay Rs 2,00,000 this Friday.", REFERENCE_DATE)
    assert result is not None
    assert result.promised_amount == Decimal("200000")
    assert result.promised_date == date(2026, 8, 28)  # the Friday following REFERENCE_DATE (a Monday)


@requires_groq_key
def test_extract_promise_correctly_finds_no_promise_in_a_vague_message():
    result = extract_promise("I'm not sure when I can pay, things are tight right now.", REFERENCE_DATE)
    assert result is None


# -- full graph ---------------------------------------------------------------


@requires_groq_key
def test_full_graph_creates_a_promise_and_scores_it_with_ptp(db_session):
    """Deliberately excludes disputed invoices -- PROMISE_CREATED on a
    disputed invoice correctly lands in DISPUTE_REVIEW, not PROMISE (dispute
    priority, already covered by test_state_machine.py). This test exercises
    the clean, undisputed path specifically, not that interaction."""
    live_invoice_id = db_session.execute(
        select(Invoice.id)
        .where(Invoice.status == InvoiceStatus.OPEN)
        .where(Invoice.true_root_cause != "dispute")
        .limit(1)
    ).scalar_one()

    event = Event(
        event_type=EventType.CUSTOMER_RESPONDED,
        invoice_id=live_invoice_id,
        occurred_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        payload={"channel": "whatsapp", "transcript": "I'll pay Rs 2,00,000 this Friday."},
    )
    result = run_invoice(live_invoice_id, event=event)

    assert result["event"].event_type == EventType.PROMISE_CREATED
    assert result["event"].payload["promised_amount"] == 200000.0
    assert result["event"].payload["promised_date"] == "2026-08-28"
    assert result["event"].payload["source"] == "whatsapp"
    assert result["next_state"].value == "promise"
    assert 0.0 <= result["ptp_probability"] <= 1.0

    # the ordinary assessment pipeline never ran for this round
    assert "economics_ranking" not in result
    assert "policy_verdict" not in result
    assert "tool_result" not in result
    assert "recovery_probability" not in result


@requires_groq_key
def test_full_graph_falls_through_to_normal_pipeline_when_no_promise_is_made(db_session):
    live_invoice_id = db_session.execute(
        select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).limit(1)
    ).scalar_one()

    event = Event(
        event_type=EventType.CUSTOMER_RESPONDED,
        invoice_id=live_invoice_id,
        occurred_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        payload={"channel": "whatsapp", "transcript": "I'm not sure when I can pay, things are tight."},
    )
    result = run_invoice(live_invoice_id, event=event)

    assert result["event"].event_type == EventType.CUSTOMER_RESPONDED  # unchanged
    assert "economics_ranking" in result
    assert "recovery_probability" in result
    assert isinstance(result["next_state"], AccountCurrentState)
