"""GET /api/invoices, GET /api/invoices/{id} -- integration tests against
the real dev DB via FastAPI's TestClient."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import DecisionLog, Invoice

client = TestClient(app)


def _pick_never_scored_invoice(db_session):
    return db_session.execute(
        select(Invoice.id).where(~Invoice.id.in_(select(DecisionLog.invoice_id))).limit(1)
    ).scalar_one()


def test_list_invoices_returns_populated_rows(db_session):
    resp = client.get("/api/invoices", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 10
    row = body[0]
    assert set(row.keys()) >= {
        "invoice_id",
        "invoice_number",
        "customer_name",
        "amount",
        "due_date",
        "current_state",
        "recoverability_score",
        "next_action",
        "treatment_group",
    }


def test_list_invoices_respects_limit_and_offset(db_session):
    first = client.get("/api/invoices", params={"limit": 5, "offset": 0}).json()
    second = client.get("/api/invoices", params={"limit": 5, "offset": 5}).json()
    assert len(first) == 5
    assert len(second) == 5
    assert {r["invoice_id"] for r in first}.isdisjoint({r["invoice_id"] for r in second})


def test_list_invoices_filters_by_valid_current_state(db_session):
    resp = client.get("/api/invoices", params={"current_state": "closed_paid", "limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 0  # Day 5's write-back guarantees some exist
    assert all(row["current_state"] == "closed_paid" for row in body)


def test_list_invoices_invalid_current_state_returns_400(db_session):
    resp = client.get("/api/invoices", params={"current_state": "not_a_real_state"})
    assert resp.status_code == 400


def test_get_invoice_by_id_matches_a_list_row(db_session):
    listed = client.get("/api/invoices", params={"limit": 1}).json()[0]
    single = client.get(f"/api/invoices/{listed['invoice_id']}")
    assert single.status_code == 200
    assert single.json() == listed


def test_get_invoice_404_for_unknown_uuid(db_session):
    resp = client.get(f"/api/invoices/{uuid4()}")
    assert resp.status_code == 404


def test_get_invoice_404_for_never_scored_invoice(db_session):
    invoice_id = _pick_never_scored_invoice(db_session)
    resp = client.get(f"/api/invoices/{invoice_id}")
    assert resp.status_code == 404
