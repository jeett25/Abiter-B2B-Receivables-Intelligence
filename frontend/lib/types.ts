// Mirrors backend/app/api/schemas.py -- the REAL source of truth for what
// the API returns (see backend/app/api/DECISIONS.md: schemas.py, not this
// file, is authoritative for DecisionTrace's nested shapes). ActionEV/
// RetrievedCase additionally trace back to app/decision/economics.py and
// app/retrieval/hybrid_search.py, and enum string values to
// app/models/enums.py directly.

export type ActionType =
  | "wait"
  | "email"
  | "whatsapp"
  | "payment_link"
  | "voice"
  | "escalate"
  | "stop";

export type PolicyResult = "allowed" | "blocked" | "escalated";

export type AccountCurrentState =
  | "overdue"
  | "assessment"
  | "wait"
  | "remind"
  | "escalate"
  | "promise"
  | "monitoring"
  | "kept"
  | "broken"
  | "reassess"
  | "closed"
  | "closed_paid"
  | "closed_abandoned"
  | "dispute_review";

export type TreatmentGroup = "acted" | "control";

// app/decision/economics.py::ActionEV, via _action_ev_to_dict
export interface ActionEV {
  action_type: ActionType;
  probability: number;
  cost: number;
  friction: number;
  expected_value: number;
}

// app/retrieval/hybrid_search.py::RetrievedCase, trimmed by
// _retrieved_case_to_dict to just the 4 fields actually persisted.
export interface RetrievedCase {
  invoice_id: string;
  case_text: string;
  status: string;
  rrf_score: number;
}

// app/api/schemas.py::InvoiceSummary
export interface InvoiceSummary {
  invoice_id: string;
  invoice_number: string;
  customer_name: string;
  amount: number;
  due_date: string;
  current_state: AccountCurrentState;
  recoverability_score: number;
  // Nullable on the wire (Pydantic includes the field even when None).
  next_action: ActionType | null;
  // Null for every invoice outside Day 5's attribution experiment population.
  treatment_group: TreatmentGroup | null;
}

// app/agent/audit.py::_build_model_scores -- the real, dominant shape
// written for virtually every decision_logs row (the live 900-invoice pass
// + all demo scenarios). candidate_actions is only present when the round
// actually ran economics (absent on a promise-creation-only round).
export interface ModelScores {
  recovery_probability: number | null;
  ptp_probability: number | null;
  candidate_actions?: ActionEV[];
}

// app/agent/tools.py::_tool_result / ToolResult (app/agent/state.py) -- the
// shape every simulated/real action-dispatch tool returns.
export interface ToolResult {
  success: boolean;
  action: string;
  external_id: string | null;
  message: string;
  timestamp: string;
}

// app/agent/audit.py::_build_evidence. trigger_event is unconditionally set
// on every real row; optional here only so pre-Day-6 mock fixtures without
// one still typecheck.
export interface Evidence {
  trigger_event?: {
    event_type: string;
    payload: Record<string, unknown>;
  };
  retrieved_cases?: RetrievedCase[];
}

// app/agent/audit.py::_build_policy_checks -- the real shape for virtually
// every row (the live 900-invoice pass + all demo scenarios).
// proposed_action/selected_action/policy_result/tool_result are each only
// present when that GraphState shape actually populated them (see
// audit.py's module docstring: normal / promise-creation / invalid-event
// shapes).
//
// final_action/result (NOT selected_action/policy_result) are the OLDER
// shape written by app/decision/persist.py -- as of Day 5, only ever hit by
// the one test-seeded already_paid_false_alarm invoice from Day 3. Kept
// here, marked legacy, rather than silently dropped: schemas.py returns raw
// JSONB, so this key really can appear on the wire.
export interface PolicyChecks {
  is_disputed: boolean | null;
  is_actually_paid: boolean | null;
  state_transition_path?: string[];
  retry_count?: number | null;
  error?: string | null;
  proposed_action?: ActionType;
  selected_action?: ActionType;
  policy_result?: PolicyResult;
  tool_result?: ToolResult | null;
  /** @deprecated Day-3-only legacy key, see app/decision/persist.py */
  final_action?: ActionType;
  /** @deprecated Day-3-only legacy key, see app/decision/persist.py */
  result?: PolicyResult;
}

