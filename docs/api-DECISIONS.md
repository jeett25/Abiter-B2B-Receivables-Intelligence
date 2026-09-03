# Dashboard API (app/api/) decisions

Running log, same convention as app/ml/, app/agent/, and app/attribution/'s
DECISIONS.md files -- entries appended, not rewritten.

## decision_logs.policy_checks: real shape vs. frontend/lib/types.ts

Discovered while designing DecisionTrace's response schema, before writing
any code: frontend/lib/types.ts's PolicyChecks interface was written in
Day 3 against app/decision/persist.py's JSON shape
(is_disputed/is_actually_paid/proposed_action/final_action/result). But
every decision_logs row actually in the DB for the live pool was written
by Day 4's app/agent/audit.py during final_integration_pass.py --persist,
which uses a DIFFERENT (overlapping but not identical) shape -- confirmed
by reading audit.py's _build_policy_checks() directly, not inferred from
test assertions alone:

  is_disputed, is_actually_paid, state_transition_path, retry_count,
  error, and (present only when that GraphState shape has them)
  proposed_action, selected_action (not final_action), policy_result
  (not result), tool_result.

Two keys were simply renamed between the two modules (selected_action vs
final_action, policy_result vs result) and the real shape carries several
fields (state_transition_path, retry_count, tool_result) types.ts has
never seen. Resolved by NOT remapping: app/api/schemas.py's DecisionTrace
returns model_scores/evidence/policy_checks as dict[str, Any] -- the real,
raw JSONB, unmodified. This file (schemas.py) is now the actual source of
truth for what the API returns; frontend/lib/types.ts is stale and needs
reconciling to it during Day 6's frontend-wiring pass, not before -- doing
that remapping here would hide a real cross-module drift instead of
surfacing it, and would silently commit to Day 3's key names as if Day 4
had never changed them.

**What Day 6 specifically needs to do:** update PolicyChecks in types.ts
to use selected_action/policy_result (or decide to have the API alias them
instead, if the frontend team prefers stable names over raw fidelity --
that's a Day-6 judgment call, not resolved here) and either add
state_transition_path/retry_count/tool_result to the type or explicitly
drop them from what the UI reads.

## /api/invoices scoped via decision_logs EXISTS, not a date-range import

The live pool (900 invoices) and the historical pool (9,000) share the
same invoices table with no explicit "is_live" column. Scoping via
`EXISTS (SELECT 1 FROM decision_logs WHERE invoice_id = invoices.id)`
uses a real, current DB fact (only the live pool has ever been scored by
the decision engine, across Day 4's final_integration_pass and any
per-invoice `decide()` calls) instead of importing
synthetic.generator's LIVE_WINDOW_START/END constants into production API
code -- continuing the no-synthetic-dependency convention
(DEFAULT_AS_OF's precedent) into this layer. Also correctly includes the
496 invoices Day 5's attribution write-back moved to CLOSED_PAID/PAID --
they were scored once (Day 4) and remain part of the live pool's own
history, not silently dropped from the dashboard just because they later
resolved.

## Enum query-param filters compared against the enum MEMBER, not the raw string

`current_state` query param on GET /api/invoices is converted to
`AccountCurrentState(current_state)` before use in a `.where()` clause,
never compared as a raw string. Reason: `account_current_state_enum` has
no `values_callable`, so SQLAlchemy stores/reads each member's NAME
("WAIT"), not its `.value` ("wait") -- see CLAUDE.md's known-gotchas list.
Comparing `AccountState.current_state == "wait"` (raw string) would bind a
lowercase literal that never matches any stored row, silently returning an
empty list instead of erroring -- exactly the kind of gotcha this project
has been bitten by before with this specific enum. An invalid filter value
raises 400, not a silent empty result.

## /api/metrics: cheap recomputation from persisted fields, not a live model run

Baseline-vs-engine reuses app/decision/evaluation.py's summarize_strategy()
unchanged, fed from account_state.recoverability_score/next_action +
invoices.amount (already-persisted, from Day 4's final_integration_pass)
rather than a fresh run_full_live_pass() -- that would re-run BOTH the ML
scoring and the retrieval call for all ~900 invoices on every page load,
which is exactly the "re-running the models" cost the master doc's
subtask-9 brief says this API must avoid. summarize_strategy() itself only
applies probability_given_action()/INTERVENTION_COST_INR/friction_cost --
all pure, cheap, deterministic functions -- so recomputing the aggregate
at request time costs nothing beyond the DB read. Verified, not assumed,
that account_state's persisted scores reflect the final unweighted
recovery model (app/ml/DECISIONS.md's scale_pos_weight decision): checked
`train_xgb_classifier`'s default (scale_pos_weight=1.0) and confirmed
app/ml/persist.py's __main__ calls it with no override, so any run of
`python -m app.ml.persist` -- and nothing since has re-run or overridden
it -- produces the unweighted model these persisted scores come from.

The attribution half of the response is a zero-computation read of
attribution_experiment_results' pooled row (segment=None, action=None) --
already computed by subtask 4/5, never recomputed here.

## Bug found by the test suite: response_model_exclude_none=True strips
## None RECURSIVELY, not just at the top level

First implementation used `response_model_exclude_none=True` on the route
decorator to gate `escalate_by_archetype`/`consistency_warnings`. Caught
immediately by `test_get_attribution_slices_include_the_portfolio_row`:
that flag strips every `None` field in the ENTIRE response tree, including
`segment`/`action` on each nested `AttributionSliceOut` -- where `None`
legitimately means "pooled across that dimension", not "field is absent".
The portfolio row (segment=None, action=None) lost both keys entirely,
breaking any client that reads them to identify which row is the pooled
one. Fixed by not using response_model_exclude_none at all: the route
keeps `response_model=AttributionResponse` (so /docs still shows the
correct schema) but returns a manually-constructed `JSONResponse` --
FastAPI passes an explicit `Response` through unvalidated, so only the two
top-level diagnostic keys are conditionally included, and every
`AttributionSliceOut`'s real `None`s serialize as `null` as intended.
General lesson: `exclude_none` (on a response_model, a `model_dump()`, or a
route decorator) is never safe to reach for when `None` is a meaningful
value somewhere in the same response, not just a "field is absent" marker.

## /api/attribution's diagnostic fields are genuinely gated, not just labeled

`include_diagnostics=false` (the default) means `escalate_by_archetype`
and `consistency_warnings` are never populated at all -- combined with
`response_model_exclude_none=True` on the route, they are absent from the
JSON response entirely, not present-but-null. This matters beyond style:
these two fields are the same category of hidden-ground-truth-informed
content app/attribution/evaluate.py's diagnostic_* functions already
gate behind explicit opt-in (never wired into a decision, never persisted
to the production-facing attribution_experiment_results table) -- the API
layer's gate is the same discipline continued one level up, not a new
policy invented here.
