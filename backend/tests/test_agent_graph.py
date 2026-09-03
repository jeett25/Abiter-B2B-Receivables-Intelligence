"""app/agent/{nodes,graph}.py tests.

Node-level tests (dispatch_action, update_account_state,
_feature_row_to_dict) are pure, no DB. Full-graph tests are integration
tests against the real dev DB and persisted Day-2 model artifacts, same
convention as test_decision_service.py.
"""
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.agent.nodes import _feature_row_to_dict, dispatch_action, update_account_state
from app.core.db import engine
from app.decision.service import DEFAULT_AS_OF, decide
from app.ml.config import CALIBRATED_PROBABILITY_CEILING, CALIBRATED_PROBABILITY_FLOOR
from app.models import Invoice
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus, PolicyResult

# -- pure: _feature_row_to_dict ---------------------------------------------


def test_feature_row_to_dict_strips_pandas_types_but_preserves_nan():
    row = pd.Series(
        {
            "amount": np.float64(45000.0),
            "prior_avg_delay_days": np.nan,
            "prior_invoice_count": np.int64(3),
            "due_date": pd.Timestamp("2026-08-20"),
            "customer_segment": "SMB",
            "has_prior_history": np.bool_(True),
        }
    )
    result = _feature_row_to_dict(row)

    assert type(result["amount"]) is float
    assert type(result["prior_invoice_count"]) is int
    assert isinstance(result["due_date"], datetime) and not isinstance(result["due_date"], pd.Timestamp)
    assert result["customer_segment"] == "SMB"
    assert result["has_prior_history"] is True
    assert isinstance(result["prior_avg_delay_days"], float) and pd.isna(result["prior_avg_delay_days"])


# -- pure: dispatch_action ---------------------------------------------------


def _dispatch_state(action: ActionType) -> dict:
    return {
        "invoice_id": uuid.uuid4(),
        "selected_action": action,
        "event": Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=None, occurred_at=DEFAULT_AS_OF),
        "features": {"invoice_number": "INV-99999", "amount": 45000.0},
    }


@pytest.mark.parametrize("action", [ActionType.WAIT, ActionType.STOP])
def test_dispatch_action_no_ops_for_wait_and_stop(action):
    result = dispatch_action(_dispatch_state(action))
    assert result["tool_result"] is None


@pytest.mark.parametrize("action", [ActionType.EMAIL, ActionType.WHATSAPP, ActionType.VOICE, ActionType.ESCALATE])
def test_dispatch_action_calls_the_real_simulated_tool(action):
    """PAYMENT_LINK is excluded here (covered in test_tools.py with a fake
    client) since this file's other tests are pure/no-network -- dispatching
    it here would either hit the real Razorpay API or the fast-fail path
    depending on whether keys happen to be configured in this environment."""
    result = dispatch_action(_dispatch_state(action))
    assert result["tool_result"]["success"] is True
    assert result["tool_result"]["action"] == action.value
    assert "INV-99999" in result["tool_result"]["message"]


def test_dispatch_action_wires_payment_link_without_crashing():
    """Doesn't assert success/failure -- that depends on whether real
    Razorpay keys are configured in this environment (test_tools.py covers
    both paths deterministically via a fake client). Only proves the wiring
    itself never raises, regardless."""
    result = dispatch_action(_dispatch_state(ActionType.PAYMENT_LINK))
    assert result["tool_result"]["action"] == "payment_link"
    assert isinstance(result["tool_result"]["success"], bool)


# -- pure: update_account_state (thin caller into state_machine.py) --------


def test_update_account_state_wires_into_the_real_transition_function():
    """The rules themselves are fully covered by test_state_machine.py --
    this only confirms update_account_state passes the right fields through
    and surfaces both next_state and state_transition_path."""
    state = {
        "current_state": AccountCurrentState.OVERDUE,
        "event": Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=None, occurred_at=DEFAULT_AS_OF),
        "is_disputed": False,
        "is_actually_paid": False,
        "selected_action": ActionType.WHATSAPP,
    }
    result = update_account_state(state)
    assert result["next_state"] == AccountCurrentState.REMIND
    assert result["state_transition_path"] == [AccountCurrentState.REMIND]


# -- integration: full graph -------------------------------------------------


def test_run_invoice_produces_a_sane_decision_for_a_real_live_invoice(db_session):
    live_invoice_id = db_session.execute(
        select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).limit(1)
    ).scalar_one()

    result = run_invoice(live_invoice_id)

    assert CALIBRATED_PROBABILITY_FLOOR <= result["recovery_probability"] <= CALIBRATED_PROBABILITY_CEILING
    assert isinstance(result["selected_action"], ActionType)
    assert isinstance(result["policy_verdict"].result, PolicyResult)
    assert len(result["economics_ranking"]) > 0
    assert isinstance(result["next_state"], AccountCurrentState)

    if result["selected_action"] in (ActionType.WAIT, ActionType.STOP):
        assert result["tool_result"] is None
    else:
        # Subtask 5: a real tool dispatch now happens -- assert it's a
        # well-formed ToolResult, not that it's a stub anymore.
        assert isinstance(result["tool_result"]["success"], bool)
        assert result["tool_result"]["action"] == result["selected_action"].value


def test_run_invoice_recovery_probability_matches_direct_decide_call(db_session):
    """Regression test for the pd.Series<->dict round-trip GraphState.features
    introduces: confirms scoring through the graph's dict-based feature row
    produces the identical recovery_probability the Series-based decide()
    path produces for the same invoice/as_of -- empirically confirmed, not
    assumed, matching this project's standing convention for any new
    single-row-scoring usage pattern (see docs/ml-DECISIONS.md)."""
    live_invoice_id = db_session.execute(
        select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).limit(1)
    ).scalar_one()

    direct_decision = decide(live_invoice_id, as_of=DEFAULT_AS_OF, engine=engine)

    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=live_invoice_id, occurred_at=DEFAULT_AS_OF)
    result = run_invoice(live_invoice_id, event=event)

    assert result["recovery_probability"] == pytest.approx(direct_decision.base_probability, abs=1e-9)
