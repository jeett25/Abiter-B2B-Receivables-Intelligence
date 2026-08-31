"""GET /api/invoices/{id}/decision, GET /api/invoices/{id}/timeline --
integration tests against the real dev DB."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AttributionRecord, DecisionLog, Invoice

client = TestClient(app)


def _pick_scored_invoice(db_session):
    return db_session.execute(select(DecisionLog.invoice_id).limit(1)).scalar_one()


def _pick_never_scored_invoice(db_session):
    return db_session.execute(
        select(Invoice.id).where(~Invoice.id.in_(select(DecisionLog.invoice_id))).limit(1)
    ).scalar_one()


def _pick_recovered_invoice(db_session):
    """A treatment-arm invoice the Day-5 experiment actually resolved --
    has both a decision_logs row (Day 4) and a payments row (Day 5
    write-back), giving a timeline with more than one event type."""
    return db_session.execute(
        select(AttributionRecord.invoice_id).where(AttributionRecord.observed_recovery > 0).limit(1)
    ).scalar_one()


def test_get_decision_returns_real_decision_log_fields(db_session):
    invoice_id = _pick_scored_invoice(db_session)
    resp = client.get(f"/api/invoices/{invoice_id}/decision")
    assert resp.status_code == 200
    body = resp.json()
    assert body["invoice_id"] == str(invoice_id)
    assert "recovery_probability" in body["model_scores"]
    # Real agent-shaped keys (see app/api/DECISIONS.md) -- NOT
    # frontend/lib/types.ts's stale final_action/result names.
    assert "is_disputed" in body["policy_checks"]
    assert body["decision"]
    assert body["reason"]


def test_get_decision_404_for_never_scored_invoice(db_session):
    invoice_id = _pick_never_scored_invoice(db_session)
    resp = client.get(f"/api/invoices/{invoice_id}/decision")
    assert resp.status_code == 404


def test_get_decision_404_for_unknown_invoice():
    resp = client.get(f"/api/invoices/{uuid4()}/decision")
    assert resp.status_code == 404


def test_get_timeline_includes_decision_and_payment_events_chronologically(db_session):
    invoice_id = _pick_recovered_invoice(db_session)
    resp = client.get(f"/api/invoices/{invoice_id}/timeline")
    assert resp.status_code == 200
    body = resp.json()
    types = {e["type"] for e in body["events"]}
    assert "decision" in types
    assert "payment" in types

    timestamps = [e["timestamp"] for e in body["events"]]
    assert timestamps == sorted(timestamps)


def test_get_timeline_404_for_unknown_invoice():
    resp = client.get(f"/api/invoices/{uuid4()}/timeline")
    assert resp.status_code == 404
