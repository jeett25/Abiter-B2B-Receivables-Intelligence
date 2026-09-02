from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import AttributionHeadline, EvaluationSummary, MetricsResponse
from app.models import AttributionExperimentResult, EvaluationSnapshot

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _to_schema(row: EvaluationSnapshot) -> EvaluationSummary:
    return EvaluationSummary(
        strategy_name=row.strategy_name,
        n_invoices=row.n_invoices,
        n_interventions=row.n_interventions,
        n_wait=row.n_wait,
        n_stop=row.n_stop,
        total_amount=float(row.total_amount),
        gross_expected_recovered=float(row.gross_expected_recovered),
        total_cost=float(row.total_cost),
        total_friction=float(row.total_friction),
        net_expected_recovered=float(row.net_expected_recovered),
        recovery_rate=row.recovery_rate,
    )


@router.get("", response_model=MetricsResponse)
def get_metrics(db: Annotated[Session, Depends(get_db)]):
    # Reads a PRECOMPUTED snapshot (python -m app.decision.persist_evaluation)
    # rather than deriving baseline-vs-engine from raw account_state at
    # request time. See app/models/evaluation_snapshot.py's docstring: the
    # prior approach recomputed today's economics against each invoice's
    # stale, possibly pre-correction persisted next_action, which produced
    # an internally-inconsistent (and once, falsely negative) comparison. A
    # fresh, self-consistent run takes ~55s -- too slow for a page load, so
    # it's precomputed instead, same operational pattern as
    # attribution_experiment_results.
    baseline_row = db.get(EvaluationSnapshot, "Baseline (email everyone)")
    engine_row = db.get(EvaluationSnapshot, "Decision engine")
    if baseline_row is None or engine_row is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation snapshot not yet computed -- run `python -m app.decision.persist_evaluation`.",
        )

    baseline_summary = _to_schema(baseline_row)
    engine_summary = _to_schema(engine_row)
    avoided = engine_row.unnecessary_interventions_avoided

    pooled = (
        db.execute(
            select(AttributionExperimentResult).where(
                AttributionExperimentResult.segment.is_(None),
                AttributionExperimentResult.action.is_(None),
            )
        )
        .scalars()
        .first()
    )

    attribution = None
    if pooled is not None:
        attribution = AttributionHeadline(
            treatment_n=pooled.treatment_n,
            control_n=pooled.control_n,
            treatment_recovery_rate=pooled.treatment_recovery_rate,
            control_recovery_rate=pooled.control_recovery_rate,
            incremental_recovery_rate=pooled.incremental_recovery_rate,
            treatment_recovered_amount=float(pooled.treatment_recovered_amount),
            control_recovered_amount=float(pooled.control_recovered_amount),
            incremental_recovered_amount=float(pooled.incremental_recovered_amount),
            treatment_cost=float(pooled.treatment_cost),
            treatment_friction=float(pooled.treatment_friction),
            incremental_net_recovery=float(pooled.incremental_net_recovery),
            treatment_count_recovery_rate=pooled.treatment_count_recovery_rate,
            control_count_recovery_rate=pooled.control_count_recovery_rate,
        )

    return MetricsResponse(
        baseline=baseline_summary,
        engine=engine_summary,
        unnecessary_interventions_avoided=avoided,
        attribution=attribution,
    )
