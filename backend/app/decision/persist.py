from __future__ import annotations

from datetime import datetime

from app.core.db import SessionLocal
from app.decision.economics import ActionEV
from app.decision.service import Decision
from app.models import AccountState, DecisionLog
from app.models.enums import AccountCurrentState, ActionType
from app.retrieval.hybrid_search import RetrievedCase

# One-shot mapping from today's chosen action to an account_state -- NOT the
# full Day-4 state machine (OVERDUE -> ASSESSMENT -> WAIT/REMIND/ESCALATE ->
# PROMISE -> MONITORING -> KEPT/BROKEN -> REASSESS -> CLOSED), which requires
# actually executing actions and observing outcomes over time. This only
# reflects "what state does the account move to as a direct result of
# today's decision" -- a single transition out of OVERDUE.
_SIMPLE_ACTION_TO_STATE: dict[ActionType, AccountCurrentState] = {
    ActionType.WAIT: AccountCurrentState.WAIT,
    ActionType.EMAIL: AccountCurrentState.REMIND,
    ActionType.WHATSAPP: AccountCurrentState.REMIND,
    ActionType.PAYMENT_LINK: AccountCurrentState.REMIND,
    ActionType.VOICE: AccountCurrentState.REMIND,
    ActionType.ESCALATE: AccountCurrentState.ESCALATE,
}

# STOP covers two different outcomes (Policy Gate rules 1 and 3) that must
# not collapse into the same terminal state -- see AccountCurrentState's
# CLOSED_PAID/CLOSED_ABANDONED docstring in app/models/enums.py. Distinguished
# via Decision.is_actually_paid (an actual computed flag), not by matching
# substrings in the policy reason text.
def _resolve_account_state(decision: Decision) -> AccountCurrentState:
    if decision.final_action == ActionType.STOP:
        return AccountCurrentState.CLOSED_PAID if decision.is_actually_paid else AccountCurrentState.CLOSED_ABANDONED
    return _SIMPLE_ACTION_TO_STATE[decision.final_action]


# No PTP model is wired yet -- subtask 5 confirmed the live pool is a true
# blank slate (zero existing payment_promises rows), so "how credible is the
# current promise" genuinely doesn't apply until Day 4 creates one. 0.0 is a
# documented "not applicable yet" sentinel, not a prediction -- replacing Day
# 1's leaked archetype.promise_keep_probability-derived placeholder with an
# honest non-answer rather than a different kind of fabricated number.
NO_ACTIVE_PROMISE_SCORE = 0.0


def build_account_state_updates(decision: Decision) -> dict:
    """revenue_at_risk = amount * (1 - base_probability): the GROSS expected
    shortfall under the current baseline (no incremental action beyond
    WAIT), not netted against any intervention's cost/friction. Since
    EV(WAIT) = base_probability * amount - 0 - 0 (zero cost/friction, see
    app/decision/economics.py), this is exactly amount - EV(WAIT) -- the
    complement of the do-nothing baseline. It is NOT the same quantity as
    any actionable candidate's EV in economics_ranking (those net real cost
    and friction and reflect a hypothetical intervention, not the current
    baseline) -- don't treat the two as interchangeable.

    Replaces the live pool's Day-1 placeholder (revenue_at_risk = full
    invoice amount, unconditional on odds) -- historical account_state rows
    already used 0.00 for paid / full amount for written-off, which is
    already outcome-aware and untouched here; only the live pool's cruder
    placeholder is being improved on.
    """
    return {
        "current_state": _resolve_account_state(decision),
        "recoverability_score": decision.base_probability,
        "promise_score": NO_ACTIVE_PROMISE_SCORE,
        # No expected-payment-date model exists -- Day 2 explicitly skipped
        # it ("nothing downstream depends on it"). NULL, not a fabricated date.
        "expected_payment_date": None,
        "revenue_at_risk": decision.amount * (1 - decision.base_probability),
        "next_action": decision.final_action,
    }


def _action_ev_to_dict(ev: ActionEV) -> dict:
    return {
        "action_type": ev.action_type.value,
        "probability": ev.probability,
        "cost": ev.cost,
        "friction": ev.friction,
        "expected_value": ev.expected_value,
    }


def _retrieved_case_to_dict(case: RetrievedCase) -> dict:
    return {
        "invoice_id": str(case.invoice_id),
        "case_text": case.case_text,
        "status": case.status,
        "rrf_score": case.rrf_score,
    }


def build_decision_log(decision: Decision, as_of: datetime) -> DecisionLog:
    """Shape mirrors the master doc's explainability trace directly: root
    cause (policy_checks.is_disputed) -> recoverability score
    (model_scores.recovery_probability) -> candidate-action EV comparison
    (model_scores.candidate_actions) -> policy check (policy_checks) ->
    chosen action (decision/final_action)."""
    model_scores = {
        "recovery_probability": decision.base_probability,
        "candidate_actions": [_action_ev_to_dict(ev) for ev in decision.economics_ranking],
        "root_cause": (
            {"predicted_label": decision.root_cause_label, "confidence": decision.root_cause_confidence}
            if decision.root_cause_label is not None
            else None
        ),
    }
    evidence = {"retrieved_cases": [_retrieved_case_to_dict(c) for c in decision.retrieved_cases]}
    policy_checks = {
        "is_disputed": decision.is_disputed,
        "is_actually_paid": decision.is_actually_paid,
        "proposed_action": decision.proposed_action.value,
        "final_action": decision.final_action.value,
        "result": decision.policy_verdict.result.value,
    }

    return DecisionLog(
        invoice_id=decision.invoice_id,
        decision=decision.final_action.value,
        model_scores=model_scores,
        evidence=evidence,
        policy_checks=policy_checks,
        reason=decision.policy_verdict.reason,
        timestamp=as_of,
    )


def persist_decision(decision: Decision, as_of: datetime, session=None) -> None:
    owns_session = session is None
    session = session or SessionLocal()
    try:
        session.add(build_decision_log(decision, as_of))

        account_state = session.get(AccountState, decision.invoice_id)
        for key, value in build_account_state_updates(decision).items():
            setattr(account_state, key, value)

        if owns_session:
            session.commit()
    finally:
        if owns_session:
            session.close()


def persist_decisions(decisions: list[Decision], as_of: datetime) -> int:
    session = SessionLocal()
    try:
        for decision in decisions:
            persist_decision(decision, as_of, session=session)
        session.commit()
        return len(decisions)
    finally:
        session.close()


if __name__ == "__main__":
    from app.decision.service import DEFAULT_AS_OF, run_full_live_pass

    decisions = run_full_live_pass()
    n = persist_decisions(decisions, DEFAULT_AS_OF)
    print(f"Persisted {n} decisions to decision_logs + account_state")
