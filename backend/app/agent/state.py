from __future__ import annotations

import uuid
from typing import Any, TypedDict

from app.agent.events import Event
from app.decision.economics import ActionEV
from app.decision.policy import PolicyVerdict
from app.models.enums import AccountCurrentState, ActionType
from app.retrieval.hybrid_search import RetrievedCase


class ToolResult(TypedDict):
    """Structured result every action/tool interface (subtask 5) returns.
    Plain TypedDict, not a dataclass -- this shape is meant to land directly
    in decision_logs.evidence as JSON, no serialization step needed."""

    success: bool
    action: str
    external_id: str | None
    message: str
    timestamp: str


class GraphState(TypedDict, total=False):
    invoice_id: uuid.UUID
    customer_id: uuid.UUID
    event: Event
    current_state: AccountCurrentState
    next_state: AccountCurrentState | None
    state_transition_path: list[AccountCurrentState]  # Subtask 9's audit narrative; see state_machine.py
    is_disputed: bool
    is_actually_paid: bool
    prior_contact_count: int
    days_since_last_contact: int | None
    features: dict[str, Any] | None
    recovery_probability: float | None
    ptp_probability: float | None
    retrieved_cases: list[RetrievedCase]
    candidate_actions: list[ActionType]
    economics_ranking: list[ActionEV]
    proposed_action: ActionType | None  # ECONOMICS' raw recommendation, pre-policy
    policy_verdict: PolicyVerdict | None
    selected_action: ActionType | None  # policy_verdict.final_action -- the actual chosen action
    tool_result: ToolResult | None
    error: str | None
    retry_count: int
