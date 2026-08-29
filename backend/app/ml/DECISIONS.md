# ML pipeline decisions

Running log of modeling decisions made with evidence, not on-the-fly judgment
calls that get forgotten by the next session. Entries are appended, not
rewritten -- a reversed decision gets a new entry that supersedes the old one;
the old one stays for the record.

## Recovery horizon: HORIZON_DAYS = 60 (not 90)

90 was the starting hypothesis (covers organic delay ranges of most
archetypes). Checked against real data via `resolution_delay_curve()` in
`labels.py`: at H=90, pooled `recovery_label` positive rate was 87.2%, above
the pre-committed 15-85% class-balance bound; several archetypes also sat
above 85% (reliable_payer 95.6%, slightly_late 94.6%, promise_keeper 92.2%,
strategic_enterprise 91.7%). Checked H=60: pooled 76.5% (in-band).

Chosen for a business reason independent of the gate passing: 60 days is
closer to the actual window in which a recovery decision is still actionable,
not just the horizon that happens to balance the label. strategic_enterprise
still misses the band at H=60 (12%, failing low) -- known, accepted, not
fixable by horizon choice (its delay distribution is a step function with
almost nothing resolved between ~60d and ~90d).

## Class-balance gate: pooled only, per-archetype is diagnostic

Per-archetype 15-85% compliance is structurally unachievable for any single
horizon -- reliable_payer/slightly_late/promise_keeper organically resolve
fast enough to exceed 85% at every horizon tested (30-150d), and
strategic_enterprise's step-function distribution means it can only ever fail
low or high, never land in-band. This is population heterogeneity by
construction (the 8 archetypes are deliberately different), not a labeling
defect. The hard gate applies to the pooled rate only; the per-archetype table
is still computed and printed every run as a permanent diagnostic, not
removed.

## scale_pos_weight: dropped, unweighted (1.0) is the default

Recovery label is ~76.5% positive on the fit split -- moderate, not severe,
imbalance. Ran a controlled comparison: auto-computed `scale_pos_weight`
(~0.31 for A, ~0.32 for B, i.e. neg/pos ratio from each experiment's own fit
split) vs. `scale_pos_weight=1.0`, same fit/validation/test splits, same seed,
both experiments.

| | scale_pos_weight | ROC-AUC | PR-AUC | LogLoss | Brier | rounds used |
|---|---|---|---|---|---|---|
| A weighted | 0.306 | 0.8328 | 0.9221 | 0.4619 | 0.1482 | 68/300 |
| A unweighted | 1.0 | 0.8311 | 0.9199 | 0.3762 | 0.1151 | 66/300 |
| B weighted | 0.323 | 0.7916 | 0.9213 | 0.4502 | 0.1400 | 300/300 |
| B unweighted | 1.0 | 0.7998 | 0.9278 | 0.3783 | 0.1149 | 51/300 |

Ranking metrics (ROC-AUC/PR-AUC) are essentially unchanged by weighting --
expected, since `scale_pos_weight` reshapes the loss, not the model's ability
to rank examples. Probability-quality metrics (LogLoss/Brier) are 20-25%
worse under weighting in both experiments. For B specifically, weighting also
suppressed early stopping (used the full 300-round budget vs. 51/300
unweighted) -- the reshaped loss landscape kept validation loss from
plateauing normally, itself a mild overfitting-risk signal independent of the
calibration argument below.

Dropped `scale_pos_weight` because: (1) the imbalance here (~3:1) isn't severe
enough to need it -- that technique earns its keep on much more skewed
problems (rare-event/fraud-style); (2) the recovery model goes through
isotonic calibration next, and calibration works best correcting a model
whose raw probabilities are already close to well-calibrated -- starting from
`scale_pos_weight`'s artificially skewed probabilities gives calibration more
distortion to undo for zero ranking benefit in return.

