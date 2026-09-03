from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import ArchetypeDiagnosticRow, AttributionResponse, AttributionSliceOut, CupedMetricOut
from app.attribution.config import EXPERIMENT_ID
from app.attribution.cuped import compute_pooled_cuped
from app.attribution.evaluate import (
    check_aggregation_consistency,
    compute_slice,
    diagnostic_action_by_archetype,
    load_attribution_data,
)
from app.models import AttributionExperimentResult

router = APIRouter(prefix="/api/attribution", tags=["attribution"])


def _to_slice_out(r: AttributionExperimentResult) -> AttributionSliceOut:
    return AttributionSliceOut(
        segment=r.segment,
        action=r.action.value if r.action else None,
        treatment_n=r.treatment_n,
        control_n=r.control_n,
        treatment_recovery_rate=r.treatment_recovery_rate,
        control_recovery_rate=r.control_recovery_rate,
        incremental_recovery_rate=r.incremental_recovery_rate,
        treatment_recovered_amount=float(r.treatment_recovered_amount),
        control_recovered_amount=float(r.control_recovered_amount),
        incremental_recovered_amount=float(r.incremental_recovered_amount),
        treatment_cost=float(r.treatment_cost),
        treatment_friction=float(r.treatment_friction),
        incremental_net_recovery=float(r.incremental_net_recovery),
        recovery_rate_diff_z=r.recovery_rate_diff_z,
        treatment_count_recovery_rate=r.treatment_count_recovery_rate,
        control_count_recovery_rate=r.control_count_recovery_rate,
    )


@router.get("", response_model=AttributionResponse)
def get_attribution(
    db: Annotated[Session, Depends(get_db)],
    include_diagnostics: bool = Query(
        default=False,
        description="Include hidden-ground-truth diagnostics (archetype breakdown, "
        "aggregation-consistency warnings) -- verification-only content, gated by default.",
    ),
    include_cuped: bool = Query(
        default=False,
        description="Include CUPED-adjusted pooled figures (count-based and average-"
        "recovered-amount-per-invoice) alongside the raw ones -- computed on demand, "
        "never persisted, never replaces the raw estimate. See app/attribution/cuped.py.",
    ),
):
    rows = (
        db.execute(select(AttributionExperimentResult).where(AttributionExperimentResult.experiment_id == EXPERIMENT_ID))
        .scalars()
        .all()
    )
    slices = [_to_slice_out(r) for r in rows]

    escalate_by_archetype = None
    consistency_warnings = None
    cuped = None

    if include_cuped:
        df = load_attribution_data(db.get_bind())
        count_result, amount_result = compute_pooled_cuped(df)
        cuped = [
            CupedMetricOut(
                metric=r.metric,
                treatment_n=r.treatment_n,
                control_n=r.control_n,
                raw_effect=r.raw_effect,
                raw_se=r.raw_se,
                cuped_effect=r.cuped_effect,
                cuped_se=r.cuped_se,
                se_reduction_pct=r.se_reduction_pct,
                theta=r.theta,
                corr=r.corr,
            )
            for r in (count_result, amount_result)
        ]

    if include_diagnostics:
        df = load_attribution_data(db.get_bind())

        archetype_df = diagnostic_action_by_archetype(df, "escalate")
        # Explicit Python-native casts -- pandas' numpy scalar types
        # (int64/float64) aren't guaranteed to coerce cleanly through
        # Pydantic v2's validation in every version, so don't rely on it.
        escalate_by_archetype = [
            ArchetypeDiagnosticRow(
                archetype=str(row["archetype"]),
                treatment_n=int(row["treatment_n"]),
                control_n=int(row["control_n"]),
                treatment_recovery_rate=float(row["treatment_recovery_rate"]),
                control_recovery_rate=float(row["control_recovery_rate"]),
                incremental_recovery_rate=float(row["incremental_recovery_rate"]),
                incremental_recovered_amount=float(row["incremental_recovered_amount"]),
                recovery_rate_diff_z=float(row["recovery_rate_diff_z"]) if row["recovery_rate_diff_z"] is not None else None,
            )
            for row in archetype_df.to_dict(orient="records")
        ]

        warnings: list[str] = []
        for r in rows:
            if r.segment is not None or r.action is None:
                continue
            action_value = r.action.value
            pooled_slice = compute_slice(df, segment=None, action=action_value)
            by_archetype = diagnostic_action_by_archetype(df, action_value)
            stratified = [
                compute_slice(df[df["archetype"] == arch], segment=None, action=action_value)
                for arch in by_archetype["archetype"]
            ]
            warning = check_aggregation_consistency(pooled_slice, stratified, action_value)
            if warning:
                warnings.append(warning)
        consistency_warnings = warnings or None

    # Built explicitly rather than via response_model_exclude_none=True:
    # that flag strips None RECURSIVELY, which would also strip the
    # legitimate segment=None/action=None on pooled/segment/action rows
    # (None there means "pooled", not "field is absent") -- caught by
    # test_get_attribution_slices_include_the_portfolio_row. Only the two
    # top-level diagnostic fields should ever be conditionally omitted.
    payload: dict = {
        "experiment_id": EXPERIMENT_ID,
        "slices": [s.model_dump() for s in slices],
    }
    if escalate_by_archetype is not None:
        payload["escalate_by_archetype"] = [r.model_dump() for r in escalate_by_archetype]
    if consistency_warnings is not None:
        payload["consistency_warnings"] = consistency_warnings
    if cuped is not None:
        payload["cuped"] = [c.model_dump() for c in cuped]
    return JSONResponse(content=payload)
