"""GET /api/demo-fixtures -- integration test against the real dev DB."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
FIXTURES_PATH = Path(__file__).parent.parent / "synthetic" / "demo_fixtures.json"


def test_get_demo_fixtures_returns_all_6_with_a_real_explanation_each():
    resp = client.get("/api/demo-fixtures")
    assert resp.status_code == 200
    body = resp.json()

    expected_keys = set(json.loads(FIXTURES_PATH.read_text()).keys())
    assert {f["key"] for f in body} == expected_keys

    for f in body:
        # Every fixture must carry real, non-empty explanatory copy -- this
        # is the whole point of the 2026-09-03 addition (a viewer with no
        # source-code context needs to understand what they're looking at
        # from the page itself). See app/api/routes/demo.py's _EXPLANATIONS.
        assert isinstance(f["explanation"], str)
        assert len(f["explanation"]) > 40


def test_reliable_payer_wait_resolves_to_the_2026_09_03_repin():
    # INV-10765, not the original INV-10330 -- see CLAUDE.md and
    # synthetic/seed_demo.py's verify_reliable_payer_wait().
    resp = client.get("/api/demo-fixtures")
    body = resp.json()
    fixture = next(f for f in body if f["key"] == "reliable_payer_wait")
    assert fixture["invoice_number"] == "INV-10765"
