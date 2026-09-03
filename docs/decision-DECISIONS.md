# Decision layer (app/decision/) pipeline decisions

Running log of decision-layer defaults changed with evidence, not on-the-fly
judgment calls. Same convention as app/ml/DECISIONS.md and
app/agent/DECISIONS.md -- entries appended, not rewritten. No entry was
needed before Day 5 because nothing had changed ACTION_UPLIFT/economics
defaults since Day 3; this file starts here.

## ESCALATE's uplift corrected for large invoices (Day 5)

**The pinned commitment this closes:** Day 3/4's own escalation-
appropriateness diagnostic (app/decision/evaluation.py) found only 22.9% of
ESCALATE decisions went to the true-high-uplift archetype (chronic_late)
while 61.4% went to strategic_enterprise, whose hidden ground-truth
ESCALATE uplift is 0.00 -- flagged then as a finding to close with real
evidence, not just report (see the project's own pinned memory on this).
Day 5's randomized-holdout Attribution Engine (app/attribution/) is that
evidence.

**What the experiment found**, in order of how much weight each piece of
evidence actually deserves (see app/attribution/DECISIONS.md for the full
derivation of each):

1. Pooled ESCALATE showed incremental_recovered_amount = -Rs.797,115
   (-5.1% amount-weighted), z=-1.8se -- but this number is NOT reliable on
   its own: WAIT (a cell with a KNOWN zero true effect, since no archetype
   action_effects entry exists for it) showed z=+2.0se from noise alone, a
   larger magnitude than ESCALATE's. The pooled ESCALATE figure does not
   clearly clear its own noise floor.
2. Worse: the pooled figure actively DISAGREES IN SIGN with its own
   archetype-stratified decomposition (stratified sum = +Rs.635,569) --
   diagnosed as a Simpson's-paradox-style compositional bias (ESCALATE's
   treatment population is ~73% strategic_enterprise, whose ~1.6% true
   control rate is far below the 17.1% pooled control rate that
   chronic_late/promise_breaker's much higher rates pull the average up
   to). check_aggregation_consistency() in app/attribution/evaluate.py now
   flags this automatically. The pooled dollar figure should NOT be read
   as "ESCALATE loses Rs.797K" -- that number is distorted by composition.
3. **The one fact that doesn't depend on trusting any noisy realized
   outcome:** 73% of ESCALATE's treatment volume (62/85) went to
   strategic_enterprise, an archetype with a TRUE, by-construction uplift
   of exactly 0.00 (archetypes.py, not a measurement). This is the actual
   basis for this fix -- a targeting/composition problem, confirmed
   independently of the noisy dollar evidence, not a claim that the
   experiment proved a specific rupee loss.

**Why amount, not archetype, and why Rs.100,000:** a real system can
condition ACTION_UPLIFT on amount (observable) but never on archetype
(hidden ground truth, no real-world analogue). Checked before relying on
it, not assumed: diagnostic_amount_by_archetype() pulled the REAL live-pool
amount distribution per archetype. Every non-strategic_enterprise
archetype's 90th percentile amount is <=Rs.74,507; strategic_enterprise's
10th percentile is Rs.122,838 and its minimum is Rs.69,916 -- the BULK of
the two populations separate cleanly (strategic_enterprise's median
Rs.196,298 vs. everyone else's 90th percentile ceiling of Rs.74,507, a
~2.6x gap at the boundary), but the tails genuinely overlap
(promise_breaker's max Rs.168,393 and promise_keeper's max Rs.151,391 both
exceed strategic_enterprise's 10th percentile). Rs.100,000 is the midpoint
of the gap between the highest non-strategic_enterprise 90th percentile
(Rs.74,507) and strategic_enterprise's 10th percentile (Rs.122,838) --
(74,507 + 122,838) / 2 = 98,673, rounded to a clean number.

**Known, stated limitation, not hidden:** this threshold WILL misclassify
a real minority of invoices in both directions -- some genuinely-responsive
smaller-archetype invoices (chronic_late/promise_breaker/promise_keeper's
upper tails) get the reduced uplift they don't deserve, and the smallest
~10% of strategic_enterprise invoices keep the full uplift they don't
deserve either. This is the honest cost of using an imperfect but the only
available observable proxy -- same category of accepted approximation as
detect_dispute()'s latency/accuracy caveat in app/decision/policy.py.

**Why the reduced value is ~0.02, not zero or a measured number:** a
composition-weighted estimate, not a fit to the noisy realized data (which
point 1-2 above already showed isn't reliable at this magnitude) and not
the calibration floor (0.01, which would fully zero out the minority of
genuinely-responsive large invoices misclassified above). Reasoning:
~90%+ of invoices above the threshold are expected to be
strategic_enterprise-shaped (true uplift 0.00); the remainder are likely
chronic_late/promise_breaker/promise_keeper (true uplifts 0.08-0.18) --
a composition-weighted expectation given that mix lands near 0.02. This is
informed by the KNOWN archetype composition/uplift table
(archetypes.py -- itself never read by production code, only by this
DECISIONS.md's reasoning and by app/attribution/'s explicitly-allowlisted
diagnostic functions), not a number fit to attribution_records.

**Implementation:** `action_uplift(action_type, amount)` in
app/decision/economics.py replaces the direct `ACTION_UPLIFT[action_type]`
lookup inside `probability_given_action()` -- flat lookup for every action
except ESCALATE at/above `ESCALATE_LARGE_AMOUNT_THRESHOLD_INR`
(config.py), which returns `ESCALATE_LARGE_AMOUNT_UPLIFT` instead. This is
NOT a general "action x context" framework -- every other action stays a
flat dict lookup, unchanged, since no evidence yet supports tiering them.
`probability_given_action()` gained a required `amount` parameter (was
`(base_probability, action_type)`, now
`(base_probability, action_type, amount)`) -- updated at both call sites
(`compute_action_ev()` internally, `app/decision/evaluation.py`'s
`summarize_strategy()`) and in every test that called it directly.

**Demonstrated, not just asserted, to change a real decision:**
`test_large_invoice_no_longer_prefers_escalate_after_uplift_correction` in
tests/test_economics.py -- at base_probability=0.5, amount=Rs.300,000, the
pre-correction top action was ESCALATE (EV~Rs.170,270); post-correction,
VOICE wins (EV~Rs.164,780) and ESCALATE drops to 5th of 6 candidates
(EV~Rs.152,270, behind WHATSAPP and PAYMENT_LINK too, not just VOICE) --
the exact "old policy vs. updated policy" comparison this fix was supposed
to produce.

**Not done, and why:** no re-run of the full 900-invoice live pool through
`decide()`/`final_integration_pass.py` with the corrected economics --
that would be a THIRD permanent mutation of `decision_logs`/`account_state`
on top of Day 4's and Day 5's own write-back, for a comparison the unit
test above already demonstrates directly and reproducibly. If a full-pool
before/after aggregate (e.g. for the pitch deck) is wanted later, run it
read-only via `app/decision/evaluation.py`'s existing baseline-vs-engine
machinery against the corrected code -- do not persist it without a fresh
pg_dump snapshot first, same discipline as every other real write this
project has done.
