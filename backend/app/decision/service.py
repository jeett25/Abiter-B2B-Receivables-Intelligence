from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy.engine import Engine

from app.decision.economics import ActionEV, rank_actions, recommend_action
from app.decision.policy import (
    IST,
    PolicyContext,
    PolicyVerdict,
    detect_already_paid,
    detect_dispute,
    evaluate_policy,
)
from app.ml.features import build_live_feature_table, load_raw_tables
from app.ml.persist import load_model
from app.ml.train_recovery import calibrated_predict_proba
from app.models.enums import ActionType
from app.retrieval.hybrid_search import RetrievedCase, build_query_text, hybrid_retrieve
DEFAULT_AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=IST)

RETRIEVAL_TOP_K = 5

_recovery_model = None
_recovery_calibrator = None


def _get_recovery_model():
    global _recovery_model
    if _recovery_model is None:
        _recovery_model = load_model("recovery_model")
    return _recovery_model


def _get_recovery_calibrator():
    global _recovery_calibrator
    if _recovery_calibrator is None:
        _recovery_calibrator = load_model("recovery_calibrator")
    return _recovery_calibrator


def score_recovery_probability(feature_row: pd.Series) -> float:
    """Single-row scoring through the exact same calibrated_predict_proba()
    Day 2 built. Empirically confirmed safe against a single-row categorical
    dtype (XGBoost matches segment/industry categories by value, not code
    position -- verified directly against the trained model before writing
    this, not assumed)."""
    df = pd.DataFrame([feature_row])
    proba = calibrated_predict_proba(_get_recovery_model(), _get_recovery_calibrator(), df)
    return float(proba[0])


@dataclass(frozen=True)
class Decision:
    invoice_id: object
    base_probability: float
    amount: float
    is_disputed: bool
    is_actually_paid: bool
    economics_ranking: list[ActionEV]
    proposed_action: ActionType
    retrieved_cases: list[RetrievedCase]
    policy_verdict: PolicyVerdict
    final_action: ActionType


def _to_naive(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def decide_from_feature_row(feature_row: pd.Series, tables: dict, as_of: datetime = DEFAULT_AS_OF) -> Decision:
    """Pure(ish) orchestration given an already-computed live feature row and
    already-loaded raw tables -- the batch-friendly path, used by both
    decide() (loads everything fresh, for one-off use) and
    run_full_live_pass() (loads once, reused across all 900 invoices)."""
    invoice_id = feature_row["invoice_id"]
    amount = float(feature_row["amount"])
    base_probability = score_recovery_probability(feature_row)

    invoices = tables["invoices"]
    payments = tables["payments"]
    actions = tables["actions"]

    invoice_row = invoices[invoices["id"] == invoice_id].iloc[0]
    is_disputed = detect_dispute(invoice_row["true_root_cause"])

    as_of_naive = _to_naive(as_of)

    invoice_payments = payments[payments["invoice_id"] == invoice_id]
    completed_total = float(invoice_payments[invoice_payments["payment_date"] <= as_of_naive]["amount"].sum())
    is_actually_paid = detect_already_paid(amount, completed_total)

    own_actions = actions[actions["invoice_id"] == invoice_id]
    prior_contact_count = len(own_actions)
    days_since_last_contact = (
        (as_of_naive - own_actions["timestamp"].max()).days if prior_contact_count > 0 else None
    )

    days_overdue = (as_of_naive - feature_row["due_date"]).days
    query_text = build_query_text(
        amount=amount,
        payment_term_days=int(feature_row["payment_term_days"]),
        segment=feature_row["customer_segment"],
        industry=feature_row["customer_industry"],
        prior_payment_rate=feature_row["prior_payment_rate"] if pd.notna(feature_row["prior_payment_rate"]) else None,
        days_overdue=days_overdue,
    )
    retrieved_cases = hybrid_retrieve(
        query_text=query_text,
        query_amount=amount,
        segment=feature_row["customer_segment"],
        industry=feature_row["customer_industry"],
        is_disputed=is_disputed,
        top_k=RETRIEVAL_TOP_K,
    )

    ranking = rank_actions(base_probability, amount, prior_contact_count=prior_contact_count, is_disputed=is_disputed)
    proposed = recommend_action(
        base_probability, amount, prior_contact_count=prior_contact_count, is_disputed=is_disputed
    )

    context = PolicyContext(
        proposed_action=proposed.action_type,
        base_probability=base_probability,
        amount=amount,
        is_actually_paid=is_actually_paid,
        is_disputed=is_disputed,
        prior_contact_count=prior_contact_count,
        days_since_last_contact=days_since_last_contact,
        now=as_of,
    )
    verdict = evaluate_policy(context)

    return Decision(
        invoice_id=invoice_id,
        base_probability=base_probability,
        amount=amount,
        is_disputed=is_disputed,
        is_actually_paid=is_actually_paid,
        economics_ranking=ranking,
        proposed_action=proposed.action_type,
        retrieved_cases=retrieved_cases,
        policy_verdict=verdict,
        final_action=verdict.final_action,
    )


def decide(invoice_id, as_of: datetime = DEFAULT_AS_OF, engine: Engine | None = None) -> Decision:
    """One-off convenience path -- loads everything fresh. Use
    run_full_live_pass() for the batch pass; it loads tables/features once
    instead of once per invoice."""
    tables = load_raw_tables(engine)
    live_table = build_live_feature_table(engine)
    feature_row = live_table[live_table["invoice_id"] == invoice_id].iloc[0]
    return decide_from_feature_row(feature_row, tables, as_of)


def run_full_live_pass(
    as_of: datetime = DEFAULT_AS_OF, engine: Engine | None = None, limit: int | None = None
) -> list[Decision]:
    """limit is a testing convenience (score only the first N live invoices)
    -- the actual "full 900" pass is the default (limit=None), exercised as
    a deliverable in subtask 9's final integration pass, not gated on every
    test run here given its multi-minute cost (retrieval embeds a query per
    invoice)."""
    tables = load_raw_tables(engine)
    live_table = build_live_feature_table(engine)
    if limit is not None:
        live_table = live_table.head(limit)
    return [decide_from_feature_row(row, tables, as_of) for _, row in live_table.iterrows()]


def _summarize(decisions: list[Decision]) -> None:
    from collections import Counter

    action_counts = Counter(d.final_action.value for d in decisions)
    result_counts = Counter(d.policy_verdict.result.value for d in decisions)

    print(f"Decisions: {len(decisions)}")
    print("\nFinal action distribution:")
    for action, count in sorted(action_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {action:<14} {count:>4}  ({count / len(decisions):.1%})")
    print("\nPolicy result distribution:")
    for result, count in sorted(result_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {result:<12} {count:>4}  ({count / len(decisions):.1%})")


if __name__ == "__main__":
    decisions = run_full_live_pass()
    _summarize(decisions)