This reverses an earlier default heuristic ("use `scale_pos_weight` given the
imbalance") -- that heuristic was a reasonable prior before anyone had
measured whether it helped on this specific dataset; it doesn't survive a
controlled comparison that points the other way, so it's superseded by this
entry.

**Side effect, not a separate open question:** Experiment B's early-stopping
behavior had been flagged as ambiguous (cold-start-is-genuinely-harder vs.
under-regularized overfitting), pending a rerun at a higher `n_estimators`
budget to check whether validation had plateaued. That rerun is unnecessary
now -- under the unweighted model, B stops at 51/300 rounds with early
stopping engaging normally, which looks like a healthy fit rather than a
fit-set-noise-chasing pattern. Resolved as a side effect of dropping the
weighting, not left dangling.

## Calibrated probabilities clipped to [0.01, 0.99]

First isotonic-calibration run on `model_A` (Experiment A) showed an
unexpected pattern: Brier moved negligibly (0.1151 raw -> 0.1164 calibrated)
but LogLoss got meaningfully *worse* (0.3774 -> 0.5189), which calibration
should never do to this degree. Diagnosed directly (not guessed): isotonic
regression's PAV fit produced boundary blocks that were literally all-one-class
in the calibration slice, so `calibrator.predict()` returned exact 0.0/1.0 for
203 (of 1613) test rows at the top extreme and 40 at the bottom. Most were
correct, but some weren't -- e.g. a raw score of 0.9597 calibrated to exactly
`1.0` for an invoice that actually landed `y=0`. A prediction of literal
certainty being wrong is catastrophic under log loss (unbounded penalty for a
confidently-wrong point) but barely visible under Brier (bounded, max penalty
1.0 per point) -- exactly the asymmetry observed, confirming the mechanism
rather than leaving it as a hypothesis.

Fix: `calibrated_predict_proba()` clips every calibrated probability to
`[0.01, 0.99]` before it's used for evaluation or anything downstream. This is
a deliberate operational floor/ceiling, not a machine epsilon picked to make a
metric look better: no probability estimate from finite calibration data
should ever be reported as literally certain or literally impossible, and this
matters beyond the metric -- this recovery probability is meant to feed Day
3's `EV(a) = P(recovery|a,x) * Amount - Cost - Friction`, where a literal 0/1
would let the economics engine treat finite-data uncertainty as certainty, a
real correctness problem, not just a log-loss artifact.

Applies to the recovery model now; revisit for the PTP model (Platt/sigmoid
calibration, subtask 8) -- sigmoid calibration is smooth and much less prone
to exact 0/1 outputs than isotonic's step function, but the same clip is cheap
insurance and the same downstream-economics argument applies regardless of
calibration method.

Post-fix numbers on Experiment A's test set: LogLoss 0.3774 (raw) -> 0.3938
(calibrated, clipped) -- a small, expected increase, not the earlier 37% blowup.
Brier 0.1151 -> 0.1161, essentially flat. Consistent with the raw model
already being reasonably well-calibrated on its own (trained with a log-loss
objective), leaving isotonic little room to improve on a modest 987-row
calibration slice.

## Known imperfection: low-probability bucket underestimates risk

Reliability table (calibrated, clipped, Experiment A test set) tracks well
from the 0.5 bucket up through 0.9+ (e.g. `[0.9,1.0)`: predicted 95.7% vs.
observed 94.6%, n=797). The `[0.0,0.1)` bucket does not: predicted mean 7.1%
vs. observed 14.9% (n=181) -- the model is overconfident on its lowest-risk
predictions, understating actual recovery risk there by roughly 2x in relative
terms. Likely cause: few low-probability examples in a modest calibration
slice make the isotonic fit noisier at that extreme.

Logged, not fixed, under today's timeline -- affects a relatively small
subpopulation (181 of 1613 test rows) and doesn't change the pooled
verdict. Worth a look if the low-probability tail becomes operationally
important later (e.g. the Policy Gate leaning heavily on "confidently
low-risk" invoices to justify WAIT/STOP decisions) -- more calibration data or
a wider calibration fraction would be the first thing to try.

## Archetype sanity check (subtask 9): recovery clean, PTP has one real gap

Recovery model, Experiment A test slice, three-way table (true organic
probability | mean predicted | observed):

| archetype | true | predicted | observed |
|---|---|---|---|
| cash_constrained | 0.45 | 0.633 | 0.565 |
| chronic_late | 0.55 | 0.772 | 0.826 |
| promise_breaker | 0.50 | 0.719 | 0.685 |
| promise_keeper | 0.60 | 0.920 | 0.916 |
| reliable_payer | 0.95 | 0.952 | 0.959 |
| slightly_late | 0.85 | 0.957 | 0.936 |
| strategic_enterprise | 0.90 | 0.076 | 0.148 |

All explained. Six of seven archetypes show predicted/observed both above
true -- the intervention-uplift mechanism the master plan anticipated
(escalation actions push realized 60-day recovery above the organic
baseline), and predicted tracks observed closely in each. `strategic_enterprise`
is not a new problem -- it's the H=60 decision above showing up exactly as
predicted: this archetype resolves in the 60-90 day range, so both predicted
and observed correctly show most haven't recovered within 60 days yet, even
though 90% eventually will.

PTP model (full promise-eligible set -- test slice was too thin, min
archetype n=9 < 30, see MIN_ARCHETYPE_N in train_ptp.py):

| archetype | true (promise-keep) | predicted | observed |
|---|---|---|---|
| cash_constrained | 0.55 | 0.581 | 0.525 |
| chronic_late | 0.45 | 0.450 | 0.443 |
| **promise_breaker** | **0.20** | **0.401** | **0.181** |
| promise_keeper | 0.90 | 0.795 | 0.916 |
| reliable_payer | 0.95 | 0.834 | 0.972 |
| slightly_late | 0.80 | 0.768 | 0.817 |
| strategic_enterprise | 0.75 | 0.711 | 0.782 |

Observed tracks true almost exactly everywhere (within ~0.03) -- expected,
since `kept`/`broken` is a direct unnoised Bernoulli draw from
`archetype.promise_keep_probability` in the generator, confirming the
population itself isn't distorted. `promise_breaker` is a real predictive
miss: predicted 40.1% vs. actual 18.1%, more than 2x off, the largest gap in
either table.

Investigated directly (feature-distribution comparison across archetypes,
not guessed) before logging this:

1. **The model's top feature doesn't flag this archetype.** `prior_avg_delay_days`
   is the single most important PTP feature (0.161), and on it
   `promise_breaker` (27.8 days) looks *milder* than `cash_constrained` (37.6d)
   and `chronic_late` (31.6d) -- its archetype-level delay range (20-50d) is
   genuinely shorter than those. The feature the model trusts most doesn't
   signal risk here.
2. **The feature that would flag it is under-weighted.** `prior_promise_kept_rate`
   and `recent_180d_ptp_keep_rate` DO separate this archetype well
   (0.271/0.291 vs. 0.584/0.662 cash_constrained, 0.495/0.484 chronic_late,
   0.915/0.922 promise_keeper) -- but `prior_promise_kept_rate` doesn't even
   rank in the model's top 10 importances, and both features are missing
   ~22-23% of the time for this archetype (similar to other archetypes, not
   uniquely bad, but a real gap in the one signal that would help).
3. **`source` actively works against it.** `promise_breaker`'s channel mix
   (70% whatsapp, 14% voice, 16% escalate, 0% email/payment_link) is nearly
   identical to `promise_keeper`'s (76% whatsapp, 24% voice, 0% else) -- the
   archetype with the *opposite* extreme keep rate. On this feature a
   promise-breaker promise and a promise-keeper promise look the same.

Not a leak, not a bug -- this is the honest cost of correctly excluding
`confidence_score` (subtask 4): without that near-direct encoding of the
ground truth, the model has to infer purely from behavioral correlates, and
`promise_breaker`'s defining trait (breaks promises specifically) isn't well
captured by the delay/amount features that dominate its decisions, while the
one feature that would capture it is under-weighted and partially missing.

Logged as a known model limitation, not fixed -- explicitly decided against a
monotonic constraint or manual feature-weighting fix under today's timeline.
If this becomes operationally important later (e.g. `promise_breaker`
customers getting mis-prioritized by the Policy Gate), the first things to try
would be forcing more weight onto `prior_promise_kept_rate`/
`recent_180d_ptp_keep_rate` (monotone constraints or a higher `colsample`
emphasis) or reducing the NaN rate on those features (a longer historical
window per customer, if available).

## Bug found and fixed: customer_invoice_frequency division blowup

Found live while spot-checking a `FeatureSnapshot` row during subtask 13
(persistence) -- `customer_invoice_frequency: 3000000.0` in the stored JSONB,
not a plausible invoices-per-month figure. Not an isolated fluke: **1,261 of
9,000 historical rows (14%)** had a negative `customer_relationship_days_at_cutoff`,
and 1,245 of those produced a `customer_invoice_frequency` blowup (mean
1.03M, max 25M across the full table).

Root cause: `customer.relationship_start_date` and each invoice's `issue_date`
are drawn independently in the Day-1 generator, with no constraint that
`issue_date >= relationship_start_date` -- so a cutoff before the customer's
recorded relationship start genuinely occurs for ~14% of historical rows. The
frequency formula divided `len(prior_issued)` by
`max(days_since_relationship_start / 30, 1e-6)` -- when the duration was
negative, the `1e-6` floor turned a division-by-near-zero into an
explosion (e.g. 3 prior invoices / 1e-6 months = 3,000,000).

This is a genuine Day-1 data characteristic, not something to fix in the
generator at this point in the project -- the feature engineering needs to
handle it, not the data. Fix: both `customer_invoice_frequency` and
`customer_relationship_days_at_cutoff` are now `NaN` when
`cutoff <= relationship_start_date`, instead of a fabricated number.
"Invoices per month since a relationship that hasn't started yet" is
undefined, not a small-but-real duration -- consistent with this project's
existing convention (undefined -> NaN, never a fabricated value). Regression
test added: `test_cutoff_before_relationship_start_date_gives_nan_not_a_blowup`
in `test_ml_features.py`.

**Impact assessed, not assumed:** this bug was present since subtask 2,
silently affecting every result reported through subtasks 6-9. Retrained both
models after the fix and compared:

| | before fix (test ROC-AUC) | after fix (test ROC-AUC) |
|---|---|---|
| Recovery A | 0.8281-0.8332 (varied by run) | 0.8294 |
| Recovery B | 0.7998 | 0.8031 |
| PTP A | 0.8332 | 0.8350 |
| PTP B | 0.8082 | 0.8081 |

All within normal run-to-run noise -- no meaningful shift. The
`promise_breaker` archetype finding above and the `strategic_enterprise`
horizon-truncation finding both reproduce essentially unchanged post-fix.
Consistent with tree-based splitting being fairly robust to a minority of
extreme-magnitude values in one feature -- but the feature itself was still
genuinely corrupted (not just cosmetically off), and the `FeatureSnapshot`
rows written to the DB before this fix stored garbage values for ~14% of
rows. All artifacts and snapshots re-generated after the fix (subtask 13
re-run).

## Day 3 addition: `build_live_feature_table()` -- widened customer grouping, traced and tested against re-leaking

Day 3's Decision Service needed to score the 900 live (open) invoices with
the same recovery model, which required computing the same features for a
population `build_feature_table()` never covers (it filters to
`HISTORICAL_STATUSES` only). Added `build_live_feature_table()` in
`features.py`, reusing every existing helper (`invoice_static_features`,
`rolling_features`, `prior_resolved_invoices`, `prior_issued_invoices`)
unchanged, same cutoff=`due_date` convention as the historical path -- a live
invoice is scored "as of the day it became due", the exact reference frame
the model was trained on, regardless of how much real time has passed since.

One deliberate difference from `build_feature_table()`: each customer's
"other invoices" group is drawn from their **full** invoice history
(historical + other live siblings), not `HISTORICAL_STATUSES` only. A
customer can genuinely have more than one live invoice open at once, and an
earlier-issued sibling should count toward cadence/prior-history features
exactly as it would in production, even though it isn't itself resolved.

This is exactly the kind of change that could reopen a leakage path --
traced directly rather than assumed safe: `prior_resolved_invoices`
structurally excludes anything not PAID/WRITTEN_OFF regardless of dates
(`is_resolved_before`'s fallthrough returns `False` for any other status),
and `prior_issued_invoices` only ever checks `issue_date < cutoff`, never a
sibling's own `due_date` or resolution status -- so a live sibling can never
leak in via either function, by construction. Proven with a direct
adversarial test (`test_live_sibling_grouping_includes_earlier_issued_excludes_later_issued`
in `test_ml_features.py`), not just the trace: a sibling issued before the
target's cutoff but due *after* it is confirmed counted (positive control),
and a sibling issued *after* the target's cutoff is confirmed excluded even
though it sits in the same widened pool (the actual adversarial check).

Single-row scoring through the trained model (a new usage pattern -- one
live invoice at a time, not a batch of thousands) was also verified, not
assumed: XGBoost's categorical handling matches `merchant_segment`/
`merchant_industry`/`customer_segment`/`customer_industry` by value name, not
code position, confirmed by comparing predictions for isolated single-row
frames against the same rows scored in full context (identical to machine
precision) before relying on it in `app/decision/service.py`.
