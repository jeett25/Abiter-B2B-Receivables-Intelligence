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


class ArchetypeDiagnosticRow(BaseModel):
    archetype: str
    treatment_n: int
    control_n: int
    treatment_recovery_rate: float
    control_recovery_rate: float
    incremental_recovery_rate: float
    incremental_recovered_amount: float
    recovery_rate_diff_z: float | None


class AttributionResponse(BaseModel):
    experiment_id: str
    slices: list[AttributionSliceOut]
    # Both None unless include_diagnostics=true was passed -- hidden
    # ground-truth-informed content, gated deliberately (not just labeled).
    # See app/api/DECISIONS.md.
    escalate_by_archetype: list[ArchetypeDiagnosticRow] | None = None
    consistency_warnings: list[str] | None = None
