from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select

from app.agent.audit import build_account_state_updates, build_decision_log
from app.agent.events import Event, EventType
from app.agent.promise_extraction import extract_promise
from app.agent.resilience import call_with_retry
from app.agent.state import GraphState
from app.agent.state_machine import TransitionContext, determine_next_state
from app.agent.tools import create_payment_link, execute_email, execute_voice, execute_whatsapp, request_human_handoff
from app.core.db import SessionLocal
from app.decision.economics import rank_actions, recommend_action
from app.decision.policy import PolicyContext, detect_already_paid, detect_dispute, evaluate_policy
from app.decision.service import RETRIEVAL_TOP_K, score_ptp_probability, score_recovery_probability
from app.ml.features import build_live_feature_table, build_live_ptp_feature_row, load_raw_tables
from app.models import AccountState, PaymentPromise
from app.models.enums import ActionType, PromiseStatus
from app.retrieval.hybrid_search import build_query_text, hybrid_retrieve


def _to_naive(ts) -> pd.Timestamp:
    
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _feature_row_to_dict(row: pd.Series) -> dict[str, Any]:

    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, pd.Timestamp):
            result[key] = value.to_pydatetime()
        elif isinstance(value, np.generic):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def ingest_event(state: GraphState) -> dict:
    event = state["event"]
    if event.invoice_id != state["invoice_id"]:
        return {
            "error": f"invalid event: event.invoice_id ({event.invoice_id}) != state invoice_id ({state['invoice_id']})",
            "retry_count": 0,
        }
    return {"retry_count": 0, "error": None}


def extract_promise_node(state: GraphState) -> dict:
    event = state["event"]
    transcript = event.payload.get("transcript", "")
    channel = event.payload.get("channel", "unknown")
    reference_date = event.occurred_at.date()

    extracted = extract_promise(transcript, reference_date)
    if extracted is None:
        return {}

    new_event = Event(
        event_type=EventType.PROMISE_CREATED,
        invoice_id=state["invoice_id"],
        occurred_at=event.occurred_at,
        payload={
            "promised_amount": float(extracted.promised_amount),
            "promised_date": extracted.promised_date.isoformat(),
            "source": channel,
        },
    )
    return {"event": new_event}


def load_context(state: GraphState, config: RunnableConfig) -> dict:
    configurable = (config or {}).get("configurable", {})
    engine = configurable.get("engine")
    tables = configurable.get("tables")
    if tables is None:
        tables = load_raw_tables(engine)

    invoice_id = state["invoice_id"]
    invoices, payments, actions = tables["invoices"], tables["payments"], tables["actions"]

    invoice_row = invoices[invoices["id"] == invoice_id].iloc[0]
    is_disputed = detect_dispute(invoice_row["true_root_cause"])

    as_of_naive = _to_naive(state["event"].occurred_at)

    invoice_payments = payments[payments["invoice_id"] == invoice_id]
    completed_total = float(invoice_payments[invoice_payments["payment_date"] <= as_of_naive]["amount"].sum())
    is_actually_paid = detect_already_paid(float(invoice_row["amount"]), completed_total)

    own_actions = actions[actions["invoice_id"] == invoice_id]
    prior_contact_count = len(own_actions)
    days_since_last_contact = (
        (as_of_naive - own_actions["timestamp"].max()).days if prior_contact_count > 0 else None
    )

    session = configurable.get("session")
    owns_session = session is None
    session = session or SessionLocal()
    try:
        account_state = session.get(AccountState, invoice_id)
        current_state = account_state.current_state
    finally:
        if owns_session:
            session.close()

    return {
        "customer_id": invoice_row["customer_id"],
        "current_state": current_state,
        "is_disputed": is_disputed,
        "is_actually_paid": is_actually_paid,
        "prior_contact_count": prior_contact_count,
        "days_since_last_contact": days_since_last_contact,
    }


