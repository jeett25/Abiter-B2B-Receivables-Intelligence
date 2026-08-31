# Attribution Engine (Day 5) pipeline decisions

Running log of Day-5 decisions made with evidence/rationale, not on-the-fly
judgment calls that get forgotten by the next session. Same convention as
app/ml/DECISIONS.md and app/agent/DECISIONS.md -- entries are appended, not
rewritten; a reversed decision gets a new entry that supersedes the old one,
the old one stays for the record.

## Write-back scope: treatment-arm outcomes are written back for real

Chosen over keeping the experiment confined to attribution_records only.
Once subtask 2/3 simulate an outcome for a treatment invoice, that outcome
gets written into invoices.status/payments/account_state for real, matching
the master doc's architecture (Outcome Verification feeds both the Account
State Machine Update and the Attribution Engine as parallel consumers of the
same real outcome). Direct consequence: this is a second permanent mutation
of the live pool on top of Day 4's `final_integration_pass.py --persist`
run -- a pg_dump snapshot before the real (persisting) experiment run is
mandatory, not optional, and seed_demo.py (subtask 9 in the Day-5 plan) is
what makes re-running the experiment for a second demo take safe.

## Split ratio: 50/50, not a small minority held back

The master doc's own architecture text frames the control group as "a
random % of eligible invoices held back," which in a real deployment would
be a small minority (you don't want to withhold help from half your
customers). Chosen 50/50 anyway for this synthetic benchmark: subtasks
4-6 need per-action and per-action-x-segment breakdowns (5 actions x
several segments), and with ~700-900 eligible invoices a small control
slice would leave several cells with single-digit counts, too thin to
report a meaningful measured-vs-assumed uplift table. This is an explicit,
stated departure from the literal production framing, made for statistical
power in a fixed-size demo population, not a claim that 50/50 is what a
real company would run.

## Stratification: customer_segment only

