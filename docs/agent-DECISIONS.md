# Agent (Day 4) pipeline decisions

Running log of orchestration-layer decisions made with evidence/rationale,
not on-the-fly judgment calls that get forgotten by the next session. Same
convention as app/ml/DECISIONS.md -- entries are appended, not rewritten; a
reversed decision gets a new entry that supersedes the old one, the old one
stays for the record.

## One graph invocation = one event

A multi-step story like "overdue -> promise -> broken -> reassess" is
modeled as separate graph runs over time, each triggered by its own Event,
with account_state.current_state (persisted in Postgres) carrying
continuity between runs -- not one long-lived graph holding a queue of
events in memory. Simpler, matches a real event-driven system, and is what
makes subtask 8's reassessment loop and subtask 10's scenario scripts
tractable (a driver just calls the graph again with the next event).

## Event ingestion: direct in-process calls, no Redis

The master architecture's Event Ingestion Layer specifies "FastAPI + async
workers, Redis queue." Deliberately not building that for Day 4: an event is
just a Python object passed directly into a graph invocation. REDIS_URL
stays an unused placeholder in .env. Revisit only if a real async/queued
ingestion path becomes a stated requirement later (e.g. a live webhook
receiver in Day 5+) -- nothing here blocks adding it later, since Event
itself doesn't assume how it was produced.

## review.timeout is a real event type, sourced by a driver, not external

The master doc's original event list included a purely time-based event
(review.timeout) alongside intervention.failed (renamed action.failed here,
naming choice only). Unlike every other event type, nothing external
produces it -- it exists because an invoice sitting in WAIT/REMIND/
MONITORING with no activity should still get reassessed once its cooldown
or silence window elapses (Policy Gate's own COOLDOWN_DAYS/
MAX_CONTACT_ATTEMPTS logic already implies this window; without a mechanism
to act on it, an invoice past that window just sits untouched).

Subtask 8 owns the driver that produces it: a scan function (e.g.
scan_for_review_timeouts()) that queries account_state for invoices whose
elapsed time in a non-terminal state exceeds the relevant threshold, and
emits a review.timeout Event for each. No real cron/scheduler -- given the
no-Redis decision above, this is a deterministic, on-demand query like
everything else in this project (invoke it manually or loop it), not a live
daemon.

## Idempotency / duplicate events: explicitly out of scope

Event has no dedup key beyond its own event_id (added for traceability into
decision_log.evidence, not for dedup). Nothing guards against the same
event being processed twice (e.g. a payment.received webhook retried by an
upstream sender). At this project's scale/timeline this is an accepted
simplification, not an oversight: the assumption is a single-delivery event
source. Logged explicitly rather than left silent, since idempotency is
exactly the kind of question a technical panel asks about anything touching
money events. First thing to add if this becomes real: a unique constraint
or an already-processed check keyed on a stable upstream delivery ID (not
event_id, which this system mints itself on receipt and therefore can't
distinguish a genuine retry from a new event).

## UPDATE_STATE is temporary scaffolding -- Subtask 4 owns all transition logic

Subtask 2's UPDATE_STATE node (update_account_state in app/agent/nodes.py)
uses a hardcoded action->state dict copied from persist.py's Day-3 one-shot
mapping, purely so the graph skeleton has something to put in next_state
before the real state machine exists. This is explicitly temporary and gets
replaced whole-cloth by Subtask 4's centralized (current_state, event) ->
next_state transition function.

Constraint, not just a note: UPDATE_STATE is the ONLY node allowed to touch
next_state. No other node (DECISION, ACTION, or anything added later) may
independently infer or set an account-state transition -- if a future
subtask needs state-transition-adjacent logic, it calls into Subtask 4's
transition function rather than growing its own copy of it. Centralizing
this in one place is what makes the transition table testable and
auditable as a single unit (subtask 4's own checkpoint: transition tests for
every major path) instead of scattered, inconsistent inference spread across
nodes.

## Account state machine (Subtask 4): dispute priority, KEPT's forward edge, and the path contract

app/agent/state_machine.py's determine_next_state() replaces UPDATE_STATE's
Subtask-2 placeholder outright, per the constraint logged above. Three
design points that weren't obvious from the master doc's transition example
and were resolved explicitly rather than left to rule-list-position accident:

