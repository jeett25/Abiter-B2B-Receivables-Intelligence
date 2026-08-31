from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import AttributionHeadline, EvaluationSummary, MetricsResponse
from app.decision.evaluation import (
    StrategyOutcome,
    summarize_strategy,
    unnecessary_interventions_avoided,
)
from app.models import AccountState, AttributionExperimentResult, DecisionLog, Invoice
from app.models.enums import ActionType

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _live_pool_outcomes(db: Session) -> list[StrategyOutcome]:
    """Built ENTIRELY from persisted account_state/invoices -- no ML scoring
    or retrieval call happens here. See app/api/DECISIONS.md for why this
    is the deliberate resolution of "don't re-run the models"."""
    rows = db.execute(
        select(Invoice.id, Invoice.amount, AccountState.recoverability_score, AccountState.next_action)
        .join(AccountState, AccountState.invoice_id == Invoice.id)
        .where(exists().where(DecisionLog.invoice_id == Invoice.id))
    ).all()
    return [
        StrategyOutcome(
            invoice_id=r.id,
            action=r.next_action or ActionType.WAIT,
            base_probability=r.recoverability_score,
            amount=float(r.amount),
        )
        for r in rows
    ]


def _to_schema(s) -> EvaluationSummary:
    return EvaluationSummary(
        strategy_name=s.strategy_name,
        n_invoices=s.n_invoices,
        n_interventions=s.n_interventions,
        n_wait=s.n_wait,
        n_stop=s.n_stop,
        total_amount=s.total_amount,
        gross_expected_recovered=s.gross_expected_recovered,
        total_cost=s.total_cost,
        total_friction=s.total_friction,
        net_expected_recovered=s.net_expected_recovered,
        recovery_rate=s.recovery_rate,
    )


@router.get("", response_model=MetricsResponse)
def get_metrics(db: Annotated[Session, Depends(get_db)]):
    engine_list = _live_pool_outcomes(db)
    baseline_list = [
        StrategyOutcome(o.invoice_id, ActionType.EMAIL, o.base_probability, o.amount) for o in engine_list
    ]

    baseline_summary = summarize_strategy("Baseline (email everyone)", baseline_list)
    engine_summary = summarize_strategy("Decision engine", engine_list)
    avoided = unnecessary_interventions_avoided(baseline_summary, engine_summary)

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
        )

    return MetricsResponse(
        baseline=_to_schema(baseline_summary),
        engine=_to_schema(engine_summary),
        unnecessary_interventions_avoided=avoided,
        attribution=attribution,
    )