Chosen over customer_segment x amount tercile. One stratification
dimension keeps every stratum well-populated at n~700-900 (satisfies the
master doc's "comparable customer/segment strata" requirement) without
risking near-empty cells from a second dimension. Balance across amount/
industry/archetype is verified post-hoc as a diagnostic (subtask 1's own
checkpoint prints per-segment counts; further balance checks belong to
subtask 5/7's segment analysis), not engineered into the randomization
itself. Archetype is never used for stratification -- it's the hidden
ground truth this whole experiment exists to check the model against, and
letting it influence assignment would bias exactly the comparison the
experiment is supposed to make honestly.

## Eligibility: excludes only already-paid and disputed, nothing else

Both computed by reusing app/decision/policy.py's own detect_already_paid/
detect_dispute -- the exact functions decide() itself calls -- so
eligibility here can never silently drift from what the real decision path
already treats as a special case. Deliberately does NOT exclude invoices
where the engine would naturally choose WAIT/STOP: that's a legitimate
experimental data point (the control arm can confirm abstention was
correct), not a case to filter out. Policy-blocked-by-cooldown/max-contacts
is not a real exclusion category today -- Day 4's DECISIONS.md already
established that nothing writes to recovery_actions for the live pool, so
every live invoice's prior_contact_count is 0 and no invoice is currently
in cooldown; the eligibility check doesn't special-case this because there
is nothing to special-case yet, not because it was overlooked.

## Randomization: deterministic, storage-free, not a persisted flag

assign_treatment_groups() is a pure function: sort each customer_segment
stratum's eligible invoice_ids (str-sorted, since DB/query iteration order
is not guaranteed stable run-to-run), shuffle with
random.Random(f"{seed}:{segment}"), split into two contiguous halves.
Rerunning against the same population and seed always reproduces the exact
same assignment, so "store the assignment so it can't flip" is satisfied by
the function's own determinism up through subtask 2 -- no separate
assignment table or flag is needed until subtask 3/4 does the real,
permanent attribution_records write, at which point the persisted
treatment_group column becomes the actual source of truth (not a
recomputation of this function against a population that may have since
changed).

## attribution_records field semantics -- incremental_recovery is NULL at
## the row level, not a fake per-invoice causal number

Three fields, three different jobs:

- `baseline_predicted_recovery` = base_probability * amount -- the Day-2 ML
  model's own prediction, identical for both arms of a given invoice. This
  is a MODEL-CALIBRATION reference point, explicitly not "predicted organic
  recovery": Day 2's own DECISIONS.md already established that
  base_probability is trained on historical data that itself includes
  intervention effects (most historical invoices received some collection
  ladder), so it is not a clean zero-intervention baseline.
- `observed_recovery` = subtask 2's simulated outcome. Control draws from
  archetype.organic_recovery_probability alone (true zero-intervention
  ground truth); treatment draws from organic_recovery_probability +
  action_effects[action].recovery_uplift (same mechanism
  synthetic/generator.py already uses for historical data) -- walled off
  entirely inside app/attribution/'s simulator, never touched by
  decision/policy code. Legitimate here specifically because the master doc
  authorizes the synthetic simulator to resolve this experiment against its
  own known treatment effect; this is not the same category of read as a
  leakage bug elsewhere in the project.
- `incremental_recovery` is stored as NULL at the individual-row level.
  observed_recovery - baseline_predicted_recovery was considered and
  rejected AS THAT COLUMN specifically: a single invoice is either
  treatment or control, never both, so its individual treatment effect is
  fundamentally unobservable (the fundamental problem of causal inference)
  -- naming a per-row column incremental_recovery would imply a causal
  claim the row cannot support, even with a careful docstring caveat
  attached. The real incremental recovery number is a GROUP comparison:
  mean(observed_recovery | treatment) - mean(observed_recovery | control),
  computed at the portfolio/action/segment level in subtask 4/5 -- never
  fabricated per row. Requires making attribution_records.incremental_recovery
  nullable (currently NOT NULL) -- a small migration, deferred to subtask 3
  since that's the first point anything actually inserts into this table.

  The residual itself is NOT discarded, just not stored under a name that
  overclaims what it is. observed_recovery - baseline_predicted_recovery is
  still a legitimate diagnostic -- in aggregate across the eligible
  population, does the model's predicted recovery roughly track what the
  simulation actually produced? Same instinct as Day 2's archetype
  ground-truth sanity check, applied to the live pool instead of the
  historical one. Decided NOT to add a stored prediction_residual column:
  it's a one-line derivation from two columns already in the table
  (observed_recovery - baseline_predicted_recovery), so persisting it would
  be redundant with no query benefit attribution_records' own schema can't
  already provide via a computed expression -- computed on the fly by
  whatever subtask 4/5 reporting code needs it instead.

## Aggregate experiment results need their own table -- named now, built in subtask 4

If incremental_recovery is NULL on every row, the actual headline number
this whole engine exists to produce (mean(observed | treatment) -
mean(observed | control), and the resulting incremental recovered amount)
has no home in attribution_records at all. Rather than let subtask 4
retrofit this under time pressure, the shape is decided now:

New table, `attribution_experiment_results` (subtask 4 migration, not built
in subtask 1): experiment_id, segment (nullable -- NULL means pooled/
overall, a value means that one customer_segment's own row, so the pooled
headline and the per-segment breakdown live side by side in the same
table/shape rather than needing a second table), computed_at,
treatment_n, control_n, treatment_recovery_rate, control_recovery_rate,
incremental_recovery_rate, treatment_recovered_amount,
control_recovered_amount, incremental_recovered_amount, treatment_cost,
treatment_friction, incremental_net_recovery. The exact
incremental_recovered_amount formula (what "eligible population basis" to
scale the rate difference by) is finalized in subtask 4, not here.

Action-level (subtask 6) and action x segment (subtask 7) breakdowns will
likely want a similarly-shaped table of their own (action_type as an
additional grouping column) -- not designed now, decided when those
subtasks actually start, to avoid guessing the shape before the
aggregation code exists to inform it.

## Subtask 2: recovered must be horizon-gated from the TRUE delay, never
## from a capped ledger date -- and the horizon is reused, not invented

Two-stage outcome mechanism in app/attribution/simulate_outcomes.py, mirroring
synthetic/generator.py's own _simulate_historical_invoice() reapplied forward
from "now" instead of from an already-elapsed historical window:
1. `recovered_ever` ~ Bernoulli(organic_recovery_probability [+ action
   uplift for treatment]) -- unconditional on time.
2. IF recovered_ever, `true_delay_days` ~ Uniform(archetype.delay_days_range)
   [- action's delay_reduction_days for treatment].

Initial design risk, caught before writing code: capping the ledger-facing
date (necessary so payments.payment_date never violates
synthetic/validators.py's temporal-consistency check) must never be allowed
to influence whether an invoice counts as `recovered`. If `recovered` were
ever derived by checking whether a (possibly-capped) date falls inside some
window, the cap would trivially satisfy that window on every capped case --
and since control-arm outcomes never touch the ledger at all (no cap ever
applies to them), this would be a ONE-SIDED inflation of the treatment arm's
apparent recovery rate, entirely an artifact of when the experiment happened
to run relative to the synthetic calendar, not of the intervention actually
working.

Fix, structural not just documented: `recovered`/`recovered_amount` are a
pure function of the TRUE, uncapped `(recovered_ever, true_delay_days)`
pair, gated at ATTRIBUTION_HORIZON_DAYS -- computed identically for both
arms in `gate_at_horizon()`, which never receives or reads any capped date.
The ledger cap (`ledger_payment_date`, subtask 3's concern) is computed
separately, downstream of `recovered` already being locked in, and is never
read back into it. `recovery_date` (the true, uncapped date) is kept on
SimulatedOutcome even when `recovered=False`, specifically so "would recover
eventually, just past this experiment's measurement window" stays
distinguishable from "archetype draw says never recovers" -- collapsing that
distinction would throw away real time-to-recovery information for no
reason.

Direct behavioral consequence for subtask 3 (write-back): only invoices
where `recovered=True` (i.e., within the horizon) get their ledger flipped
to paid. An invoice that would eventually recover just outside the horizon
stays OPEN/overdue in the DB -- that's what the experiment actually observed
within its measurement window, not full omniscient future knowledge.

`ATTRIBUTION_HORIZON_DAYS = app.ml.config.HORIZON_DAYS` (60), reused rather
than invented, for two independent reasons: (1) baseline_predicted_recovery
already means "P(recovery within HORIZON_DAYS) * amount" -- a different
horizon here would make observed_recovery and baseline_predicted_recovery
measure two different clocks, breaking subtask 1's own residual diagnostic.
(2) Checked empirically anyway, not just assumed consistent by reuse alone:
computed the control-arm (pure organic) recovered-within-horizon rate at H=
30/45/60/90 using the real live-pool archetype mix. Pooled: 30d~43%,
60d~58%, 90d~72% -- all non-degenerate, monotonic as expected.
Per-archetype at H=60 reproduces Day 2's own already-documented finding
exactly (strategic_enterprise ~0%, since its 60-90d delay range sits right
at the boundary) -- not a new problem, the same one app/ml/DECISIONS.md
already logged and accepted for the ML model's own horizon choice.
Real per-archetype counts from the actual live pool are printed by
`python -m app.attribution.simulate_outcomes` (subtask 2's checkpoint), not
just the hand-computed approximation used to motivate this choice.

## Control's recorded action is WAIT, not a separate "no action" label

Matches app/decision/evaluation.py's existing NO_INTERVENTION_ACTIONS
convention ({WAIT, STOP}) rather than inventing a new label. WAIT ("no
active intervention, still monitoring") is the more accurate description of
what the control arm actually represents than STOP (which specifically
means "abandoned as not worth pursuing" -- a different claim the control arm
never makes).

## Subtask 3: write-back scope is exactly recovered=True, nothing else

Confirms and implements the write-back-for-real decision from subtask 1:
app/attribution/persist.py writes an attribution_records row for EVERY
eligible invoice (both arms), always -- but only touches
invoices/payments/account_state for outcome.recovered=True. An invoice the
experiment did not observe as recovered within ATTRIBUTION_HORIZON_DAYS
(never resolves, or resolves-but-outside-horizon) is left exactly as Day
4's final_integration_pass.py --persist already left it -- no
account_state churn for a "non-event". base_probability (the model's own
prediction, reused from the treatment arm's Decision or freshly scored via
score_recovery_probability for control, which never calls decide() at all)
is written to account_state.recoverability_score only for the recovered
case, matching Day 3 persist.py's own convention of recoverability_score
reflecting the model's estimate at the moment of resolution, not reset to
0/1.

promise_score, on any touched row, is deliberately left untouched -- this
experiment never runs the agent's promise-extraction/PTP flow (treatment
uses app/decision/service.py's decide_from_feature_row directly, the same
Day-3 deterministic service subtask 2 always used, not Day 4's LangGraph
run_invoice() -- see the "why decide(), not run_invoice()" entry below), so
there is nothing new to say about promise credibility for these invoices.

payments.method for the write-back is the literal string
"attribution_simulation" -- deliberately distinguishable from the
generator's real methods (bank_transfer/upi/cheque/card) so a later
inspection (or seed_demo.py's reset) can tell a Day-5-simulated payment
apart from Day-1 synthetic history at a glance. Confirmed harmless first:
grepped app/ml/features.py, payments.method is never read as a feature.

attribution_records.invoice_id is the table's primary key, so persisting
twice for the same invoice fails loudly (IntegrityError) rather than
silently duplicating -- unlike decision_logs' append-only design. Kept
deliberately: an experiment should be re-run on purpose (via seed_demo.py's
reset, once it exists), not accidentally re-triggered by rerunning this
script.

## Why decide(), not run_invoice() -- Day 3's service, not Day 4's agent

subtask 2/3 route the treatment arm through app/decision/service.py's
decide_from_feature_row() (Day 3's deterministic service), never Day 4's
app/agent/graph.py's run_invoice() (the LangGraph orchestration wrapping
the same decision logic plus tool dispatch/LLM/audit). The master doc's own
subtask-2 wording ("invoice -> ML -> retrieval -> economics -> policy ->
selected action") stops exactly where decide() stops -- it does not say
"-> tool dispatch". Routing through run_invoice() instead would mean a
PAYMENT_LINK decision (a real CANDIDATE_ACTIONS member) fires a REAL
Razorpay test-mode API call for every one of ~405 treatment invoices where
that's the chosen action -- an expensive, noisy side effect with no
analytical purpose for an experiment that's measuring economic uplift, not
demonstrating tool integration at this scale. decide_from_feature_row()
gives the exact same selected_action the agent layer would have used to
decide (UPDATE_STATE's mapping/determine_next_state ultimately reads the
same Economics+Policy output either way), without either the tool-dispatch
side effects or the multi-times-slower runtime.

## Bug found before subtask 4: action was never persisted, forcing a
## snapshot restore

Discovered while designing subtask 4's per-action breakdown: attribution_records
had no column recording which action a treatment invoice actually received
-- account_state.next_action gets overwritten to STOP for every recovered
invoice (a real, but different, fact: "nothing left to do"), and
not-recovered treatment invoices' action was never written anywhere at all.
Neither decision_logs nor any other table has it either, since subtask 2/3
deliberately calls decide_from_feature_row() directly rather than Day 4's
run_invoice() (see the entry below) -- there is no audit trail for this
experiment's action choices outside the in-memory SimulatedOutcome.

This could not be fixed by simply adding the column and backfilling from a
fresh simulation run: build_experiment_population() identifies the live
pool via invoices.status == OPEN, and the already-executed write-back had
flipped 496 invoices to PAID. Rerunning against the now-mutated DB would
silently draw from a smaller, different population (404 open invoices
instead of 812 eligible ones) under the same seed -- reproducing a
DIFFERENT experiment, not filling in the gap in the real one. Fixed by
restoring the pre-persist pg_dump snapshot (taken specifically for this
reason back in subtask 3) before adding the columns and re-running.
General lesson, not just this one bug: once a compute-then-persist step's
write-back mutates the same table its own population query depends on,
"deterministic given the same seed" stops being true against the live DB --
only true against a frozen/restored snapshot of the pre-experiment state.

## attribution_records.action / counterfactual_action

`action` (nullable): the real dispatched action, treatment rows only --
NULL for control (control's own `action` field internally is always WAIT,
but storing that would misleadingly suggest control received an
intervention decision at all, when it received none).

`counterfactual_action` (nullable): control rows only -- what
recommend_action()+evaluate_policy() would have chosen for that invoice,
computed WITHOUT calling retrieval (confirmed by reading economics.py's and
policy.py's own signatures: base_probability/amount/is_disputed/
prior_contact_count are the only inputs either function reads -- retrieved
cases never influence the action choice, only the explainability/dashboard
trace). Because it costs nothing extra at scale, it was added specifically
to make subtask 4/5's per-action comparison more honest than "every
action's treatment rate vs. one flat pooled control rate": an ESCALATE row
can now be compared against control invoices the engine would ALSO have
escalated, not against the whole control population regardless of how
different those invoices look. This is purely a reporting/stratification
label -- it is never fed back into control's simulated outcome, which
remains governed by organic probability alone, exactly as before this
change.

## attribution_experiment_results: one cube table, not two

Originally scoped (subtask 1 entry above) as a segment-only pooled/
breakdown table, with action-level breakdown left as "a similarly-shaped
table of their own, decided when that subtask starts." Superseded here:
since subtask 4 was merged with action-level analysis from the start (see
the Day-5 subtask renumbering), the table is built as one
(experiment_id, segment, action) cube instead -- segment=NULL means pooled
across segments, action=NULL means pooled across actions,
(segment=NULL, action=NULL) is the single portfolio headline row. Subtask 4
populates the pooled row, the per-segment rows (action=NULL), and the
per-action rows (segment=NULL); subtask 5 fills in the full segment x
action grid using the exact same table and aggregation function, not a
redesign.

## Bug found from the real subtask-4 run: recovery_rate must be
## amount-weighted, not count-weighted

The first real run of app/attribution/evaluate.py produced a portfolio
headline with incremental_recovery_rate = +3.3% (positive) alongside
incremental_recovered_amount = -Rs.60.7L (deeply negative) -- an internal
contradiction, not a real finding. Root cause: treatment_recovery_rate/
control_recovery_rate were computed as a COUNT-based fraction
(mean(recovered boolean), % of invoices recovered), then that count-based
rate was used inside the DOLLAR formula
(incremental_recovered_amount = treatment_recovered_amount -
control_recovery_rate * treatment_total_amount). That cross-multiplication
is only valid if recovered and non-recovered invoices have similar average
amounts -- they don't, here: invoices are lognormal and archetype-
correlated, and large invoices (chiefly strategic_enterprise, mean ~Rs.222K)
correlate with a delay range that mostly sits outside
ATTRIBUTION_HORIZON_DAYS, so they recover within-horizon far less often
than small invoices do. A rising COUNT of recovering invoices can
therefore coincide with falling DOLLARS recovered, and mixing the two
bases together produces exactly the sign contradiction observed.

Fixed by redefining treatment_recovery_rate/control_recovery_rate as
AMOUNT-weighted (recovered_amount.sum() / amount.sum()) throughout --
which also happens to match app/decision/evaluation.py's own pre-existing
recovery_rate definition (gross / total_amount) exactly, so this is an
alignment with an established convention, not a new one. With rate and
dollar figures built from the same basis, a positive rate can no longer
imply a negative dollar impact -- proven by a regression test
constructed with deliberately uneven amounts (test_recovery_rate_is_amount_weighted_not_count_weighted
in test_attribution_evaluate.py), not just asserted fixed.

This does not reverse escalate's finding -- if anything, amount-weighting
makes it look worse, since its failures concentrate in large invoices --
it makes the number honest rather than changing the underlying story.

## Subtask 5: noise calibration made quantitative, not eyeballed

Prompted by a real judgment call in the subtask-4 readout: WAIT showed a
+8.9% lift despite having zero true uplift by construction (no archetype
action_effects entry for WAIT, identical mechanism for both arms), which
was used informally as "here's roughly how much noise a cell this size
produces" when judging whether ESCALATE's -5.1% was a real signal. Called
out, correctly, as not quite apples-to-apples: WAIT's cell (~200 treatment
invoices) and ESCALATE's cell (~85) have different n, and noise scales with
1/sqrt(n), so borrowing WAIT's absolute noise magnitude for ESCALATE's
differently-sized cell understates ESCALATE's true noise floor.

Fixed with a two-proportion standard error / z-score
(_two_proportion_se_and_z), computed per slice: se = sqrt(p1(1-p1)/n1 +
p2(1-p2)/n2) (unpooled -- estimating the precision of the observed
difference itself, not testing a strict equal-proportions null), z =
(p1-p2)/se. Deliberately informal: no declared alpha, no
multiple-comparisons correction across the 8+ slices this module produces
-- "roughly how many SEs from zero" for calibrating whether a subgroup
result deserves weight, not a publishable significance claim. Cheap enough
to always compute; still worth being honest that it's a lightweight
calibration tool, not a rigorous testing framework, exactly per the
scope this was asked for.

**Critical: built on the COUNT-based rate, never the amount-weighted one.**
p1/p2 above are treatment_count_recovery_rate/control_count_recovery_rate
(fraction of INVOICES recovered) -- the natural quantity for a binomial
variance. This is a NEW, deliberate split from treatment_recovery_rate/
control_recovery_rate (amount-weighted, for the dollar figures) -- mixing
these two bases together is exactly the bug the subtask-4 entry above
already found and fixed once; the two are now structurally separate fields
on AttributionSlice/attribution_experiment_results, not two different
formulas reading the same field.

## Subtask 5: segment x action cells test a specific claim, not a generic
## cross-tab

compute_all_slices() now also computes every (segment, action) combination
that actually occurs in the treatment arm, using the exact same
compute_slice() (segment filter + action filter + counterfactual-matched
control, together this time), persisted into the same
attribution_experiment_results cube alongside the pooled/segment-only/
action-only rows -- exactly the extension the subtask-1 "one cube table,
not two" decision anticipated.

Built specifically to test the falsifiable claim ESCALATE's portfolio-level
-5.1%/-Rs.797K loss is concentrated in Enterprise/strategic_enterprise (61.4%
of escalations went there per Day 3's diagnostic, true ESCALATE uplift
0.00, delay range mostly outside the horizon) rather than broadly negative
across every segment/archetype -- a materially different finding that would
call for a broader ESCALATE recalibration in subtask 6, not a segment-
specific carve-out. The Enterprise x escalate cell (and, at the diagnostic
archetype level below, strategic_enterprise specifically) is what actually
answers this, not the segment-only or action-only rows in isolation.

## Archetype-level diagnostic: a deliberate, documented ground-truth read

diagnostic_action_by_archetype() reads customers.archetype directly --
hidden ground truth, off-limits everywhere else in this project except a
short, explicit allowlist. This is the SAME category of exception already
established twice: app/attribution/simulate_outcomes.py imports
synthetic.archetypes.ARCHETYPES to resolve the experiment itself, and
app/decision/evaluation.py's evaluate_escalation_appropriateness() already
reads archetype to verify (never decide) whether ESCALATE goes to the
archetype with real uplift. This function is the same pattern as the
latter: explaining a measured business result using the ground truth that
generated it, strictly after the fact, never influencing any decision or
simulated outcome.

Deliberately NOT persisted to attribution_experiment_results -- that table
stays limited to segment/action, dimensions a real production system could
actually observe. Archetype-level output is print/diagnostic-only (called
directly from evaluate.py's __main__, not wired into persist_slices()) so
the schema itself never carries a column that would read as an accidental
ground-truth leak to someone auditing it later without this file's context.

## Aggregation-consistency guardrail: pooled ESCALATE disagreed in SIGN with
## its own archetype-stratified sum

Found while reading subtask 5's real output: the pooled `escalate` row
showed incremental_recovered_amount = -Rs.797,115, but summing
diagnostic_action_by_archetype's own per-archetype figures for escalate
gave +Rs.635,570 -- opposite sign, not just a different magnitude. Root
cause: strategic_enterprise is ~73% of escalate's treatment volume (62/85)
with a true control rate of ~1.6%, while chronic_late/promise_breaker
(much smaller volume, ~52.9%/78.7% control rates) pull the POOLED control
rate up to 17.1% -- applying that inflated 17.1% counterfactual to a
population that's mostly strategic_enterprise-shaped manufactures an
extra-negative pooled figure that the stratified view doesn't support.
This is a real Simpson's-paradox-style aggregation bias, not a code bug --
the pooled and stratified figures are both computed correctly, they just
answer subtly different questions when the stratifying variable is unevenly
distributed and has very different rates per stratum.

Formalized as check_aggregation_consistency(pooled, stratified, label) --
a print-only guardrail (never gates or alters anything), run for every
action in evaluate.py's __main__, not just ESCALATE, since the failure
mode isn't ESCALATE-specific. Deliberately scoped to ONE function, not a
general statistical framework -- it compares sign (with a materiality
floor to ignore trivial-amount noise), nothing more. Same hidden-ground-
truth-for-verification-only category as diagnostic_action_by_archetype
(which it calls internally) -- never used to alter a decision or a
persisted attribution_experiment_results row, purely a printed warning
telling a human "don't trust this pooled number without checking the
breakdown."

**Practical consequence for subtask 6:** the pooled ESCALATE dollar figure
should not be read as "ESCALATE loses Rs.797K" -- that number is
compositionally distorted. The more defensible, ground-truth-independent
finding is the ONE fact that doesn't rely on trusting any noisy realized
outcome: 73% of ESCALATE's treatment volume goes to an archetype with a
true, by-construction uplift of exactly 0.00. That's a targeting problem,
not a magnitude-of-loss problem, and it's what subtask 6 should actually
fix.

## amount as an observable proxy for the targeting problem -- checked, not
## assumed clean

Since a real system can condition ACTION_UPLIFT on amount but never on
archetype (archetype has no real-world analogue -- see CLAUDE.md), subtask
6's fix needs amount to actually separate strategic_enterprise from other
archetypes reasonably cleanly, not just be "6-7x larger on average" (a
lognormal MEAN comparison that says nothing about tail overlap).
diagnostic_amount_by_archetype() groups the real (not simulated-from-
archetypes.py-parameters) live-pool amount data by archetype
(10th/25th/50th/75th/90th percentiles) specifically to check this before
subtask 6 relies on a threshold. Diagnostic-only, hidden ground truth, same
allowlist category as the other archetype-reading functions in this file --
never wired into a decision or persisted.

## Subtask 6: ACTION_UPLIFT correction lives in app/decision/DECISIONS.md,
## not here

The actual fix (ESCALATE's uplift conditioned on amount above
Rs.100,000, reduced to ~0.02) touches app/decision/config.py and
economics.py, not this package -- logged in the new app/decision/DECISIONS.md
alongside the code it changes, per this project's own convention of
co-locating a decision's rationale with the module it affects. This entry
is just the pointer: the full evidence chain (noise-floor check, the
Simpson's-paradox catch, the amount-distribution verification, the
composition-weighted value choice, and the demonstrated before/after
decision change) lives there.

## Reporting must be per-stratum, not just pooled -- confirmed for subtask 4

Randomization was stratified by customer_segment specifically so
treatment/control balance holds within each segment (see the
Stratification entry above), not just overall. subtask 4/5's aggregation
must report the incremental recovery rate per segment as well as pooled --
`attribution_experiment_results`'s nullable `segment` column above exists
specifically to carry both without a schema change between "pooled" and
"broken down." A single pooled number could hide a segment that responds
very differently to intervention than another; since the stratification
machinery already exists, reporting per-segment alongside pooled is a small
marginal cost for real analytical and demo value.
