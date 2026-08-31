"""GET /api/attribution -- integration test against the real dev DB."""
from fastapi.testclient import TestClient

from app.attribution.config import EXPERIMENT_ID
from app.main import app

client = TestClient(app)


def test_get_attribution_default_excludes_diagnostics(db_session):
    resp = client.get("/api/attribution")
    assert resp.status_code == 200
    body = resp.json()
    assert body["experiment_id"] == EXPERIMENT_ID
    assert len(body["slices"]) > 0
    # Gated fields absent entirely (response_model_exclude_none), not
    # present-but-null -- see app/api/DECISIONS.md.
    assert "escalate_by_archetype" not in body
    assert "consistency_warnings" not in body


def test_get_attribution_slices_include_the_portfolio_row(db_session):
    body = client.get("/api/attribution").json()
    portfolio_rows = [s for s in body["slices"] if s["segment"] is None and s["action"] is None]
    assert len(portfolio_rows) == 1


def test_get_attribution_with_diagnostics_includes_archetype_breakdown_and_warnings(db_session):
    resp = client.get("/api/attribution", params={"include_diagnostics": True})
    assert resp.status_code == 200
    body = resp.json()
    assert "escalate_by_archetype" in body
    assert any(row["archetype"] == "strategic_enterprise" for row in body["escalate_by_archetype"])
    assert "consistency_warnings" in body
    assert any("escalate" in w for w in body["consistency_warnings"])