def _upsert_open_promise(
    invoice_id, promised_amount: Decimal, promised_date, source: str, confidence_score: float, config: RunnableConfig
) -> None:
    configurable = (config or {}).get("configurable", {})
    session = configurable.get("session")
    owns_session = session is None
    session = session or SessionLocal()
    try:
        existing = session.execute(
            select(PaymentPromise).where(
                PaymentPromise.invoice_id == invoice_id, PaymentPromise.status == PromiseStatus.OPEN
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.promised_amount = promised_amount
            existing.promised_date = promised_date
            existing.source = source
            existing.confidence_score = confidence_score
        else:
            session.add(
                PaymentPromise(
                    invoice_id=invoice_id,
                    promised_amount=promised_amount,
                    promised_date=promised_date,
                    source=source,
                    confidence_score=confidence_score,
                    status=PromiseStatus.OPEN,
                )
            )
        if owns_session:
            session.commit()
    finally:
        if owns_session:
            session.close()


def score_ptp(state: GraphState, config: RunnableConfig) -> dict:
    configurable = (config or {}).get("configurable", {})
    engine = configurable.get("engine")
    tables = configurable.get("tables")

    event = state["event"]
    promised_date = date.fromisoformat(event.payload["promised_date"])
    source = event.payload["source"]
    cutoff = _to_naive(event.occurred_at)

    feature_row = build_live_ptp_feature_row(
        state["invoice_id"], promised_date, source, cutoff, engine=engine, tables=tables
    )
    ptp_probability = score_ptp_probability(pd.Series(feature_row))

    _upsert_open_promise(
        state["invoice_id"],
        Decimal(str(event.payload["promised_amount"])),
        promised_date,
        source,
        ptp_probability,
        config,
    )

    return {"ptp_probability": ptp_probability}


def build_features(state: GraphState, config: RunnableConfig) -> dict:
    configurable = (config or {}).get("configurable", {})
    engine = configurable.get("engine")
    live_table = configurable.get("live_feature_table")
    if live_table is None:
        live_table = build_live_feature_table(engine)

    invoice_id = state["invoice_id"]
    matches = live_table[live_table["invoice_id"] == invoice_id]
    if matches.empty:
        raise ValueError(f"invoice_id {invoice_id} not found in the live feature table")
    return {"features": _feature_row_to_dict(matches.iloc[0])}


def score_ml(state: GraphState) -> dict:
    feature_row = pd.Series(state["features"])
    return {"recovery_probability": score_recovery_probability(feature_row), "ptp_probability": None}


def retrieve_cases(state: GraphState) -> dict:
    features = state["features"]
    as_of_naive = _to_naive(state["event"].occurred_at)
    days_overdue = (as_of_naive - features["due_date"]).days

    prior_payment_rate = features["prior_payment_rate"]
    query_text = build_query_text(
        amount=float(features["amount"]),
        payment_term_days=int(features["payment_term_days"]),
        segment=features["customer_segment"],
        industry=features["customer_industry"],
        prior_payment_rate=prior_payment_rate if pd.notna(prior_payment_rate) else None,
        days_overdue=days_overdue,
    )
    retrieved = hybrid_retrieve(
        query_text=query_text,
        query_amount=float(features["amount"]),
        segment=features["customer_segment"],
        industry=features["customer_industry"],
        is_disputed=state["is_disputed"],
        top_k=RETRIEVAL_TOP_K,
    )
    return {"retrieved_cases": retrieved}


def run_economics(state: GraphState) -> dict:
    amount = float(state["features"]["amount"])
    ranking = rank_actions(
        state["recovery_probability"], amount,
        prior_contact_count=state["prior_contact_count"], is_disputed=state["is_disputed"],
    )
    proposed = recommend_action(
        state["recovery_probability"], amount,
        prior_contact_count=state["prior_contact_count"], is_disputed=state["is_disputed"],
    )
    return {
        "candidate_actions": [ev.action_type for ev in ranking],
        "economics_ranking": ranking,
        "proposed_action": proposed.action_type,
    }


def run_policy(state: GraphState) -> dict:
    context = PolicyContext(
        proposed_action=state["proposed_action"],
        base_probability=state["recovery_probability"],
        amount=float(state["features"]["amount"]),
        is_actually_paid=state["is_actually_paid"],
        is_disputed=state["is_disputed"],
        prior_contact_count=state["prior_contact_count"],
        days_since_last_contact=state["days_since_last_contact"],
        now=state["event"].occurred_at,
    )
    return {"policy_verdict": evaluate_policy(context)}


def finalize_decision(state: GraphState) -> dict:
    """Trivial merge today -- the seam Subtask 7 later hangs an LLM-authored
    explanation narrative off of. Never changes the underlying action."""
    return {"selected_action": state["policy_verdict"].final_action}


_ACTION_DISPATCH = {
    ActionType.EMAIL: lambda invoice_id, invoice_number, amount, now: execute_email(
        invoice_number=invoice_number, amount=amount, now=now
    ),
    ActionType.WHATSAPP: lambda invoice_id, invoice_number, amount, now: execute_whatsapp(
        invoice_number=invoice_number, amount=amount, now=now
    ),
    ActionType.PAYMENT_LINK: lambda invoice_id, invoice_number, amount, now: create_payment_link(
        invoice_id=invoice_id, invoice_number=invoice_number, amount=amount, now=now
    ),
    ActionType.VOICE: lambda invoice_id, invoice_number, amount, now: execute_voice(
        invoice_number=invoice_number, amount=amount, now=now
    ),
    ActionType.ESCALATE: lambda invoice_id, invoice_number, amount, now: request_human_handoff(
        invoice_number=invoice_number, reason=f"escalation for invoice {invoice_number}", now=now
    ),
}


def dispatch_action(state: GraphState) -> dict:
    action = state["selected_action"]
    if action in (ActionType.WAIT, ActionType.STOP):
        return {"tool_result": None}

    invoice_id = state["invoice_id"]
    invoice_number = state["features"]["invoice_number"]
    amount = Decimal(str(state["features"]["amount"]))
    now = state["event"].occurred_at

    result, attempts = call_with_retry(
        lambda: _ACTION_DISPATCH[action](invoice_id, invoice_number, amount, now),
        is_success=lambda r: r["success"],
    )

    if result["success"]:
        return {"tool_result": result, "retry_count": attempts - 1}

    return {
        "tool_result": result,
        "retry_count": attempts - 1,
        "selected_action": ActionType.WAIT,
        "error": f"{action.value} failed after {attempts} attempt(s): {result['message']}",
    }


def update_account_state(state: GraphState) -> dict:
    """Thin caller only -- app.agent.state_machine.determine_next_state owns
    every (current_state, event, ...) -> next_state decision in this
    project. This node computes nothing itself."""
    context = TransitionContext(
        current_state=state["current_state"],
        event=state["event"],
        is_disputed=state["is_disputed"],
        is_actually_paid=state["is_actually_paid"],
        # ActionType.WAIT is an inert placeholder for the PROMISE_CREATED
        # skip path (Subtask 7's SCORE_PTP never runs DECISION, so
        # selected_action is absent from state) -- determine_next_state
        # never actually reads it for that event type, PROVEN by
        # test_promise_created_next_state_is_independent_of_selected_action
        # in test_state_machine.py, not just asserted true-by-construction.
        selected_action=state.get("selected_action", ActionType.WAIT),
    )
    transition = determine_next_state(context)
    return {"next_state": transition.next_state, "state_transition_path": transition.path}


def write_audit(state: GraphState, config: RunnableConfig) -> dict:
    configurable = (config or {}).get("configurable", {})
    if not configurable.get("persist", False):
        return {}

    session = configurable.get("session")
    owns_session = session is None
    session = session or SessionLocal()
    try:
        session.add(build_decision_log(state))
        if "next_state" in state:
            account_state = session.get(AccountState, state["invoice_id"])
            for key, value in build_account_state_updates(state).items():
                setattr(account_state, key, value)
        if owns_session:
            session.commit()
    finally:
        if owns_session:
            session.close()
    return {}
