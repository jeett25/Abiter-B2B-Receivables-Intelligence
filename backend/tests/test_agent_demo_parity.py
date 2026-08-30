"""Subtask 3 checkpoint: the graph must not change the underlying decision.

For each of the 6 curated demo fixtures (synthetic/demo_fixtures.json), runs
the same invoice through both app.decision.service.decide() (Day-3 direct)
and app.agent.graph.run_invoice() (the graph) at the identical as_of, and
asserts they agree on every decision-relevant output.

Deliberately NOT asserting against each fixture's "expected_action" label --
that's a Day-1 aspirational label, and CLAUDE.md's own Day-3 integration
notes already record that promise_breaker_reassess's "reassess" isn't a real
action either engine produces yet (anticipates Day 4's state machine). The
only thing this test cares about is decide() == run_invoice() for the same
invoice/moment, for all 6 fixtures including that one.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.core.db import engine
from app.decision.service import DEFAULT_AS_OF, decide
from app.models import Invoice

FIXTURES_PATH = Path(__file__).parent.parent / "synthetic" / "demo_fixtures.json"
FIXTURES = json.loads(FIXTURES_PATH.read_text())


@pytest.mark.parametrize("scenario_key", list(FIXTURES.keys()))
def test_graph_matches_direct_decision_for_demo_fixture(scenario_key, db_session):
    invoice_number = FIXTURES[scenario_key]["invoice_number"]
    invoice_id = db_session.execute(
        select(Invoice.id).where(Invoice.invoice_number == invoice_number)
    ).scalar_one()

    direct = decide(invoice_id, as_of=DEFAULT_AS_OF, engine=engine)

    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DEFAULT_AS_OF)
    graph_result = run_invoice(invoice_id, event=event)

    assert graph_result["recovery_probability"] == pytest.approx(direct.base_probability, abs=1e-9)
    assert graph_result["is_disputed"] == direct.is_disputed
    assert graph_result["is_actually_paid"] == direct.is_actually_paid
    assert graph_result["proposed_action"] == direct.proposed_action
    assert graph_result["selected_action"] == direct.final_action
    assert graph_result["policy_verdict"] == direct.policy_verdict
    assert graph_result["economics_ranking"] == direct.economics_ranking

    # Order/ties in a floating-point RRF fusion score aren't guaranteed
    # stable across two separately-issued SQL queries with no ORDER BY --
    # comparing the retrieved set, not the exact ordered list, is the
    # meaningful assertion here (evidence content, not incidental ordering).
    graph_case_ids = {c.invoice_id for c in graph_result["retrieved_cases"]}
    direct_case_ids = {c.invoice_id for c in direct.retrieved_cases}
    assert graph_case_ids == direct_case_ids