// app/api/schemas.py::DecisionTrace. model_scores/evidence/policy_checks are
// dict[str, Any] on the wire -- schemas.py deliberately never narrows them
// (see app/api/DECISIONS.md) so the backend can't silently drop a field the
// audit trail actually wrote. The interfaces above describe what's actually
// written today, not a contract the backend validates against -- treat every
// field on ModelScores/Evidence/PolicyChecks as possibly absent in practice.
export interface DecisionTrace {
  invoice_id: string;
  invoice_number: string;
  customer_name: string;
  amount: number;
  decision: string;
  model_scores: ModelScores;
  evidence: Evidence;
  policy_checks: PolicyChecks;
  reason: string;
  timestamp: string;
}

// app/api/schemas.py::TimelineEntry
export interface TimelineEntry {
  timestamp: string;
  type: "decision" | "payment";
  summary: string;
  detail: Record<string, unknown>;
}

// app/api/schemas.py::InvoiceTimeline
export interface InvoiceTimeline {
  invoice_id: string;
  events: TimelineEntry[];
}

// app/api/schemas.py::EvaluationSummary
export interface EvaluationSummary {
  strategy_name: string;
  n_invoices: number;
  n_interventions: number;
  n_wait: number;
  n_stop: number;
  total_amount: number;
  gross_expected_recovered: number;
  total_cost: number;
  total_friction: number;
  net_expected_recovered: number;
  recovery_rate: number;
}

// app/api/schemas.py::AttributionHeadline -- the pooled (segment=null,
// action=null) row of the attribution experiment, flattened for the metrics
// screen.
export interface AttributionHeadline {
  treatment_n: number;
  control_n: number;
  treatment_recovery_rate: number;
  control_recovery_rate: number;
  incremental_recovery_rate: number;
  treatment_recovered_amount: number;
  control_recovered_amount: number;
  incremental_recovered_amount: number;
  treatment_cost: number;
  treatment_friction: number;
  incremental_net_recovery: number;
  // COUNT-based (fraction of invoices recovered) -- distinct from the
  // amount-weighted rates above, and the metric the z-score is actually
  // computed on (app/attribution/DECISIONS.md). Null only if the backend
  // hasn't recomputed this slice since this field was added.
  treatment_count_recovery_rate: number | null;
  control_count_recovery_rate: number | null;
}

// app/api/schemas.py::MetricsResponse
export interface MetricsResponse {
  baseline: EvaluationSummary;
  engine: EvaluationSummary;
  unnecessary_interventions_avoided: number;
  // Null only if Day-5's attribution pass hasn't been run/persisted yet --
  // never fabricated by the backend.
  attribution: AttributionHeadline | null;
}

// app/api/schemas.py::AttributionSliceOut -- one row of the
// (segment, action) cube. segment=null means pooled across segments,
// action=null means pooled across actions; (null, null) is the portfolio
// headline row -- null here is a real, meaningful value, never "absent".
export interface AttributionSliceOut {
  segment: string | null;
  action: ActionType | null;
  treatment_n: number;
  control_n: number;
  treatment_recovery_rate: number;
  control_recovery_rate: number;
  incremental_recovery_rate: number;
  treatment_recovered_amount: number;
  control_recovered_amount: number;
  incremental_recovered_amount: number;
  treatment_cost: number;
  treatment_friction: number;
  incremental_net_recovery: number;
  recovery_rate_diff_z: number | null;
  // Same count-vs-amount-weighted split as AttributionHeadline above.
  treatment_count_recovery_rate: number | null;
  control_count_recovery_rate: number | null;
}

// app/api/schemas.py::ArchetypeDiagnosticRow -- hidden-ground-truth
// diagnostic, only present when include_diagnostics=true. See
// app/attribution/DECISIONS.md: archetype has no real-world analogue --
// never surface this on a production-facing screen, verification/dev use only.
export interface ArchetypeDiagnosticRow {
  archetype: string;
  treatment_n: number;
  control_n: number;
  treatment_recovery_rate: number;
  control_recovery_rate: number;
  incremental_recovery_rate: number;
  incremental_recovered_amount: number;
  recovery_rate_diff_z: number | null;
}

// app/api/schemas.py::AttributionResponse
export interface AttributionResponse {
  experiment_id: string;
  slices: AttributionSliceOut[];
  // Both undefined unless include_diagnostics=true was passed -- gated
  // deliberately (see app/api/DECISIONS.md): absent from the JSON entirely,
  // not present-but-null.
  escalate_by_archetype?: ArchetypeDiagnosticRow[];
  consistency_warnings?: string[];
}

// app/api/routes/demo.py::DemoFixtureOut -- one of the 6 curated demo
// invoices from synthetic/demo_fixtures.json, resolved to a real invoice_id.
export interface DemoFixture {
  key: string;
  label: string;
  invoice_number: string;
  invoice_id: string;
  expected_action: string;
}
