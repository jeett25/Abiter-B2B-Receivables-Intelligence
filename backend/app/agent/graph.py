
from __future__ import annotations

import uuid

from langgraph.graph import END, START, StateGraph

from app.agent.events import Event, EventType
from app.agent.nodes import (
    build_features,
    dispatch_action,
    extract_promise_node,
    finalize_decision,
    ingest_event,
    load_context,
    retrieve_cases,
    run_economics,
    run_policy,
    score_ml,
    score_ptp,
    update_account_state,
    write_audit,
)
from app.agent.state import GraphState

_compiled_graph = None


def _route_after_ingest(state: GraphState) -> str:
    if state.get("error"):
        return "AUDIT"
    if state["event"].event_type == EventType.CUSTOMER_RESPONDED:
        return "EXTRACT_PROMISE"
    return "LOAD_CONTEXT"


def _route_after_load_context(state: GraphState) -> str:
    return "SCORE_PTP" if state["event"].event_type == EventType.PROMISE_CREATED else "BUILD_FEATURES"


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("INGEST_EVENT", ingest_event)
    graph.add_node("EXTRACT_PROMISE", extract_promise_node)
    graph.add_node("LOAD_CONTEXT", load_context)
    graph.add_node("SCORE_PTP", score_ptp)
    graph.add_node("BUILD_FEATURES", build_features)
    graph.add_node("ML_SCORING", score_ml)
    graph.add_node("RETRIEVE_CASES", retrieve_cases)
    graph.add_node("ECONOMICS", run_economics)
    graph.add_node("POLICY", run_policy)
    graph.add_node("DECISION", finalize_decision)
    graph.add_node("ACTION", dispatch_action)
    graph.add_node("UPDATE_STATE", update_account_state)
    graph.add_node("AUDIT", write_audit)

    graph.add_edge(START, "INGEST_EVENT")
    graph.add_conditional_edges(
        "INGEST_EVENT",
        _route_after_ingest,
        {"AUDIT": "AUDIT", "EXTRACT_PROMISE": "EXTRACT_PROMISE", "LOAD_CONTEXT": "LOAD_CONTEXT"},
    )
    graph.add_edge("EXTRACT_PROMISE", "LOAD_CONTEXT")
    graph.add_conditional_edges(
        "LOAD_CONTEXT", _route_after_load_context, {"SCORE_PTP": "SCORE_PTP", "BUILD_FEATURES": "BUILD_FEATURES"}
    )
    graph.add_edge("SCORE_PTP", "UPDATE_STATE")
    graph.add_edge("BUILD_FEATURES", "ML_SCORING")
    graph.add_edge("ML_SCORING", "RETRIEVE_CASES")
    graph.add_edge("RETRIEVE_CASES", "ECONOMICS")
    graph.add_edge("ECONOMICS", "POLICY")
    graph.add_edge("POLICY", "DECISION")
    graph.add_edge("DECISION", "ACTION")
    graph.add_edge("ACTION", "UPDATE_STATE")
    graph.add_edge("UPDATE_STATE", "AUDIT")
    graph.add_edge("AUDIT", END)

    return graph.compile()


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def run_invoice(
    invoice_id: uuid.UUID, event: Event | None = None, config: dict | None = None, persist: bool = False
) -> GraphState:
    if event is None:
        from app.decision.service import DEFAULT_AS_OF

        event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DEFAULT_AS_OF)

    config = dict(config or {})
    configurable = dict(config.get("configurable", {}))
    configurable.setdefault("persist", persist)
    config["configurable"] = configurable

    initial_state: GraphState = {"invoice_id": invoice_id, "event": event}
    return get_graph().invoke(initial_state, config=config)


if __name__ == "__main__":
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import Invoice
    from app.models.enums import InvoiceStatus

    session = SessionLocal()
    try:
        sample_id = session.execute(select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN).limit(1)).scalar_one()
    finally:
        session.close()

    result = run_invoice(sample_id)
    print(f"invoice_id: {result['invoice_id']}")
    print(f"recovery_probability: {result['recovery_probability']:.4f}")
    print(f"proposed_action: {result['proposed_action'].value}")
    print(f"policy_verdict: {result['policy_verdict'].result.value} -- {result['policy_verdict'].reason}")
    print(f"selected_action: {result['selected_action'].value}")
    print(f"next_state: {result['next_state'].value}")
    print(f"tool_result: {result['tool_result']}")
