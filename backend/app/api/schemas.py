"""Pydantic response models for the dashboard API.

These ARE the source of truth for what this API actually returns -- NOT
frontend/lib/types.ts, which still reflects a pre-Day-4 shape for
DecisionTrace.policy_checks (final_action/result, no
state_transition_path/retry_count/tool_result). See app/api/DECISIONS.md
for the full explanation; Day 6's frontend-wiring pass reconciles
types.ts against this file, not the other way around.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class InvoiceSummary(BaseModel):
    invoice_id: UUID
    invoice_number: str
    customer_name: str
    amount: float
    due_date: date
    current_state: str
    recoverability_score: float
    next_action: str | None
    treatment_group: str | None = None


class DecisionTrace(BaseModel):
    invoice_id: UUID
    invoice_number: str
    customer_name: str
    amount: float
    decision: str
    # Real, raw decision_logs JSONB -- deliberately dict[str, Any], not a
    # strict sub-schema, so this never silently drops or renames a field
    # the audit trail actually wrote. See module docstring.
    model_scores: dict[str, Any]
    evidence: dict[str, Any]
    policy_checks: dict[str, Any]
    reason: str
    timestamp: datetime
    # Set only when model_scores/evidence above were pulled from an EARLIER
    # decision_logs row than `timestamp` -- see get_decision()'s fallback
    # merge for invoices whose latest row is a bare closing entry (e.g.
    # app/attribution/persist.py's build_closing_decision_log(), which
    # deliberately has no fresh model_scores of its own). None means
    # model_scores/evidence are from the same row as decision/reason/timestamp.
    assessed_at: datetime | None = None


class TimelineEntry(BaseModel):
    timestamp: datetime
    type: str  # "decision" | "payment"
    summary: str
    detail: dict[str, Any]


class InvoiceTimeline(BaseModel):
    invoice_id: UUID
    events: list[TimelineEntry]


class EvaluationSummary(BaseModel):
    strategy_name: str
    n_invoices: int
    n_interventions: int
    n_wait: int
    n_stop: int
    total_amount: float
    gross_expected_recovered: float
    total_cost: float
    total_friction: float
    net_expected_recovered: float
    recovery_rate: float


class AttributionHeadline(BaseModel):
    treatment_n: int
    control_n: int
    treatment_recovery_rate: float
    control_recovery_rate: float
    incremental_recovery_rate: float
    treatment_recovered_amount: float
    control_recovered_amount: float
    incremental_recovered_amount: float
    treatment_cost: float
    treatment_friction: float
    incremental_net_recovery: float
    # COUNT-based (fraction of invoices recovered), distinct from the
    # amount-weighted rates above -- this is the metric recovery_rate_diff_z
    # is actually computed on (see app/attribution/DECISIONS.md: "built on
    # the COUNT-based rate, never the amount-weighted one"). The
    # amount-weighted rate has no valid standard error at this sample size;
    # exposing this lets the frontend show the number its own significance
    # test is actually about, instead of only the noisier one.
    treatment_count_recovery_rate: float | None = None
    control_count_recovery_rate: float | None = None


class MetricsResponse(BaseModel):
    baseline: EvaluationSummary
    engine: EvaluationSummary
    unnecessary_interventions_avoided: int
    # None only if the Day-5 attribution pass hasn't been run/persisted yet
    # -- never fabricated.
    attribution: AttributionHeadline | None


class AttributionSliceOut(BaseModel):
    segment: str | None
    action: str | None
    treatment_n: int
    control_n: int
    treatment_recovery_rate: float
    control_recovery_rate: float
    incremental_recovery_rate: float
    treatment_recovered_amount: float
    control_recovered_amount: float
    incremental_recovered_amount: float
    treatment_cost: float
    treatment_friction: float
    incremental_net_recovery: float
    recovery_rate_diff_z: float | None
    # See AttributionHeadline above -- same count-vs-amount-weighted split.
    treatment_count_recovery_rate: float | None = None
    control_count_recovery_rate: float | None = None


class ArchetypeDiagnosticRow(BaseModel):
    archetype: str
    treatment_n: int
    control_n: int
    treatment_recovery_rate: float
    control_recovery_rate: float
    incremental_recovery_rate: float
    incremental_recovered_amount: float
    recovery_rate_diff_z: float | None


class CupedMetricOut(BaseModel):
    """CUPED-adjusted pooled figure, alongside the raw one it's derived
    from -- never a replacement. 'count' matches evaluate.py's own
    count-based recovery rate exactly (the statistically-tested metric --
    see app/attribution/DECISIONS.md); 'amount' is the average recovered
    amount PER INVOICE, a related but distinct statistic from the
    ratio-of-sums 'amount-weighted recovery rate' shown elsewhere -- see
    app/attribution/cuped.py's module docstring."""

    metric: str
    treatment_n: int
    control_n: int
    raw_effect: float
    raw_se: float | None
    cuped_effect: float
    cuped_se: float | None
    se_reduction_pct: float | None
    theta: float
    corr: float


class AttributionResponse(BaseModel):
    experiment_id: str
    slices: list[AttributionSliceOut]
    # Both None unless include_diagnostics=true was passed -- hidden
    # ground-truth-informed content, gated deliberately (not just labeled).
    # See app/api/DECISIONS.md.
    escalate_by_archetype: list[ArchetypeDiagnosticRow] | None = None
    consistency_warnings: list[str] | None = None
    # None unless include_cuped=true. Pooled-only (portfolio headline), not
    # gated by hidden ground truth -- see app/attribution/cuped.py.
    cuped: list[CupedMetricOut] | None = None
