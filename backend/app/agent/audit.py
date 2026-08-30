"""Audit persistence -- Subtask 9.

Builds a DecisionLog + AccountState update from GraphState. Deliberately
defensive throughout (.get()/"key" in state, never blind indexing) because
GraphState has three genuinely different shapes by the time write_audit
runs, not one:
  1. Normal pipeline (most events): recovery_probability, retrieved_cases,
     economics_ranking, proposed_action, policy_verdict, selected_action,
     tool_result, next_state all present.
  2. Promise-creation (Subtask 7's SCORE_PTP path): only ptp_probability +
     next_state -- none of the economics/policy/tool fields exist.
  3. Invalid event (Subtask 6's routing): only error/retry_count -- no
     next_state at all, since UPDATE_STATE never ran for this path.

Reuses app.decision.persist's _action_ev_to_dict/_retrieved_case_to_dict
directly (verified safe: both operate on a single always-fully-populated
dataclass instance with no internal iteration or null-checking of their
own -- the list-comprehension and the "does this list exist" question both
live here, at the call site, not inside those helpers).
"""
from __future__ import annotations

from datetime import datetime

from app.decision.persist import _action_ev_to_dict, _retrieved_case_to_dict
from app.models import DecisionLog


def _decision_label(state: dict) -> str:
    if "selected_action" in state:
        return state["selected_action"].value
    if "next_state" in state:
        return state["next_state"].value
    return "rejected"


def _build_model_scores(state: dict) -> dict:
    scores = {
        "recovery_probability": state.get("recovery_probability"),
        "ptp_probability": state.get("ptp_probability"),
    }
    if "economics_ranking" in state:
        scores["candidate_actions"] = [_action_ev_to_dict(ev) for ev in state["economics_ranking"]]
    return scores


def _build_evidence(state: dict) -> dict:
    event = state["event"]
    evidence = {"trigger_event": {"event_type": event.event_type.value, "payload": event.payload}}
    if "retrieved_cases" in state:
        evidence["retrieved_cases"] = [_retrieved_case_to_dict(c) for c in state["retrieved_cases"]]
    return evidence


def _build_policy_checks(state: dict) -> dict:
    checks = {
        "is_disputed": state.get("is_disputed"),
        "is_actually_paid": state.get("is_actually_paid"),
        "state_transition_path": [s.value for s in state.get("state_transition_path", [])],
        "retry_count": state.get("retry_count"),
        "error": state.get("error"),
    }
    if "proposed_action" in state:
        checks["proposed_action"] = state["proposed_action"].value
    if "selected_action" in state:
        checks["selected_action"] = state["selected_action"].value
    if "policy_verdict" in state:
        checks["policy_result"] = state["policy_verdict"].result.value
    if "tool_result" in state:
        checks["tool_result"] = state["tool_result"]
    return checks


def _build_reason(state: dict) -> str:
    if state.get("error"):
        return state["error"]
    if "policy_verdict" in state:
        return state["policy_verdict"].reason
    if "next_state" in state:
        return f"promise recorded -- account moved to {state['next_state'].value}"
    return "no assessment this round"


def build_decision_log(state: dict) -> DecisionLog:
    """Shape mirrors app.decision.persist.build_decision_log's Day-3
    convention (root cause -> recoverability score -> candidate-action EV
    comparison -> policy check -> chosen action), extended with
    ptp_probability, state_transition_path, retry_count, and the triggering
    event itself in evidence (fulfilling Subtask 1's Event docstring's
    traceability note, not done until now) -- and made to degrade
    gracefully for the promise-creation and invalid-event shapes, which
    Day 3's version never had to handle."""
    return DecisionLog(
        invoice_id=state["invoice_id"],
        decision=_decision_label(state),
        model_scores=_build_model_scores(state),
        evidence=_build_evidence(state),
        policy_checks=_build_policy_checks(state),
        reason=_build_reason(state),
        timestamp=state["event"].occurred_at,
    )


def build_account_state_updates(state: dict) -> dict:
    """Only called when next_state is present (write_audit's caller
    guards this) -- shape 3 (invalid event) never reaches here, since there
    is no next_state to write and fabricating one would be worse than
    leaving the row untouched. Fields Subtask 9 doesn't have fresh data
    for this round (recoverability_score when this was a promise-creation
    round, e.g.) are simply omitted from the returned dict -- the caller's
    setattr loop leaves whatever was already in the row alone, the same
    current-snapshot-only-overwrite-what-was-recomputed logic Day 3 used
    per-row, just applied per-field now."""
    updates: dict = {"current_state": state["next_state"]}
    if "selected_action" in state:
        updates["next_action"] = state["selected_action"]
    if "recovery_probability" in state:
        updates["recoverability_score"] = state["recovery_probability"]
        updates["revenue_at_risk"] = state["features"]["amount"] * (1 - state["recovery_probability"])
    if state.get("ptp_probability") is not None:
        updates["promise_score"] = state["ptp_probability"]
    return updates
