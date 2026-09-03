"""Persist a fresh baseline-vs-engine EvaluationSnapshot -- the read side of
the Day 6 metrics-staleness bug (see app/models/evaluation_snapshot.py's
docstring and docs/api-DECISIONS.md for the full story). Re-run this whenever
the live pool composition or the economics config changes; GET /api/metrics
only ever reads the latest persisted snapshot, it never recomputes.

    python -m app.decision.persist_evaluation
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.decision.evaluation import (
    EvaluationSummary,
    baseline_outcomes,
    engine_outcomes,
    summarize_strategy,
    unnecessary_interventions_avoided,
)
from app.decision.service import run_full_live_pass
from app.models import EvaluationSnapshot


def _upsert(db: Session, summary: EvaluationSummary, avoided: int) -> None:
    row = db.get(EvaluationSnapshot, summary.strategy_name)
    if row is None:
        row = EvaluationSnapshot(strategy_name=summary.strategy_name)
        db.add(row)
    row.n_invoices = summary.n_invoices
    row.n_interventions = summary.n_interventions
    row.n_wait = summary.n_wait
    row.n_stop = summary.n_stop
    row.total_amount = Decimal(str(summary.total_amount))
    row.gross_expected_recovered = Decimal(str(summary.gross_expected_recovered))
    row.total_cost = Decimal(str(summary.total_cost))
    row.total_friction = Decimal(str(summary.total_friction))
    row.net_expected_recovered = Decimal(str(summary.net_expected_recovered))
    row.recovery_rate = summary.recovery_rate
    row.unnecessary_interventions_avoided = avoided


def persist_evaluation_snapshot() -> tuple[EvaluationSummary, EvaluationSummary]:
    decisions = run_full_live_pass()
    baseline = summarize_strategy("Baseline (email everyone)", baseline_outcomes(decisions))
    engine = summarize_strategy("Decision engine", engine_outcomes(decisions))
    avoided = unnecessary_interventions_avoided(baseline, engine)

    db = SessionLocal()
    try:
        _upsert(db, baseline, avoided)
        _upsert(db, engine, avoided)
        db.commit()
    finally:
        db.close()
    return baseline, engine


if __name__ == "__main__":
    baseline, engine = persist_evaluation_snapshot()
    print(f"Persisted baseline: n={baseline.n_invoices} net=Rs.{baseline.net_expected_recovered:,.0f}")
    print(f"Persisted engine:   n={engine.n_invoices} net=Rs.{engine.net_expected_recovered:,.0f}")
    print(f"Net improvement: Rs.{engine.net_expected_recovered - baseline.net_expected_recovered:,.0f}")