**Dispute priority over the broken-promise narrative.** A disputed invoice's
persisted current_state is DISPUTE_REVIEW regardless of what else happened
this round (a promise created, a promise broken and reassessed, an ordinary
action outcome) -- disputes supersede all of it, intentionally. The
event-driven narrative (PROMISE, or BROKEN/REASSESS) is still preserved in
the transition's `path`, just never becomes the resting current_state while
the dispute is open. Consequence worth being explicit about, not just
implied by "no reverse transition": since nothing in this synthetic dataset
ever un-disputes an invoice, and this rule outranks everything except full
payment, DISPUTE_REVIEW is a de-facto absorbing state for the remainder of a
disputed invoice's lifecycle -- every subsequent event routes there except
one that fully pays the invoice off (rule 1 still wins over it). This is a
materially bigger behavioral consequence than "an enum value with no reverse
transition" sounds like, and it's a direct result of this priority choice,
not an oversight.

**KEPT is a real, readable resting state, not dead code.** current_state ==
PROMISE plus a payment event produces KEPT whether or not that payment fully
resolves the invoice -- if it does, the persisted next_state becomes
CLOSED_PAID (rule priority), but KEPT still appears in `path` (e.g.
[KEPT, CLOSED_PAID]), so "the promise was honored" is never lost from the
narrative even when superseded as the resting value. When it doesn't fully
resolve the invoice, KEPT genuinely persists as current_state and is read
back exactly like WAIT/REMIND on the next invocation -- no rule branches on
current_state == KEPT specially; it just flows through the cascade based on
whatever new event/flags apply then. Forward edge to CLOSED_PAID is rule 1,
the next time a payment fully clears the remaining balance.

**path contract, fixed:** always [...intermediate states..., next_state],
where `intermediate` is computed purely from the event type (and, for the
promise-resolution case, current_state) independent of dispute/paid status,
and deduplicated if next_state already equals the last intermediate entry.
Subtask 9's audit narrative can rely on this shape unconditionally.

**Bug caught by the first test run, fixed before merge:** the first
implementation used one `intermediate` list and picked `intermediate[-1]` as
the resting-state candidate whenever `intermediate` was non-empty -- wrong
for PROMISE_BROKEN, since that made `REASSESS` (a purely transient label)
win over a fresh `selected_action` as the persisted next_state, exactly
backwards from the intended "reassess, then the fresh action is what rests"
behavior. Fixed by splitting `_event_narrative()` into two return values:
the narrative `path` labels (always recorded) and a separate
`resting_candidate` (only `PROMISE`/`KEPT` ever set one; `PROMISE_BROKEN`
deliberately returns `None` so its narrative labels never short-circuit the
fresh action-outcome mapping). Caught immediately by
`test_promise_broken_reassesses_to_a_fresh_action_in_one_invocation`, not
found later -- exactly the kind of thing subtask 4's own checkpoint (named
transition-path tests) exists to catch.

**BROKEN/REASSESS are real but never literally persisted.** Because the
graph runs the full assessment pipeline on every invocation regardless of
triggering event, a PROMISE_BROKEN event's fresh economics+policy outcome is
already computed by the time UPDATE_STATE runs -- so "BROKEN -> REASSESS ->
next action" collapses into one invocation, with BROKEN/REASSESS recorded
in `path` for the audit trail rather than ever being written to
account_state.current_state.

## Action/tool layer (Subtask 5)

Five functions in app/agent/tools.py, one per non-WAIT/STOP ActionType,
every one returning a ToolResult and never raising. Confirmed before writing
this, not assumed: Customer/Merchant have no email/phone field anywhere in
the schema -- a deliberate Day-1 scope decision (the master doc's own
customers table never listed one), not something discovered missing now.
Since the simulated channels (email/whatsapp/voice/human-handoff) don't
deliver anywhere real regardless, they only need invoice_number/amount, not
a fabricated contact target.

