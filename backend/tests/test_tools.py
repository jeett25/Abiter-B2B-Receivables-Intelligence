"""app/agent/tools.py tests: pure, no real network calls.

Simulated channels (email/whatsapp/voice/human-handoff) are tested directly,
including their deterministic failure_mode seam (no randomness anywhere in
this module). create_payment_link is tested via dependency injection (its
optional `client` param) so none of these hit the real Razorpay API: a fake
client returning a successful link, no keys configured (the fast-fail
path), a fake client that raises a generic error (the structured-failure-
not-crash path), and a fake client that raises a duplicate-reference_id
error (the idempotency path).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.agent import tools
from app.agent.tools import create_payment_link, execute_email, execute_voice, execute_whatsapp, request_human_handoff

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
INVOICE_ID = uuid.uuid4()


class _FakePaymentLinkResource:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def create(self, data):
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeRazorpayClient:
    def __init__(self, response=None, exc=None):
        self.payment_link = _FakePaymentLinkResource(response=response, exc=exc)


# -- simulated channels -----------------------------------------------------


def test_execute_email_succeeds_by_default():
    result = execute_email(invoice_number="INV-1001", amount=Decimal("45000.00"), now=NOW)
    assert result["success"] is True
    assert result["action"] == "email"
    assert result["external_id"] is not None
    assert "INV-1001" in result["message"]
    assert result["timestamp"] == NOW.isoformat()


def test_execute_email_failure_mode_is_deterministic_not_random():
    for _ in range(5):
        result = execute_email(invoice_number="INV-1001", amount=Decimal("45000.00"), now=NOW, failure_mode=True)
        assert result["success"] is False
        assert result["external_id"] is None


def test_execute_whatsapp_succeeds_by_default():
    result = execute_whatsapp(invoice_number="INV-1002", amount=Decimal("12000.00"), now=NOW)
    assert result["success"] is True
    assert result["action"] == "whatsapp"


def test_execute_whatsapp_failure_mode():
    result = execute_whatsapp(invoice_number="INV-1002", amount=Decimal("12000.00"), now=NOW, failure_mode=True)
    assert result["success"] is False
    assert result["action"] == "whatsapp"


def test_execute_voice_succeeds_by_default():
    result = execute_voice(invoice_number="INV-1003", amount=Decimal("98000.00"), now=NOW)
    assert result["success"] is True
    assert result["action"] == "voice"


def test_execute_voice_failure_mode():
    result = execute_voice(invoice_number="INV-1003", amount=Decimal("98000.00"), now=NOW, failure_mode=True)
    assert result["success"] is False
    assert result["action"] == "voice"


def test_request_human_handoff_has_no_external_id():
    result = request_human_handoff(invoice_number="INV-1004", reason="large amount escalation", now=NOW)
    assert result["success"] is True
    assert result["action"] == "escalate"
    assert result["external_id"] is None
    assert "large amount escalation" in result["message"]


def test_request_human_handoff_failure_mode():
    result = request_human_handoff(invoice_number="INV-1004", reason="x", now=NOW, failure_mode=True)
    assert result["success"] is False
    assert result["action"] == "escalate"


# -- create_payment_link -----------------------------------------------------


def test_create_payment_link_fast_fails_when_keys_not_configured(monkeypatch):
    monkeypatch.setattr(tools.settings, "razorpay_key_id", None)
    monkeypatch.setattr(tools.settings, "razorpay_key_secret", None)

    result = create_payment_link(invoice_id=INVOICE_ID, invoice_number="INV-2001", amount=Decimal("50000.00"), now=NOW)

    assert result["success"] is False
    assert result["action"] == "payment_link"
    assert result["external_id"] is None
    assert "not configured" in result["message"]


def test_create_payment_link_success_with_fake_client(monkeypatch):
    monkeypatch.setattr(tools.settings, "razorpay_key_id", "rzp_test_fake")
    monkeypatch.setattr(tools.settings, "razorpay_key_secret", "fake_secret")

    fake_client = _FakeRazorpayClient(response={"id": "plink_fake123", "short_url": "https://rzp.io/l/fake123"})
    result = create_payment_link(
        invoice_id=INVOICE_ID, invoice_number="INV-2002", amount=Decimal("75000.00"), now=NOW, client=fake_client
    )

    assert result["success"] is True
    assert result["external_id"] == "plink_fake123"
    assert "https://rzp.io/l/fake123" in result["message"]


def test_create_payment_link_uses_stable_invoice_id_derived_reference_and_converts_to_paise(monkeypatch):
    monkeypatch.setattr(tools.settings, "razorpay_key_id", "rzp_test_fake")
    monkeypatch.setattr(tools.settings, "razorpay_key_secret", "fake_secret")

    captured = {}

    class _CapturingResource:
        def create(self, data):
            captured.update(data)
            return {"id": "plink_x", "short_url": "https://rzp.io/l/x"}

    class _CapturingClient:
        payment_link = _CapturingResource()

    create_payment_link(
        invoice_id=INVOICE_ID, invoice_number="INV-2003", amount=Decimal("45000.00"), now=NOW, client=_CapturingClient()
    )
    assert captured["amount"] == 4500000
    assert captured["currency"] == "INR"
    assert captured["reference_id"] == str(INVOICE_ID)


def test_create_payment_link_decimal_avoids_float_rounding_artifacts(monkeypatch):
    """A value like 45000.10 has no exact binary float representation --
    Decimal(str(x)) must still convert to exactly 4500010 paise, not
    4500009 or 4500011 from a binary-float artifact."""
    monkeypatch.setattr(tools.settings, "razorpay_key_id", "rzp_test_fake")
    monkeypatch.setattr(tools.settings, "razorpay_key_secret", "fake_secret")

    captured = {}

    class _CapturingResource:
        def create(self, data):
            captured.update(data)
            return {"id": "plink_x", "short_url": "https://rzp.io/l/x"}

    class _CapturingClient:
        payment_link = _CapturingResource()

    amount = Decimal(str(45000.10))
    create_payment_link(invoice_id=INVOICE_ID, invoice_number="INV-2005", amount=amount, now=NOW, client=_CapturingClient())
    assert captured["amount"] == 4500010


def test_create_payment_link_converts_generic_exception_to_a_structured_failure(monkeypatch):
    """The exact thing this subtask's checkpoint asks to prove: a raised
    exception at the Razorpay boundary never propagates out of this
    function."""
    monkeypatch.setattr(tools.settings, "razorpay_key_id", "rzp_test_fake")
    monkeypatch.setattr(tools.settings, "razorpay_key_secret", "fake_secret")

    fake_client = _FakeRazorpayClient(exc=ConnectionError("network unreachable"))
    result = create_payment_link(
        invoice_id=INVOICE_ID, invoice_number="INV-2004", amount=Decimal("30000.00"), now=NOW, client=fake_client
    )

    assert result["success"] is False
    assert result["action"] == "payment_link"
    assert result["external_id"] is None
    assert "network unreachable" in result["message"]


def test_create_payment_link_duplicate_reference_id_is_idempotent_not_a_failure(monkeypatch):
    """Simulates a retried event calling this function twice for the same
    invoice (e.g. a crash before graph state was persisted) -- the second
    call must not report a failure, since the desired outcome (a payment
    link exists for this invoice) is already true."""
    monkeypatch.setattr(tools.settings, "razorpay_key_id", "rzp_test_fake")
    monkeypatch.setattr(tools.settings, "razorpay_key_secret", "fake_secret")

    fake_client = _FakeRazorpayClient(exc=Exception("BadRequestError: reference_id already exists"))
    result = create_payment_link(
        invoice_id=INVOICE_ID, invoice_number="INV-2006", amount=Decimal("30000.00"), now=NOW, client=fake_client
    )

    assert result["success"] is True
    assert result["external_id"] is None
    assert "idempotent" in result["message"]
    assert str(INVOICE_ID) in result["message"]
