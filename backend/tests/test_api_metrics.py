"""GET /api/metrics -- integration test against the real dev DB."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_metrics_returns_baseline_engine_and_attribution(db_session):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()

    assert body["baseline"]["strategy_name"] == "Baseline (email everyone)"
    assert body["engine"]["strategy_name"] == "Decision engine"
    # Same live-pool population underlies both strategies.
    assert body["baseline"]["n_invoices"] == body["engine"]["n_invoices"]
    assert body["baseline"]["n_invoices"] > 0

    assert body["unnecessary_interventions_avoided"] >= 0

    assert body["attribution"] is not None
    assert body["attribution"]["treatment_n"] > 0
    assert body["attribution"]["control_n"] > 0


def test_get_metrics_baseline_always_intervenes_engine_sometimes_abstains(db_session):
    body = client.get("/api/metrics").json()
    # Baseline emails everyone -- zero wait/stop by construction.
    assert body["baseline"]["n_wait"] == 0
    assert body["baseline"]["n_stop"] == 0
    # The engine, having real economics, abstains on at least some invoices.
    assert body["engine"]["n_wait"] + body["engine"]["n_stop"] > 0