create_payment_link is the one real integration (razorpay-python, test
mode). (1) Fast-fails with a structured result, no network call at all, if
RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET aren't configured -- confirmed as the
actual state at the time this was written (project's Razorpay test account
was still being set up). (2) No timeout/retry wrapping around the SDK call
-- that's Subtask 6's job wrapping this function, kept deliberately separate
from "does the tool work and fail safely" here.

**Correction, same session:** the first version of this function
deliberately left reference_id unset, reasoning that Razorpay rejecting a
duplicate would break repeated test/demo runs against the same invoice.
Caught in review before this was wired into the graph: that reasoning threw
away the actual point of reference_id -- a stable idempotency key protecting
against a real failure mode (worker crashes after Razorpay's create()
succeeds but before this graph run's state is persisted; the event gets
retried; PAYMENT_LINK fires again; two payment links now exist for one
invoice). Fixed properly: reference_id=str(invoice_id) (stable per invoice,
not per test run), and a Razorpay "duplicate reference_id" rejection is now
treated as an idempotent success (the desired outcome -- a payment link
exists for this invoice -- is already true) rather than a generic failure.
The actual safety guarantee is Razorpay's server-side uniqueness constraint
on reference_id, not this function's ability to correctly classify the
resulting error message (see _looks_like_duplicate_reference's docstring) --
worth being precise about which part is guaranteed vs. best-effort.

**Money is Decimal from this module's boundary inward, not float.** The ML
feature pipeline (app/ml/features.py) legitimately keeps amount as float
end-to-end for scoring -- that's correct there, not a shortcut. But it's
wrong for anything actually constructing a monetary payload (paise for
Razorpay). app/agent/nodes.py's dispatch_action converts once, at the exact
point money stops being a model input and starts being a real financial
operation: Decimal(str(state["features"]["amount"])), never Decimal(float)
directly (Decimal(0.1) carries binary-float artifacts; Decimal(str(0.1))
doesn't). Every tools.py function signature takes amount: Decimal.

**Simulated tools get a deterministic failure_mode flag, not random
unreliability.** execute_email/execute_whatsapp/execute_voice/
request_human_handoff all default to always succeeding (correct: there's no
real failure mode to model for a call that doesn't go anywhere), but that
meant Subtask 6's retry/fallback logic would have nothing to actually
exercise through these four tools. failure_mode=True forces a structured
success=False result deterministically -- explicitly not randomness, so
production behavior through these functions stays fully deterministic and
Subtask 6's tests are reproducible. create_payment_link doesn't need this
flag: its optional `client` param already serves as its test seam (inject a
fake client that raises).

## Retry/fallback/error handling (Subtask 6)

**call_with_retry (app/agent/resilience.py) is mechanism-only; fallback
semantics belong to the caller, never to this function.** It calls fn up to
max_attempts times against a caller-supplied is_success predicate and
returns (last_result, attempts_made) -- nothing more. This was corrected
during review before writing it: the first draft would have baked
"exhausted retries -> WAIT" into the retry utility itself, which looks
reusable but actually isn't, since subtask 7's future LLM extraction call
needs a completely different fallback ("failed twice -> treat the promise
as unextracted, don't fabricate one -- WAIT doesn't obviously mean anything
for a promise-extraction failure"). Keeping the two separate means subtask 7
reuses call_with_retry as-is and writes its own fallback, rather than this
function accumulating unrelated failure semantics from every caller that
has ever used it.

**dispatch_action's fallback: DO NOT GUESS a different channel, always
WAIT.** Exhausting retries on any contact action (EMAIL/WHATSAPP/VOICE/
ESCALATE) or PAYMENT_LINK falls back to ActionType.WAIT unconditionally --
never a substitute channel. proposed_action (ECONOMICS' original
recommendation, untouched by this) lets the audit trail show "wanted to
ESCALATE, tool failed twice, fell back to WAIT" rather than losing that
context. Subtask 8's review.timeout driver is what eventually picks the
account back up for reassessment.

**Duplicate events are not actively detected or suppressed, and that's
worth stating precisely rather than glossing as "safe."** Reprocessing is
designed to be operationally safe for the current action set --
create_payment_link's reference_id fix (Subtask 5) makes a duplicate
PAYMENT_LINK dispatch a no-op, the simulated tools have no real side
effects to double up, and determine_next_state is a pure function -- but
duplicate event processing CAN and WILL produce duplicate decision_log rows
once Subtask 9 wires persistence (append-only, one row per graph
invocation, no dedup at the audit layer either). That's a real, visible
artifact of this scope decision, not just a hypothetical: reprocessing the
same real-world occurrence twice will show as two separate decisions in the
audit trail, even though no money or state gets duplicated. Event-ID-based
deduplication is intentionally deferred, not forgotten -- see Subtask 1's
original entry above for the same call, now reaffirmed with the fuller
picture of what "safe" does and doesn't cover.

**Invalid events are routed to AUDIT, not yet recorded there.** ingest_event
no longer raises on a mismatched event.invoice_id (a hard exception would
crash the whole .invoke() call, exactly what this subtask exists to
prevent) -- it sets state["error"], and the graph's one conditional edge
(_route_after_ingest in graph.py) sends an errored state straight to AUDIT,
skipping the entire assessment pipeline. But AUDIT is still the Subtask-2
no-op stub today. So: invalid events are audit-ready, routed to the node
that will eventually persist them, once Subtask 9 exists -- not durably
recorded yet. This subtask's own tests verify the routing only, deliberately
not claiming persistence that doesn't exist for two more subtasks.

## Promise extraction + PTP activation (Subtask 7)

**Topology bug caught in review, fixed before writing code:** the first
draft checked event_type == PROMISE_CREATED at ML_SCORING, after
BUILD_FEATURES had already run unconditionally -- meaning SCORE_PTP would
have scored against recovery-model features (cutoff=due_date) instead of
PTP features (cutoff=T=now), silently defeating the subtask. Fixed by
moving the branch to right after LOAD_CONTEXT, before BUILD_FEATURES ever
executes: LOAD_CONTEXT -> (event_type==PROMISE_CREATED? SCORE_PTP :
BUILD_FEATURES). SCORE_PTP builds its own feature row via
build_live_ptp_feature_row(), entirely independent of state["features"].
Direct consequence: recovery_probability is never computed for a
promise-creation round -- absent from state, not fabricated, same
treatment the invalid-event path already gets.

**CUSTOMER_RESPONDED with no extractable promise falls through to the
normal pipeline, confirmed explicitly, not left implicit.** EXTRACT_PROMISE
leaves state["event"] unchanged (still CUSTOMER_RESPONDED) whenever
extract_promise() returns None -- whether because the LLM correctly found
no concrete commitment, or because extraction failed twice. The
LOAD_CONTEXT branch then routes to BUILD_FEATURES and the full
RETRIEVE_CASES -> ECONOMICS -> POLICY -> DECISION -> ACTION pipeline runs
exactly as for any other reassessment-triggering event -- CUSTOMER_RESPONDED
isn't named in determine_next_state's cascade, so it falls through to rule
6's ordinary action-outcome mapping. "No news, proceed as normal," and both
sub-cases (no promise vs. extraction failure) are deliberately
indistinguishable from extract_promise()'s return value alone -- they mean
the same thing downstream.

**call_with_retry's fallback here is "no promise created," not
dispatch_action's "fall back to WAIT"** -- exactly the separation Subtask
6's DECISIONS.md entry called for when it kept fallback semantics out of
call_with_retry itself. WAIT wouldn't obviously mean anything for a failed
promise-extraction call; "treat it as unextracted" does.

**The "inert placeholder" claim has a regression test, not just a design
assertion.** update_account_state defaults selected_action to
ActionType.WAIT when absent (Subtask 7's SCORE_PTP path never runs
DECISION). This is provably safe today because determine_next_state's rule
2 (event_type==PROMISE_CREATED -> PROMISE) fires before rule 6 ever reads
selected_action -- proven directly by
test_promise_created_next_state_is_independent_of_selected_action in
test_state_machine.py (parametrized over every ActionType, including STOP),
not just asserted true-by-construction. If a future change to the rule
cascade's ordering ever makes this untrue, that test fails immediately.

**The literal payment_promises DB row is deferred to Subtask 9, not written
here.** Every node so far has held to "no DB writes until Subtask 9 wires
persistence," specifically so repeated test/demo runs stay non-destructive
-- and build_ptp_table()'s own compute_promise_cutoffs() docstring
documents a real one-promise-per-invoice invariant this project's PTP
feature-building depends on, which repeated test runs actually inserting
rows would break. Subtask 7 computes and validates
promised_amount/promised_date/source and the PTP score, carrying them in
the rewritten event; Subtask 9 does the actual insert alongside
decision_logs.

**PTP score is informational only -- it does not gate the state
transition.** The master doc's own framing ("the LLM extracts the promise;
it does not decide whether the promise is credible -- the PTP model does
that") is about WHO assesses credibility, not about credibility gating
STATE. determine_next_state's PROMISE_CREATED rule doesn't read
ptp_probability at all; a low-credibility promise still lands in PROMISE,
same as a high-credibility one. Using PTP score to change the transition
(e.g., a very-low-credibility promise skipping straight to something more
skeptical) would be a real, defensible idea, but it's a new decision this
project hasn't made -- not assumed here as a hidden default.

## Event-driven reassessment loop (Subtask 8)

**The payment_promises write moved from Subtask 7's deferred-to-Subtask-9
plan to a narrow, immediate exception, because Subtask 8 structurally
depends on it.** The reassessment loop's whole point is a story spanning
two separate graph invocations over time (promise created in one, its
due-date-passed discovery feeding a second) -- that only works if the
promise genuinely persists in the database between them. Every other node
still holds to "no DB writes until Subtask 9 wires persistence"
(decision_logs/account_state remain untouched); this is one table, written
in SCORE_PTP (not EXTRACT_PROMISE), specifically because confidence_score
(NOT NULL on the model) is our own PTP model's calibrated probability --
the honest real-system value, unlike the synthetic historical data's
fabricated-from-ground-truth confidence_score -- and that value only exists
once scoring has run.

**The write is an upsert, not a blind insert, because the collision is
real, not hypothetical.** Two CUSTOMER_RESPONDED events extracting
successfully before the first promise resolves is a realistic scenario (a
customer revising their promise) -- and it's also exactly what happens if a
test re-runs against the same live invoice without a DB reset. _upsert_open_promise
(app/agent/nodes.py) checks for an existing OPEN promise on the invoice
first and updates it in place rather than duplicating, making it
structurally impossible to have more than one open promise per invoice at
once, and making repeated runs against the same invoice idempotent-safe --
the same property Subtask 6 established for the tool layer, now extended
to this write.

**scan_for_review_timeouts and scan_for_broken_promises partition
candidate invoices by account_state.current_state and can never both fire
for the same invoice in the same pass.** PROMISE is exclusively
scan_for_broken_promises's territory and is excluded from
scan_for_review_timeouts's candidate states (WAIT/REMIND/ESCALATE/KEPT) --
no other state can simultaneously be PROMISE, so the two candidate sets are
disjoint by construction, not by coincidence. Proven directly (both a
module-level assert and a named regression test in test_scanners.py), not
just by inspection -- if either scanner's candidate-state set is ever
edited, both catch a reopened double-fire path immediately.
DISPUTE_REVIEW is deliberately excluded from scan_for_review_timeouts too:
it's waiting on a human, and the automated system re-pinging it would
contradict the entire reason that state exists.

**scan_for_broken_promises checks the ledger before reporting broken,**
comparing cumulative payments on the invoice since the promise was made
against promised_amount -- a promise that's actually been kept (payment
arrived, invoice not yet fully closed) must route through the existing
KEPT path (current_state==PROMISE plus a real payment event), not get
mis-reported as broken by this scanner.

**payment.received/payment.partial are not scanned for -- they're
externally triggered**, same treatment customer.responded already gets: a
real system would learn these from a Razorpay webhook this project doesn't
have a live receiver for, so they're hand-constructed events in
tests/demo scripts.

**Driver/scheduling model, stated precisely:** today, scan_for_broken_promises
and scan_for_review_timeouts are plain functions invoked by a demo/test
driver with an explicit, controlled as_of -- matching Day 3's
DEFAULT_AS_OF reproducibility pattern, not a scheduled job. In a production
deployment this would be a periodic scan job (e.g. a cron-triggered
worker); building that scheduler is explicitly out of scope for this build
week.

## Full audit trail (Subtask 9)

**Persistence stays opt-in, defaulting to off.** write_audit only writes
when config["configurable"]["persist"] is True -- mirrors Day 3's
decide()-vs-persist_decision() split exactly. Dozens of tests across
Subtasks 2-8 call run_invoice() expecting write_audit to be a no-op;
flipping the default would silently make every one of them mutate
decision_logs/account_state for whatever live invoice they happened to
touch. run_invoice() gained a persist: bool = False convenience parameter
so callers that do want it (this subtask's own tests, the eventual demo
driver) don't have to hand-thread raw config dicts.

**app/agent/audit.py's builders are defensive across three genuinely
different state shapes**, not one: the normal pipeline (everything
present), promise-creation (only ptp_probability + next_state), and
invalid events (only error/retry_count, no next_state at all since
UPDATE_STATE never ran). Every field read uses .get()/"key" in state, never
blind indexing. The AccountState update is skipped entirely when
next_state is absent -- forcing a value there would fabricate a decision
this invocation never actually made. decision_logs is still written
unconditionally whenever persist=True regardless of shape, including for
invalid events -- recording the rejection was the entire point of Subtask
6's decision to route them to AUDIT instead of crashing, and skipping the
DecisionLog write for that shape would have silently undone that.

**Reused persist.py's _action_ev_to_dict/_retrieved_case_to_dict directly,
verified safe first, not assumed.** Both operate on a single
always-fully-populated dataclass instance (ActionEV/RetrievedCase) with no
internal iteration or null-checking of their own -- the list-comprehension
and the "does this list exist" question both live at the call site in
audit.py, which already guards on "economics_ranking" in state /
"retrieved_cases" in state before ever calling these helpers. Confirmed by
reading the actual function bodies, not inferred from "same types."

## Full agent simulation (Subtask 10)

app/agent/simulate_scenarios.py is a narrated rehearsal script
(python -m app.agent.simulate_scenarios), not a pytest suite -- most
scenario mechanics are already proven by existing tests; this assembles
them into one coherent, watchable story and fills in the two that had no
prior coverage (C, E). Runs with persist=True deliberately -- same
accepted-side-effect precedent as test_decision_persist.py/test_audit.py.

Reuses named demo fixtures for A/B/D/F (stable invoice_number across every
rehearsal/recording) rather than arbitrary live invoices. C (dispute) and E
(low economic value) have no matching fixture: C queries directly for a
real disputed live invoice; E scans the live pool via Day-3's
run_full_live_pass() (fast -- loads tables once, no LLM/embedding calls)
for a real invoice that genuinely resolves to STOP today, printing which
one it found rather than assuming one exists. Both scan/query at DAY1 (the
script's own timeline), not Day-3's DEFAULT_AS_OF, to avoid any
as-of-date mismatch between the diagnostic scan and the actual demo run
that follows it.

DAY1/DAY10 (the script's fixed timeline) were checked, not assumed, to
fall on IST business days/hours -- Scenario F and C's ESCALATE path is
gated on is_business_hours(), and a silently-wrong reference timestamp
already broke this once before (Day 3's DEFAULT_AS_OF gotcha, see
CLAUDE.md's known-gotchas list).

**Scenario E (low economic value -> CLOSED_ABANDONED) is unreachable by
any real live invoice today -- verified directly, not assumed from the
scan result alone.** Two paths lead to STOP in the Policy Gate:
(1) low pursuit value, which requires the Economics Engine's own
recommend_action() to choose WAIT first -- swept amounts down to Rs.5,000
(the dataset floor) and probabilities down to 0.01 (the calibration floor):
WAIT never won a single combination. At the absolute floor, WHATSAPP's EV
(Rs.407) still beats WAIT's (Rs.50) well past the materiality threshold.
This is Day 3's own already-documented finding (PAYMENT_LINK/WHATSAPP
dominate the realistic amount range, "accepted... rather than re-tuned
further, to avoid curve-fitting") -- Subtask 10 is just the first time
anyone actually tried to trigger the rule that depends on it not dominating.
(2) max contact attempts (MAX_CONTACT_ATTEMPTS=5) -- doesn't depend on
economics at all, but requires prior_contact_count >= 5, and nothing in
this project writes to recovery_actions for the live pool (the simulated
tools don't insert rows), so every live invoice's count is still 0.

Re-tuning the economics config now specifically to make this scenario
reachable would be the exact "curve-fitting toward an arbitrary target"
Day 3 already rejected doing, in a new guise -- not done. Per explicit
user decision, Scenario E instead demonstrates the mechanism directly
(determine_next_state() with a constructed context), clearly labeled
illustrative rather than presented as a real invoice's own decision -- the
mechanism itself is already proven by
test_state_machine.py::test_stop_maps_to_closed_abandoned_when_not_actually_paid,
this just makes it visible in the same narrated rehearsal as the other
five scenarios.

## Final integration pass (Subtask 11): dry run first, two real findings caught

Per explicit decision, this ran dry (persist=False) before ever touching
the permanent write -- and it caught two real things a persisted run would
have made much more annoying to unwind, exactly the reason the dry run was
insisted on rather than skipped "to save a run":

**CLOSED_ABANDONED count: 0/900, confirmed as expected.** Matches the
low-value/max-contacts unreachability finding verified earlier at small
scale (case-by-case sweep down to the amount/probability floor) -- the
full-900 dry run is the same finding at full scale, not a new one. Zero
was the predicted, correct answer, and the dry run confirms it rather than
just asserting it.

**"No hidden-ground-truth identifiers" initially failed on this script's
own denylist.** final_integration_pass.py's FORBIDDEN_IDENTIFIERS list
necessarily contains the words archetype/true_recovery_probability/
true_promise_keep_probability as string literals to define what to search
for -- the check was scanning its own source file and matching its own
denylist. Fixed by excluding this file from its own scan. Trivial once
seen, but a real instance of "the checker checking itself" -- worth
noting since it's a class of bug this project's own rigor (verify
directly, don't assume a check is correct just because it ran and
produced output) exists specifically to catch.

**"No placeholder recovery_probability" failed for real (74/900), traced
to a genuine float32/float64 precision bug in Day 2's
calibrated_predict_proba() -- see app/ml/DECISIONS.md's Subtask-11 entry
for the full root-cause trace and fix.** Re-verified directly after the
fix: 0/900 out-of-bounds. This is the clearest evidence yet for why the
dry run was the right call -- a real, previously-undiscovered bug in
"settled" Day-2 code, caught and fixed before 900 rows were permanently
written, not after.

## features stored as dict, not pandas Series

GraphState.features is dict[str, Any] | None, not pd.Series -- keeps agent
state easily serializable/inspectable and decouples it from the
data-processing layer. The conversion (with numpy scalar / pd.Timestamp /
NaN sanitization so the dict is actually JSON-clean) happens in subtask 2's
context-loading node, the first place a real feature row exists. Day-3
functions that expect a Series (score_recovery_probability, etc.) are
unchanged -- a node reconstructs pd.Series(state["features"]) immediately
before calling into them; the Series shape only ever lives transiently
inside a node, never in state.

## Bug found during Day 5's final validation pass: Scenario A's payment
## insert had no date cap, unlike test_reassessment_loop.py's equivalent

simulate_scenarios.py's scenario_a_successful() writes a real Payment row
dated DAY10 (2026-09-03) with no cleanup and no cap, same pattern
tests/test_reassessment_loop.py had before it was fixed -- except this one
was never caught earlier because no pytest test invokes
simulate_scenarios.py's functions (confirmed by grep), so it only
surfaces when someone actually runs `python -m app.agent.simulate_scenarios`
by hand. Every such run would permanently fail
synthetic/validators.py's temporal-consistency check. Fixed the same way
app/attribution/persist.py already handles this exact situation: cap the
persisted payment_date at DEFAULT_AS_OF - 1 day, leaving the narrative's
own DAY10 timestamp (used for the PAYMENT_RECEIVED event itself) untouched
-- only the ledger write is capped. Unlike the pytest-test case, no
cleanup was added here on purpose: this script's whole point is leaving a
real, inspectable trail (`decision_logs`/`account_state`/now `payments`)
behind for rehearsal review, same accepted-side-effect precedent already
established for this file.
