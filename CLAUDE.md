# CLAUDE.md — B2B Receivables Decision Intelligence

Single source of truth for this project across sessions. Read this first in any new session before touching code.

## What this is

Submission for **Razorpay AI Buildathon 2026, Track 03 (AI Revenue Recovery)**. Not "an AI collections bot" — a decision engine that, for every overdue B2B invoice, decides *whether* chasing it is worth it, *why* it's late, *how confident* to be in any payment promise, *which* intervention is cheapest-and-effective, executes it inside compliant guardrails, and *proves* how much money it actually caused to come in vs. what would have arrived anyway (via a randomized holdout/attribution engine).

Full architecture spec (11-table Postgres+pgvector schema, XGBoost recovery/PTP models, LangGraph orchestration, deterministic policy gate, attribution engine, Next.js frontend) was provided by the user as a markdown doc at the start of the project — not stored in the repo, but its content is what everything below implements. Key sections referenced throughout this file: §4 (data model), §5 (ML layer), §6 (synthetic dataset), §9 (five completeness gaps), §10 (7-day build plan).

7-day build plan, ending with a demo video submission. Days 1–4 are all done (see their sections below). **Day 5 starts next session.**

## ⚠ CURRENT CANONICAL STATE (2026-09-03, work PC) — READ THIS FIRST

**Every specific number (model metrics, attribution rates, evaluation totals,
live-pool counts) anywhere below this section was true AT THE TIME that
section was written, against whatever database existed then. Multiple
sessions since have restored/replaced/retrained against different database
instances — a number quoted from an old section is not reliable as "the
current state" without checking here first.** This section is the one place
that gets updated in place (not appended-to-chronologically) as the
canonical numbers change. If you're a future session and about to cite a
statistic from this file in a prompt, script, or slide — use the numbers in
THIS section, not one found by searching the Day-by-day history below.

**Why this section exists:** 2026-09-03 investigation found the home Mac and
work PC had diverged (see "Cross-machine DB reconciliation" below) —
home Mac had independently re-run `synthetic.generator` rather than
restoring a transferred dump, producing a different (but business-column-
identical) dataset with entirely different invoice UUIDs. That, plus a real
survivorship-bias bug in recovery-model training (see below), made several
of this file's previously-"final" numbers wrong. Investigated, fixed, and
this DB is now the one canonical instance going forward.

**Database**: this work PC's local Docker Postgres (`receivables_ai`) is the
canonical instance, restored from the home Mac's 2026-09-02 dump. Alembic
head: `834e0783e3f1`. 9,900 invoices total: 391 OPEN (live pool, down from
900 — attribution's own write-back already flipped 509 of the original 900
to PAID over the course of the Day-5 experiment), 8,358 PAID, 1,151
WRITTEN_OFF. Of the PAID invoices, 509 were resolved via Day 5's attribution
write-back (`payments.method='attribution_simulation'`) — those are
correctly EXCLUDED from ML training population (see bug below), leaving a
9,000-invoice organic historical pool (matching Day 1's original generated
size exactly).

**Real bug found and fixed (2026-09-03): recovery/PTP/root-cause model
training had a survivorship-bias contamination.** `build_feature_table()`/
`build_ptp_table()` selected their training population by
`invoices.status IN (PAID, WRITTEN_OFF)` alone — but Day 5's attribution
write-back only EVER flips a formerly-live invoice to PAID when it
recovered (never-recovered ones stay OPEN forever). Once attribution has
run once, naively training on that status filter silently pulls in this
outcome-pre-filtered subset as real history, collapsing the most recent
time slice to 100% positive (confirmed: recovery model's test set was
417/417 recovered, ROC-AUC undefined, before the fix). This is a bug in
code that predates this session — nobody had ever retrained models against
a DB where attribution had already run before. Fixed via
`organic_historical_mask()` in `app/ml/features.py` (excludes any invoice
with an `attribution_simulation`-method payment from the top-level training
population; still valid as prior-history context features for OTHER
invoices — only invalid as the labeled training row itself). Committed as
`7197fe7 "fix recovery model survivorship bias from attribution write-back"`.

**Current model metrics** (retrained 2026-09-03 against the corrected
population — closely matches original Day-2-era numbers, confirming the fix
just restored the intended methodology rather than changing it):
- Recovery: n=1613 test, ROC-AUC=0.8339, PR-AUC=0.9240, Brier=0.1177, positive_rate=0.772.
- PTP: n=211 test, ROC-AUC=0.8350, PR-AUC=0.8899, Brier=0.1635, positive_rate=0.607 (unaffected by the bug — retrained anyway for artifact consistency).
- Root cause: n=1529 test, ROC-AUC=0.7577, PR-AUC=0.7063, Brier=0.1987, positive_rate=0.456.

**Current evaluation_snapshots** (refreshed 2026-09-03, `python -m
app.decision.persist_evaluation`, against the corrected models and a fresh
`final_integration_pass --persist` over the 391 open invoices): Baseline
net=₹9,871,714.28 (recovery_rate=31.84%), Decision engine
net=₹11,292,861.08 (recovery_rate=36.54%). **Net EV improvement:
+₹1,421,147.** (Supersedes every earlier-dated net-EV figure in this file.)

**Known caveat on today's decision distribution**: repeated pipeline reruns
during today's investigation exhausted Razorpay's test-mode payment-link
quota (hard cap, ~30 links) partway through. 77 of 391 invoices (19.7%)
whose real economics recommendation was PAYMENT_LINK show `wait` instead,
via the already-existing, correctly-working "tool failed twice → fall back
to WAIT, never guess a different channel" design (`app/agent/tools.py`) —
not a policy override, not a modeling error. Decided to leave as an honest,
correctly-labeled record rather than retry (retrying risks exhausting the
quota further with no guaranteed fix — see chat history for the full
reasoning). Action distribution from today's run: wait 176 (45.0%, ~77 of
these are the quota artifact above), voice 108 (27.6%), whatsapp 56 (14.3%),
stop 32 (8.2%), escalate 17 (4.3%), payment_link 2 (0.5%). All 7 automated
safety checks (no duplicate processing, no policy bypass, business-hours
compliance, no LLM calls outside promise extraction, no placeholder scores,
no hidden-ground-truth identifiers) pass.

**Attribution experiment (`attribution_experiment_results`/
`attribution_records`) — NOT recomputed on 2026-09-03, still exactly as
restored from the home Mac's dump** (computed_at 2026-09-02 18:15 UTC).
Deliberately left alone: redoing it requires a pre-attribution snapshot
(900 still-open invoices) that doesn't exist for this dataset instance —
attribution's own write-back already mutated 509 invoices to PAID, and
`app/attribution/DECISIONS.md` itself documents that rerunning against an
already-mutated population produces a different, non-comparable experiment,
not a "corrected" one. **Pooled result, 811 eligible invoices (404
treatment / 407 control) — POSITIVE on this dataset, correcting every
prior "-3.1%"/negative reference elsewhere in this file**:
- Amount-weighted: treatment 38.14% vs. control 31.53% → **+6.61pp** (incremental_net_recovery ≈ +₹1,370,293).
- Count-based (the statistically-tested one, per `app/attribution/DECISIONS.md`): treatment 64.85% vs. control 61.18% → **+3.67pp**, z≈1.08 (not significant at conventional thresholds, but positive, not negative).
- ESCALATE's aggregation-consistency check DOES still fire on this dataset (pooled +₹122,248 vs. archetype-stratified sum -₹3,639 — a genuine Simpson's-paradox-style sign disagreement) — `tests/test_api_attribution.py::test_get_attribution_with_diagnostics_includes_archetype_breakdown_and_warnings` passes as-is, no code change was needed (an earlier "pre-existing failure" note elsewhere in this file was true against a different, now-superseded database state).

**CUPED feasibility check run 2026-09-03** (against the numbers above, not
built yet — pending go-ahead): `Corr(base_probability, recovered)` = 0.557
→ 17.0% SE reduction on the count-based metric; `Corr(baseline_predicted_
recovery, observed_recovery)` = 0.465 → 11.5% SE reduction on the
amount-weighted metric. Both real, both matching the theoretical `1-√(1-r²)`
prediction almost exactly — passes the "worth building" bar from the
already-agreed plan (see "Attribution metric honesty fixes" section below).

**Test suite**: 304 passed / 3 failed, all 3 tracing to the single Razorpay
quota issue above (`test_agent_demo_parity.py::...[low_value_stop]`,
`test_seed_demo.py::test_reset_and_reassess_low_value_stop_passes_its_own_check`,
`test_seed_demo.py::test_seed_demo_end_to_end_reports_all_clear`) — expected
to clear once the quota resets and `seed_demo.py` is rerun.

**Cross-machine DB reconciliation (2026-09-03, full account)**: the home
Mac's local DB had diverged from this work PC's because it ran
`synthetic.generator` fresh rather than restoring a transferred dump —
confirmed via identical aggregate business data (9,900 invoices, ₹495.18M
total, byte-identical) but completely different invoice UUIDs.
`app/attribution/assignment.py`'s `assign_treatment_groups()` and
`simulate_outcomes.py`'s `draw_raw_outcomes()` both sort candidates by
`str(invoice_id)` before consuming a seeded RNG stream — deterministic
*given the same population*, but a different UUID set (from an independent
generator run) reorders that stream entirely, landing on a different
treatment/control split and a different sequence of recovery draws even
under the same `SEED`. `app/attribution/DECISIONS.md` had already stated
this precisely ("deterministic given the same seed" requires "the same
population") without anyone connecting it to the cross-machine case. This
work PC's DB was restored from the home Mac's dump (now canonical); the old
work-PC dataset instance's numbers throughout this file's earlier sections
no longer correspond to any live database.

## Repo layout

```
b2b-receivables-intelligence/
  README.md, .gitignore, CLAUDE.md          <- repo root
  backend/
    app/
      core/            config.py (pydantic-settings), db.py (SQLAlchemy engine/session/Base)
      models/          12 SQLAlchemy models + enums.py (see Schema below) -- case_embedding.py added Day 3
      ml/              Day-2 feature engineering + Recovery/PTP models -- see "Day 2: ML layer" below
        config.py        HORIZON_DAYS, recency windows, split ratios, calibration bounds, SEED -- no synthetic/ import
        features.py      DB->pandas, is_resolved_before(), rolling+recency features, outstanding_ratio,
                          build_live_feature_table() (Day 3 -- same helpers, live/open pool, widened
                          customer-invoice grouping incl. other live siblings, see Day 3 section)
        labels.py        recovery_label(), build_ptp_table(), T-reconstruction, class-balance diagnostics
        splits.py        Experiment A (time-based, 4-way) and B (customer-based) splits
        evaluate.py      classification_metrics(), reliability_table(), archetype_sanity_check()
        train_recovery.py  fit + isotonic-calibrate + evaluate recovery model, CLI entry
        train_ptp.py       fit + Platt-calibrate + evaluate PTP model, CLI entry
        persist.py         joblib save/load + FeatureSnapshot DB writer, CLI entry
        DECISIONS.md       evidence-backed modeling decisions log -- read this before changing any ML default
        artifacts/         gitignored -- .joblib models + metrics.json, regenerate via `python -m app.ml.persist`
      decision/        Day-3 decision intelligence -- see "Day 3: Decision intelligence layer" below
        config.py        intervention cost/uplift/friction/materiality assumptions (business judgment, not fit)
        economics.py     candidate actions, EV formula, ranking, materiality-gated recommend_action()
        policy.py        deterministic Policy/Safety Gate, 8-rule priority cascade, PolicyContext/PolicyVerdict
        service.py       Decision Service: live scoring + retrieval + economics + policy orchestration
        persist.py        writes decision_logs (append-only) + updates account_state (current snapshot)
        evaluation.py     baseline-vs-engine expected-value comparison, escalation-appropriateness diagnostic
      retrieval/       Day-3 hybrid retrieval -- see "Day 3: Decision intelligence layer" below
        build_case_corpus.py  synthesizes case-narrative text + fastembed embeddings -> case_embeddings table
        hybrid_search.py      BM25 + pgvector + structured-filter retrieval, RRF fusion, relevance diagnostics
      agent/           Day-4 LangGraph orchestration -- see "Day 4: LangGraph orchestration layer" below
        events.py            EventType enum (8 values incl. review.timeout) + Event dataclass (frozen, kw_only=True)
        state.py             GraphState (TypedDict, total=False) + ToolResult -- LangGraph silently drops any
                              undeclared key a node returns, hit twice (subtasks 4 and 9), watch for it on any new field
        state_machine.py     TransitionContext/StateTransition/determine_next_state() -- the ONLY place that
                              decides (current_state, event, ...) -> next_state; two-phase cascade, path contract
        tools.py             5 action/tool functions -- Decimal money, idempotent create_payment_link
                              (reference_id=str(invoice_id)), deterministic failure_mode seam on the 4 simulated ones
        resilience.py        call_with_retry() -- generic retry mechanism, NO fallback semantics baked in
                              (caller decides what "failure" means and what to do about it)
        promise_extraction.py  Groq (openai/gpt-oss-120b) promise extraction, wired through call_with_retry
        scanners.py           scan_for_review_timeouts()/scan_for_broken_promises() -- plain functions, no
                              scheduler; candidate account_state sets are disjoint by construction (asserted + tested)
        audit.py              build_decision_log()/build_account_state_updates() from GraphState -- defensive
                              across 3 state shapes (normal/promise-creation/invalid-event)
        nodes.py              all graph node functions (thin wrappers calling into decision/ml/retrieval/tools)
        graph.py              StateGraph wiring, 3 conditional edges, run_invoice(persist: bool = False)
        simulate_scenarios.py     narrated rehearsal script, the 6 named scenarios (python -m app.agent.simulate_scenarios)
        final_integration_pass.py  full-900-live-invoice pass + safety checks (python -m app.agent.final_integration_pass [--persist])
        DECISIONS.md          evidence-backed Day-4 decisions log -- read before touching agent/ defaults
    alembic/           migrations (env.py hand-authored, not `alembic init`-generated)
    synthetic/
      archetypes.py    8 archetypes' ground-truth parameters
      generator.py     deterministic dataset generator (SEED=42)
      validators.py    validation suite + dataset summary + reproducibility fingerprint
      demo_fixtures.py selects/pins 6 curated demo invoices -> demo_fixtures.json
    tests/             pytest suite, 222 total (118 from Days 1-3 + 104 new in Day 4)
    docker-compose.yml Postgres+pgvector container definition
    requirements.txt   Python deps (see exact versions below) -- now includes xgboost, scikit-learn (Day 2),
                        fastembed, rank-bm25 (Day 3), langgraph, groq, razorpay (Day 4)
    .env.example / .env (.env gitignored, never committed -- LLM_API_KEY and RAZORPAY_KEY_ID/SECRET,
                        staged blank since Day 1, are now filled in for real as of Day 4)
  frontend/            Next.js 16 + TypeScript + App Router, scaffolded Day 3 -- see "Day 3" section below.
                        No CSS framework installed (Tailwind deliberately skipped -- user's own design/CSS
                        pass comes later, Day 5/6). 3 screens against typed mock data mirroring real backend
                        shapes (lib/types.ts), no live API wiring yet.
```

## Environment (work PC)

- **Python 3.14.5**, venv at `backend/venv` (created via `python -m venv venv`, not `uv` — user's explicit preference despite `uv` being installed). Installed via `pip install -r requirements.txt`, not pinned in the committed `requirements.txt` (it lists bare package names) — actual installed versions, confirmed from `venv/Lib/site-packages/*.dist-info`:
  - fastapi 0.141.1, uvicorn 0.52.4, sqlalchemy 2.0.52, alembic 1.19.1, psycopg 3.3.4 (+psycopg-binary 3.3.4), pgvector (python pkg) 0.5.0, pydantic 2.13.4 / pydantic-settings 2.15.0, python-dotenv 1.2.3, pandas 3.0.5, numpy 2.5.2, faker 40.37.0, pytest 9.1.1.
  - Day 2 additions: xgboost 3.4.1, scikit-learn 1.9.0.
  - If reinstalling, prefer running `pip freeze > requirements.txt` afterward to lock these for real reproducibility — hasn't been done yet, so the checked-in file stays intentionally unpinned for now.
- **PostgreSQL 18.4** also runs natively as a Windows service on port **5432** — this project does **not** use it. Native Postgres has no pgvector available for Windows (no official binary, and this machine has no Visual Studio/C++ build tools to compile it from source).
- **This project's Postgres runs in Docker instead:** container `receivables-postgres`, image `pgvector/pgvector:pg16` (reused an already-cached image from an unrelated prior project rather than pulling pg18 — pgvector 0.8.2 either way), host port **5433**, db `receivables_ai`. `docker-compose.yml` pins `name: b2b-receivables-intelligence` explicitly so running compose commands from `backend/` doesn't derive a different project name and orphan the container/volume.
- **Git identity:** local repo config overrides to personal (Jeet Patel / jeetpatel2506@gmail.com); global git identity stays the work identity so other (work) repos on this machine are unaffected. SSH remote uses a dedicated `github-personal` host alias with its own key.
- **pgAdmin 4** is bundled at `C:\Program Files\PostgreSQL\18\pgAdmin 4`. Connect to this project's DB with host `localhost`, port `5433`, db `receivables_ai`, user/pass `postgres`/`postgres`.
- **Node.js v22.17.1 / npm 10.9.2** confirmed available (Day 3, for the frontend). `frontend/` was scaffolded via `create-next-app` directly (not handed to the user to run — boilerplate generation, not a dependency judgment call, unlike the Python ML installs which are always handed over per the working-style rule below). Exact scaffolded versions: `next` 16.3.3, `react`/`react-dom` 19.2.8, TypeScript ^5, ESLint ^9 — App Router, no Tailwind (deliberately skipped, see Day 3 section).
- **LangGraph 1.2.11 + groq 1.7.0 confirmed working on Python 3.14.5** (Day 4) — checked live before relying on it, not assumed: LangGraph's own upstream had (and may still have) an open issue about incomplete 3.14 CI coverage, and `langgraph-cli` specifically has known install failures on 3.14 due to a PyO3 version cap. Neither package nor its dependency chain hit that in practice here. `razorpay` (Python SDK) installed with no issues (pure HTTP client, no compiled extensions).

## How to resume work

```powershell
cd backend
venv\Scripts\Activate.ps1
docker start receivables-postgres        # if not already running
alembic upgrade head                      # if models changed since last session
pytest -v                                 # confirm everything still passes
```

To regenerate the dataset from scratch (safe — truncates and rebuilds atomically):
```powershell
python -m synthetic.generator
python -m synthetic.demo_fixtures
python -m synthetic.validators
```

To rerun the Day-2 ML pipeline (read-only against the dataset above, safe to rerun anytime):
```powershell
python -m app.ml.labels           # horizon/class-balance diagnostics + PTP class-balance report
python -m app.ml.splits           # split size/date-range diagnostics for both tables
python -m app.ml.train_recovery   # trains + calibrates + evaluates + archetype sanity check
python -m app.ml.train_ptp        # same, for PTP
python -m app.ml.persist          # retrains both, saves .joblib + metrics.json, writes FeatureSnapshot rows
```

To rerun the Day-3 decision-intelligence pipeline:
```powershell
python -m app.retrieval.build_case_corpus   # rebuild the case_embeddings corpus (needed once; ~9,000 rows, one-time fastembed model download on first run)
python -m app.retrieval.hybrid_search       # archetype-cohesion relevance diagnostic (larger sample than the pytest version)
python -m app.decision.service              # full 900-live-invoice decision pass, prints action/policy distribution (read-only, safe to rerun anytime)
python -m app.decision.evaluation           # baseline-vs-engine comparison + escalation-appropriateness diagnostic (read-only)
python -m app.decision.persist              # WRITES: runs the full pass and persists to decision_logs + account_state -- not yet run for real across all 900, only tested on one invoice; consider whether you want this run before Day 4, since it overwrites account_state's Day-1 placeholder scores permanently until reset
```

To run the Day-3 frontend scaffold (mock data only, no backend wiring yet):
```powershell
cd frontend
npm install    # only if node_modules isn't already present
npm run dev    # http://localhost:3000, redirects to /invoices
```

To rerun the Day-4 agent layer (all read-only/non-destructive by default -- persistence is opt-in, see below):
```powershell
pytest tests/test_agent_contract.py tests/test_agent_graph.py tests/test_agent_demo_parity.py tests/test_state_machine.py tests/test_tools.py tests/test_resilience.py tests/test_promise_extraction.py tests/test_scanners.py tests/test_reassessment_loop.py tests/test_audit.py -v
                                             # full Day-4 pytest suite (104 tests) -- some require LLM_API_KEY, skip gracefully if unset
python -m app.agent.simulate_scenarios      # narrated rehearsal script, the 6 named scenarios -- WRITES real decision_logs/account_state rows for the invoices it touches (accepted side effect, same precedent as test_decision_persist.py)
python -m app.agent.final_integration_pass          # dry run (persist=False) -- distributions + safety checks against the full 900-invoice live pool, read-only
python -m app.agent.final_integration_pass --persist  # the real, permanent write -- already run once for real as of Day 4 (see checklist below); rerunning is idempotent-safe but will re-overwrite account_state/decision_logs for all 900 again
```

## Schema (11 tables — architecture doc §4)

`merchants`, `customers`, `invoices`, `payments`, `payment_promises`, `interactions`, `recovery_actions`, `decision_logs`, `account_state`, `attribution_records`, `feature_snapshots`. All UUID primary keys (Python-generated via `uuid.uuid4()`, **explicitly set at construction time** — see gotcha below). Full column-by-column breakdown was given in-session; the model files in `backend/app/models/` are the authoritative source now.

Notable deviations/additions beyond the doc's literal field list (all deliberate, confirmed with user):
- `invoices.invoice_number` — human-readable label (`INV-1042`) for demo/dashboard legibility; UUID stays the real key.
- `invoices.true_root_cause` — synthetic-only ground truth (`cash_flow_stress`/`dispute`/`oversight`), added via a second migration, supports a future root-cause classification stage implied by the pitch ("decides ... *why* it's late").
- `customers.archetype`, `true_recovery_probability`, `true_promise_keep_probability` — synthetic-only ground truth, hidden from ML models, used only by the generator/validators.
- `account_state` and `attribution_records` use `invoice_id` as their primary key (1:1 per invoice) since the doc's own field list for those two tables never included a separate `id`.
- Enums beyond the doc's explicit ones: `payments.status`, `recovery_actions.action_type` (WAIT/EMAIL/WHATSAPP/PAYMENT_LINK/VOICE/ESCALATE/STOP — from architecture §3), `recovery_actions.policy_result` (allowed/blocked/escalated). Doc-explicit enums: `invoices.status`, `payment_promises.status`, `account_state.current_state` (full §9 state machine), `attribution_records.treatment_group`.
- `account_state.current_state` gained two values in Day 3 (`CLOSED_PAID`, `CLOSED_ABANDONED`) — the Policy Gate's `STOP` action covers two semantically different outcomes (already paid vs. expected value too small to pursue) that would otherwise collapse into one indistinguishable `CLOSED`. Plain `CLOSED` is kept unused for now. Day 4 added a seventh value, `DISPUTE_REVIEW` — a disputed invoice needs its own visible status distinct from generic `WAIT` so the dashboard can show "needs human dispute resolution" as its own bucket; by rule priority in `determine_next_state()`, this absorbs every subsequent event for a disputed invoice except full payment, a materially sticky/terminal-ish state in practice (see `app/agent/DECISIONS.md`). Full current value set: `OVERDUE, ASSESSMENT, WAIT, REMIND, ESCALATE, PROMISE, MONITORING, KEPT, BROKEN, REASSESS, CLOSED, CLOSED_PAID, CLOSED_ABANDONED, DISPUTE_REVIEW` — `ASSESSMENT` and `MONITORING` remain defined but never actually produced by any Day-4 rule (see Day 4 section below).
- pgvector: `case_embeddings` table (Day 3, own migration, 384-dim `Vector` column via the `pgvector` python package) — one row per historical (paid/written_off) invoice, a synthesized case-narrative text + its embedding, for hybrid BM25+vector retrieval. Not in the master doc's literal table list, same kind of deliberate addition as `invoice_number`/`true_root_cause`.
- `payment_promises` now has real rows for the live pool as of Day 4 (previously a genuine blank slate) — written by `app/agent/nodes.py`'s `_upsert_open_promise()` whenever a live customer's response extracts a real promise. Upsert, not insert: never more than one `OPEN` promise per invoice at a time, by construction.

Migrations (7 total, all applied): `f77b57a510b7_initial_schema.py` (all 11 original tables), `f53cb24488a8_add_invoice_root_cause.py`, `5d6cc313aeb7_add_case_embeddings_table.py` (Day 3), `2f4bc391a33c_add_closed_paid_and_closed_abandoned_.py` (Day 3, see below), `b7fa2b3a4acb_fix_account_current_state_enum_labels_.py` (Day 3 — corrective, see below), `a3f9c1d84e27_add_dispute_review_account_state.py` (Day 4 — added the uppercase label directly, gotcha already known going in, no corrective follow-up needed this time). Verified via psql `\dt` and pgAdmin at each step.

**Gotcha found in Day 3, worth remembering for any future enum change:** `account_current_state_enum = SAEnum(AccountCurrentState, name=...)` has no `values_callable`, so SQLAlchemy's default `Enum` type stores each Python enum member's **NAME** (`'OVERDUE'`, `'WAIT'`, ...), not its `.value` — confirmed by querying `pg_enum` directly. A migration that adds new enum values as lowercase `.value` strings will silently mismatch and fail with `InvalidTextRepresentation` on the first real ORM write. Always add new enum labels as the uppercase member name to match the existing convention in this specific enum (other enums may differ — check `pg_enum` before assuming).

## Synthetic dataset (Day 1's centerpiece — everything later grades against this ground truth)

**Scale:** 15 merchants, 600 customers, 9,900 invoices total, split into two pools:
- **Historical/closed pool** (9,000 invoices: 7,849 paid + 1,151 written-off) — fully resolved, full generated history (recovery_actions/promises/interactions/payments), trains Day-2 models and fills the retrieval corpus. Issue dates span a 12-month window ending 11 months before the dataset's fixed reference date, guaranteeing every invoice has had time to fully resolve (even the slowest case: 120-day terms + 180-day written-off wait ≈ 10 months).
- **Live/open pool** (900 invoices, all currently overdue, `status='open'`) — unresolved, no history yet (blank slate), except the already-paid-false-alarm archetype which gets a real `payments` row. This is what the live decision engine / demo / Day-5 attribution holdout actually operates on.
- Fixed reference date: `REFERENCE_DATE = date(2026, 8, 27)` in `generator.py` — hardcoded (not `date.today()`) so the dataset is identical regardless of what day the script runs, which is required for the reproducibility check.
- `SEED=42` throughout. **Caveat:** primary keys use `uuid.uuid4()`, which is NOT seeded by Python's `random` module — reruns produce different UUIDs but identical business data. The reproducibility check (`python -m synthetic.validators --fingerprint`) hashes only business columns for exactly this reason; confirmed byte-identical across two runs.

**8 archetypes** (`synthetic/archetypes.py`) — population share / organic recovery probability / promise-keep probability / typical delay:

| Archetype | Share | Recovery | Promise-keep | Delay |
|---|---|---|---|---|
| reliable_payer | 20% | 0.95 | 0.95 | 2–5d |
| slightly_late | 20% | 0.85 | 0.80 | 10–20d |
| chronic_late | 15% | 0.55 | 0.45 | 40–70d |
| promise_keeper | 10% | 0.60 | 0.90 | varies |
| promise_breaker | 10% | 0.50 | 0.20 | varies |
| strategic_enterprise | 10% | 0.90 | 0.75 | 60–90d |
| cash_constrained | 10% | 0.45 | 0.55 | varies, partial payments |
| already_paid_false_alarm | 5% | ~1.0 | n/a | n/a |

Each archetype also has: an amount lognormal distribution (₹5k–₹5L bounds, skewed larger for strategic_enterprise, smaller for reliable/slightly-late), per-action recovery-uplift/delay-reduction effects (EMAIL/WHATSAPP/PAYMENT_LINK/VOICE/ESCALATE), and a cash_flow_stress-vs-oversight root-cause weighting (dispute is a flat 6% across ALL archetypes, applied before this split).

**Two fixed mechanisms worth remembering:**
- **Written-off rule:** unpaid + no kept promise + historical window's own time-elapsed guarantee (150–180 day range) → `status=written_off`. No separate runtime check needed since the historical window's construction already ensures enough time has passed.
- **Already-paid false alarm (fixed mechanism, not naive):** generates a real `payments` row (correct invoice_id/amount, dated before "today", `status=completed`) but deliberately leaves `invoices.status='open'` and `paid_at=NULL`, with `account_state.current_state='overdue'`. Models "the ledger event happened but the invoice record hasn't been reconciled yet" — keeps referential integrity intact while giving the Policy Gate's already-paid check something real to catch (it must cross-reference `payments` directly, not trust `invoices.status`). Only appears in the live pool, not historical, since it's a live phenomenon.

**Demo fixtures** (`synthetic/demo_fixtures.py` → `demo_fixtures.json`): 6 curated invoices pinned by `invoice_number`, selected from the live pool — reliable_payer→WAIT, chronic_late→ESCALATE, promise_breaker→REASSESS, low_value→STOP, high_value(chronic_late)→ACT, already_paid_false_alarm→STOP/SUPPRESS. Re-running the generator + demo_fixtures script re-pins these deterministically.

## Validation suite (`synthetic/validators.py`)

Checks the **current database state**, not generator internals — 7 checks (referential integrity/orphans, temporal consistency, business rules, duplicates, missing values, amount/date bounds, archetype presence within tolerance), a dataset summary, and the fingerprint reproducibility check. All passing as of last run. Also reused directly by the pytest suite (`tests/test_synthetic_generator.py::test_validation_suite_passes_on_generated_dataset`) rather than duplicating the checks.

## Known gotchas / bugs already hit and fixed

1. **Alembic autogenerate + a Postgres enum shared across two tables** (`action_type`, used by both `recovery_actions` and `account_state`) generates a `CREATE TYPE` in both tables' `op.create_table()` blocks — the second one must be edited to `postgresql.ENUM(..., create_type=False)` or it errors with `DuplicateObject`. Already fixed in the initial migration; watch for this again if a shared enum gets used on a third table later.
2. **SQLAlchemy `default=uuid.uuid4` on a PK column is only invoked at flush/insert time, not at Python object construction.** The generator builds the whole in-memory object graph before any flush and wires up FKs via `.id` immediately — so `Merchant`/`Customer`/`Invoice` must be constructed with an explicit `id=uuid.uuid4()`, or every downstream FK reference silently reads `None`.
3. **No ORM `relationship()` objects are defined between models** (plain FK columns only) — this project relies on `session.flush()` calls between dependency stages (merchants → customers → invoices → everything else) in `generator.py` to guarantee insert order, since automatic dependency-sorting wasn't reliable without them.
4. Port **5432 is native Postgres, 5433 is this project's Docker Postgres** — don't confuse them when running psql/pgAdmin/connection strings.
5. **A `str, enum.Enum` column mapped with plain `SAEnum(SomeEnum, name=...)` (no `values_callable`) stores each member's `.name` in Postgres, not its `.value`.** Confirmed by querying `pg_enum` directly: `account_current_state` holds `'OVERDUE'`, `'WAIT'`, etc. (uppercase), not `'overdue'`/`'wait'`. A migration that adds a new enum label as the lowercase `.value` string will silently mismatch what the ORM actually writes/reads, failing with `InvalidTextRepresentation` on the first real write (hit when adding `CLOSED_PAID`/`CLOSED_ABANDONED` in Day 3 — fixed with a corrective migration adding the uppercase labels; the orphaned lowercase ones are harmless, Postgres can't drop enum values without rebuilding the type). Check `pg_enum` before adding a value to any enum in this project — don't assume `.value` is what's stored.
6. **A bare `datetime(year, month, day, tzinfo=timezone.utc)` literal defaults to midnight UTC — 5:30am IST** for this India-focused product, which is before any 9am-start business-hours check. Hit in Day 3: `app/decision/service.py`'s `DEFAULT_AS_OF` silently blocked every `VOICE`/`ESCALATE` recommendation across the entire 900-invoice batch pass because of this, found only by inspecting the actual full-scale run's output (a unit test with a hand-picked business-hours timestamp wouldn't have caught it). Any new "current moment" reference timestamp in this project should be constructed in IST directly (`datetime(..., tzinfo=IST)`, not `timezone.utc`) and checked against `is_business_hours()` if it's going to drive a business-hours-gated decision.
7. **LangGraph silently drops any state key a node returns that isn't declared in the state schema (`GraphState` TypedDict) — no error, the key just vanishes.** Hit twice in Day 4: once in subtask 2 (`prior_contact_count`/`days_since_last_contact` were used by nodes before being added to `GraphState`, causing a `KeyError` two nodes downstream instead of at the source), once in subtask 4 (`state_transition_path` needed adding proactively once the mistake pattern was recognized). Any new field a node needs to pass forward must be added to `GraphState` in `app/agent/state.py` *before* a node starts returning it, not after something downstream fails.
8. **`Event` (`app/agent/events.py`) is `@dataclass(frozen=True, kw_only=True)` — every field must be passed by keyword, positional construction raises immediately.** Hit while writing `app/agent/simulate_scenarios.py` (subtask 10) — every `Event(EventType.X, invoice_id, timestamp)` call failed until rewritten as `Event(event_type=..., invoice_id=..., occurred_at=...)`. Deliberate design choice (subtask 1), not a bug — just easy to forget when writing a new call site.
9. **XGBoost's `predict_proba()` returns `float32`, and `IsotonicRegression.predict()`/`LogisticRegression.predict_proba()` both preserve that precision rather than upcasting — so `np.clip()` (which preserves input dtype) was clipping in float32, not float64.** `float32(0.99) != float64(0.99)`, so a probability clipped to the float32 ceiling, once widened via `float(...)`, could land ~1e-8 outside the documented `[0.01, 0.99]` bounds. Found via Day 4's Subtask 11 full-integration safety check (a strict full-precision bounds comparison other tests never happened to do), affecting 74/900 live invoices. Zero practical effect on any decision (an EV shift of `1e-8 * amount` is nowhere near the ₹50 materiality floor) — fixed anyway by casting to `float64` before the clip in both `app/ml/train_recovery.py` and `app/ml/train_ptp.py`'s `calibrated_predict_proba()`. No retraining needed — pure post-processing fix, the trained model/calibrator artifacts are untouched. See `app/ml/DECISIONS.md`.

## User's working-style preferences for this project (important — apply without being re-told)

- **Never `git commit`/`push` unless explicitly asked.** Write/edit code, report what changed, stop.
- **Commit messages: short and plain** (e.g. "db schema and synthetic data creation code written"), not multi-paragraph.
- **Hand over install/setup commands as text for the user to run themselves** (venv creation, `pip install`, `alembic upgrade`, running the generator) rather than executing them directly — the user runs them and reports output/errors back.
- **One step at a time** — implement a discrete piece, stop, let the user check/run it, then continue to the next.
- Plain `python -m venv venv` + `pip install -r requirements.txt` workflow, not `uv` (even though installed).
- **Main-task workflow (plan → approve → code → report)**, for any substantial/main task (e.g. a feature-engineering module, a model-training script, a splits implementation — not small mechanical steps like installing a dependency or scaffolding an empty package):
  1. Present a short design plan in chat (what will be built, key definitions/decisions, function/file shape) *before* writing any code.
  2. Wait for explicit user approval — do not write the main code on an ambiguous "ok" that's really just acknowledging the process, if it's unclear whether the plan itself was approved, ask.
  3. After the code is written, report: which files were added/changed and what each one's main contents/responsibilities are, then what (if anything) the user needs to run manually, and what tests to run/review.
  - Small tasks (installs, trivial scaffolding, one-line config edits) skip this — just do them and report briefly.

## Day 2: ML layer (`backend/app/ml/`) — complete

Turned the 9,000-invoice historical pool into a leakage-safe feature table and trained two calibrated XGBoost models: **Recovery Probability** (will this invoice pay back within a horizon?) and **Promise-to-Pay / PTP** (will a given payment promise be kept?). Full design rationale, every evidence-backed decision, and every bug found is in **`backend/app/ml/DECISIONS.md` — read it before changing any ML default**; this section is a summary, not a replacement.

**Methodology (both models):**
- **Point-in-time safety**: every feature is computed strictly as of a cutoff — `due_date` for recovery, `T` (reconstructed promise-creation moment, `T = max(recovery_actions.timestamp)` for that invoice — exact given the generator's construction, not an approximation) for PTP. `is_resolved_before()` in `features.py` is the single mechanism enforcing this; a written-off invoice only counts as "known" 150 days past its own due date (conservative bound), a paid one only once `paid_at < cutoff`.
- **Two experiments, not one**: Experiment A (time-based: months 1–9 train / 10–11 test, boundary derived dynamically from the data's own date range, never hardcoded) is the calibrated, production-relevant split. Experiment B (customer-based: 80/20 seeded customer split, no customer overlap) measures generalization to a customer never seen in training — deliberately uncalibrated (scope cut) and consistently shows a larger fit-vs-test gap than A, which is the *expected*, correct finding (unseen-customer generalization is a harder task), not a bug.
- **`app/ml/DECISIONS.md` covers**, in evidence-backed detail: why `HORIZON_DAYS=60` (not the original 90 — checked against real data, plus a genuine business rationale), why the class-balance gate applies only to the pooled rate (per-archetype imbalance is by construction — `reliable_payer` etc. are *designed* to be extreme), why `scale_pos_weight` was dropped (controlled comparison showed it hurts calibration-relevant metrics with zero ranking benefit), why calibrated probabilities are clipped to `[0.01, 0.99]` (isotonic regression can output literal 0.0/1.0 on a sparse calibration tail — confirmed live, catastrophic under log loss, and this probability feeds Day 3's `EV(a) = P(recovery)*Amount - Cost - Friction` where a literal 0/1 is a correctness bug, not just a metric artifact), and a real bug found + fixed (`customer_invoice_frequency` exploding to millions for the ~14% of rows where a customer's `relationship_start_date` — drawn independently of `issue_date` in the Day-1 generator — falls after an invoice's own cutoff; both affected features are now `NaN` in that case, not a fabricated number).

**Final numbers** (Experiment A test set unless noted; see `DECISIONS.md` for the full tables):
- **Recovery**: A raw/calibrated ROC-AUC ≈0.829, PR-AUC ≈0.92, Brier ≈0.116-0.117; B (unseen customers) ROC-AUC ≈0.803. `amount` and `prior_avg_delay_days` dominate feature importances in both experiments.
- **PTP**: A raw/calibrated ROC-AUC ≈0.835, PR-AUC ≈0.89; broken-promise detection at threshold 0.5: precision 0.767, recall 0.554, F1 0.643; B ROC-AUC ≈0.808.
- **Archetype sanity check** (predicted vs. observed vs. hidden ground truth, both models): recovery's table is fully explained — 6/7 archetypes show intervention-uplift (observed/predicted above the organic constant, expected), `strategic_enterprise` is low because its 60-90d organic delay falls mostly outside the 60-day horizon (also expected, logged). PTP has one genuine, investigated-not-guessed limitation: `promise_breaker`'s keep rate is overpredicted (0.40 vs. true 0.20) because the model's dominant feature (`prior_avg_delay_days`) doesn't flag this archetype while the feature that would (`prior_promise_kept_rate`) is under-weighted and ~22% missing — the direct cost of correctly excluding `confidence_score` (a near-direct leak of the ground truth). Logged as a known limitation, not fixed, on explicit instruction.

**Testing**: 30 pytest tests total (12 from Day 1 + 18 new), across `test_ml_features.py`, `test_ml_labels.py`, `test_ml_splits.py` — includes the full leakage-critical guard set: `is_resolved_before` correctness, same-invoice self-exclusion, future-event regression (build a feature vector, insert a row dated after the cutoff, recompute, assert byte-identical — for both the recovery and PTP cutoff paths), T-reconstruction correctness (row-level, not aggregate), and the `customer_invoice_frequency` bug's regression test. All green.

**Explicitly skipped/deferred**: expected-payment-date regression (a third, separate model — nothing downstream depends on it) skipped outright. SHAP (richer per-prediction explanations, on top of the `feature_importances_` already exported unconditionally by both training scripts) deferred as optional — do only if there's spare time later, not required for Day 3+.

**Customer-level split (Experiment B) and time-based holdout (Experiment A)** — the two ML methodology requirements specified before Day 2 started — are both implemented exactly as designed above, in `splits.py`.

## Day 3: Decision intelligence layer (`backend/app/decision/`, `backend/app/retrieval/`) — complete

Built the full deterministic decision path — Economics Engine, hybrid retrieval, Policy/Safety Gate, Decision Service, state/audit persistence, evaluation — plus the frontend scaffold. **No LLM anywhere in this path** (confirmed via grep across `app/` and `requirements.txt`); that's Day 4's LangGraph layer. Full design rationale for every subtask is in the session transcript; this is a summary of what exists and the decisions that would surprise a future session.

**Economics Engine** (`app/decision/economics.py` + `config.py`): `EV(a) = P(recovery|a) * Amount - Cost(a) - Friction(a)`, `P(recovery|a) = base + uplift[a]*(1-base)` (diminishing returns). `INTERVENTION_COST_INR`/`ACTION_UPLIFT`/`FRICTION_BASE_INR` are **deliberate business assumptions, not fit from data and not read from `synthetic/archetypes.py`'s hidden ground truth** — that table is the answer key the whole benchmark is graded against; production code echoing it (even in aggregate) would defeat the point. Day 5's Attribution Engine is meant to validate/correct these assumptions against the randomized holdout — **see the pinned project memory `project_day5_attribution_must_close_the_uplift_gap`: Day 5 must actually update `ACTION_UPLIFT` from the holdout result, not just report the gap, or the "here's what we assumed vs. what we measured" narrative doesn't land.**
- `STOP` is never an Economics Engine candidate (Policy Gate's decision only).
- `recommend_action()` applies a **materiality threshold** (`max(₹50, 1% of amount)`) on top of raw EV ranking — without it, any near-zero-cost action with positive uplift (`PAYMENT_LINK`) mathematically beats `WAIT` for almost any realistic invoice amount, making abstention never fire. `rank_actions()` itself stays raw-EV-sorted for the explainability screen.
- **Two real bugs found via an actual full-900-invoice run, not caught by unit tests alone**: (1) `WHATSAPP`/`EMAIL` were strictly dominated by `PAYMENT_LINK` on both cost and uplift simultaneously, mathematically unwinnable — fixed by raising `WHATSAPP`'s uplift with a stated mechanism justification (personal touch drives *engagement*, a payment link only reduces *friction* for someone already intending to pay); `EMAIL`'s dominance was left as an accepted, defensible finding, not force-fixed. (2) `PAYMENT_LINK` then dominated across nearly the whole realistic amount range in turn — accepted as a real, explainable pattern (larger invoices justify progressively more assertive channels) rather than re-tuned further, to avoid curve-fitting the config toward an arbitrary "all 6 should fire" target.

**pgvector + hybrid retrieval** (`app/retrieval/`): `case_embeddings` table (own migration, 384-dim), one row per historical invoice — a synthesized case-narrative text (reusing Day 2's `build_feature_table()` verbatim for the point-in-time-safe fields, plus this invoice's own hindsight action/outcome — safe because corpus rows are never used to predict themselves, only indexed for a *different* invoice's query) embedded via `fastembed` (ONNX runtime, no torch — lighter install than `sentence-transformers`). Retrieval combines three independent rankings — vector cosine similarity, BM25 keyword overlap, and log-amount proximity (added as its own ranking because general text embeddings don't reliably encode numeric magnitude) — via **Reciprocal Rank Fusion** over a segment/industry/dispute-aware candidate pool with a fully-specified relaxation cascade. Dispute-awareness reuses `invoices.true_root_cause` via a join, no new column. **Relevance verified two ways**: a strict self-retrieval-at-rank-1 test, and an archetype-cohesion diagnostic (hidden ground truth, verification-only) showing **2.00x the random baseline** — with `exclude_invoice_id` required in the diagnostic specifically to avoid a case trivially retrieving itself and inflating the number for a reason unrelated to real retrieval quality.

**Policy/Safety Gate** (`app/decision/policy.py`): 8 rules, fixed priority order, first match wins — already-paid (cross-references `payments` directly, never trusts `invoices.status`, per the `already_paid_false_alarm` archetype's whole purpose) → disputed+`ESCALATE`/`VOICE` → low-pursuit-value `WAIT`→`STOP` conversion (**disputed invoices are exempt** — a legitimate dispute needs resolution regardless of size, `STOP` would mean giving up on investigating it, a different and larger decision) → max contact attempts → cooldown → business hours (`VOICE`/`ESCALATE` only; IST, Mon–Sat 9am–7pm) → large-amount-`ESCALATE` human-approval routing → allowed. `detect_dispute()` reading `true_root_cause` is a **different category of read than the hidden-ground-truth fields Day 2 excludes** — the test that matters is whether a field has a real-world analogue a production system could observe (a dispute is a real business fact a real system would eventually learn) vs. whether it's a pure simulation parameter that only exists to define the outcome being predicted (`archetype`, `true_recovery_probability` — no real-world analogue at all). Full reasoning is in `detect_dispute()`'s docstring.

**Deterministic Decision Service** (`app/decision/service.py`): `build_live_feature_table()` (new, in `app/ml/features.py`) mirrors Day 2's feature construction for the live/open pool, cutoff=`due_date` (same reference frame the model trained on — scoring "as of the day it became due" stays valid regardless of how much real time has since passed). Its customer-invoice grouping is deliberately widened to include other live siblings, not just historical ones — traced safe against re-leaking (`prior_resolved_invoices` structurally excludes anything not PAID/WRITTEN_OFF regardless of dates; `prior_issued_invoices` only ever checks `issue_date < cutoff`) and proven with a direct adversarial test, not just the trace. Single-row categorical scoring through the trained XGBoost model was **empirically confirmed safe** (not assumed) before relying on it — verified predictions match exactly whether a row is scored alone or in full context. **No PTP model wired yet**: the live pool is a genuine blank slate (zero `payment_promises` rows), so promise credibility doesn't apply until Day 4 creates one.
- **Real bug found via the actual full-900 run**: `DEFAULT_AS_OF` defaulted to midnight UTC = 5:30am IST, before business hours — silently blocking every `VOICE`/`ESCALATE` recommendation regardless of merit for the entire batch. Fixed to noon IST; must stay a hardcoded literal matching `synthetic/generator.py`'s `REFERENCE_DATE` (`date(2026, 8, 27)`, not imported — see the no-synthetic-dependency rule), with an automated drift-detection test (asserts consistency against the live pool's actual date range) as insurance against future silent disagreement.

**State/audit persistence** (`app/decision/persist.py`): `decision_logs` is append-only (each assessment is a new row); `account_state` is a current-snapshot overwrite. Replaces Day 1's seed-time placeholders — `recoverability_score`/`promise_score` were literally `archetype.organic_recovery_probability`/`promise_keep_probability` + noise (the hidden ground truth itself, found while building the Decision Service) — with real model output and a documented `0.0` "not applicable yet" sentinel respectively. `revenue_at_risk` redefined from Day 1's flat "full invoice amount" to `amount * (1 - base_probability)` (probability-weighted, gross — algebraically equals `amount - EV(WAIT)`, **not** comparable to any actionable candidate's EV, which nets cost/friction). Checked, not assumed: `synthetic/validators.py`'s `dataset_summary()` sums this field; no test hardcodes an expected value, but the printed number will legitimately decrease as more live invoices get processed.

**Evaluation** (`app/decision/evaluation.py`): baseline ("email everyone", no policy gate at all) vs. engine, both using the *same* recovery-probability estimates so the comparison isolates the value of the decision-intelligence layer itself. **Explicitly an expected-value comparison, not a real-outcomes comparison** — the live pool is unresolved; that comparison is Day 5's randomized-holdout Attribution Engine. Full 900-invoice result: net expected recovered ₹23,346,218 (engine) vs. ₹20,947,129 (baseline) — **+₹2.4M improvement**, recovery rate 51.5% vs. 45.9%, 457 unnecessary interventions avoided. Escalation-appropriateness diagnostic (hidden ground truth, verification-only) found only 22.9% of `ESCALATE` decisions go to the true-high-uplift archetype (`chronic_late`) while 61.4% go to `strategic_enterprise` specifically, whose true `ESCALATE` uplift is 0.00 — their invoices are just large enough (mean ₹222K) that the *assumed* flat uplift looks EV-positive regardless. Kept as an honest, visible finding tied directly to the flat-uplift assumption above, not smoothed over.

**Frontend scaffold** (`frontend/`): Next.js 16 + TypeScript + App Router, `create-next-app`-scaffolded, no Tailwind (design pass deferred to Day 5/6 per user's explicit instruction). 3 screens per the master doc: invoice list, explainability/decision-trace (click-through, all 5 sections — root cause, recoverability score, candidate-action EV table, retrieved cases, policy check + chosen action), metrics comparison. `lib/types.ts` mirrors the real backend `Decision`/`DecisionLog`/`EvaluationSummary` shapes field-for-field (string enums matching Python `.value`s exactly) so Day 6's live-data wiring is a data-source swap, not a reshape. `lib/mockData.ts`'s metrics numbers are the **real** subtask-7 evaluation output, not fabricated. `InvoiceSummary.treatment_group` reserved (optional, undefined) for Day 5's control-group assignment — decided now that it should be shown per-invoice for transparency/debugging, not just aggregated on the metrics page.

**Final integration pass**: the 6 Day-1 demo scenarios run through the real pipeline — 5 match their Day-1 expectation directly; `promise_breaker_reassess` correctly produces an initial action rather than `REASSESS` (that label anticipated Day 4's post-promise-broken state machine, not applicable yet on a blank-slate invoice); `low_value_stop`'s pinned invoice (exactly `AMOUNT_MIN`, ₹5,000, predicted 50% recovery probability) gets a cheap `WHATSAPP` nudge rather than `STOP` — checked directly and left as the honest answer (EV(WAIT)=₹2,500 narrowly exceeds the ₹2,000 pursuit floor, and the nudge has a genuine +₹159 margin) rather than retuning the threshold to force the Day-1 label, which predates the real economics. **118 tests total** (30 from Day 1–2 + 88 new), all passing, full suite ~4 minutes.

## Day 4: LangGraph orchestration layer (`backend/app/agent/`) — complete

Wired a real LangGraph agent on top of Day 3's deterministic core — the graph orchestrates existing `decision`/`ml`/`retrieval` functions, it never reimplements them. Full evidence-backed rationale for every decision below is in **`backend/app/agent/DECISIONS.md` — read it before touching any Day-4 default**; this section is a summary. Split into 11 subtasks, each reviewed and corrected before merging (several real bugs were caught this way, not after the fact) — see "bugs found" below.

**Event/state contract** (`events.py`, `state.py`): 8 event types including `review.timeout` (a purely time-based event, sourced by a scanner, not externally triggered — see below). `GraphState` is a `TypedDict(total=False)`, deliberately holding Day-3's real dataclasses (`ActionEV`, `PolicyVerdict`, `RetrievedCase`) unmodified rather than re-flattening them. **Core architectural decision: one graph invocation = one event** — a multi-step story like "overdue → promise → broken → reassess" is modeled as separate graph runs over time, with `account_state.current_state` (persisted) carrying continuity between them, not one long-lived graph holding a queue in memory. **Idempotency/deduplication is explicitly out of scope** — no event-ID-based dedup; reprocessing the same event twice is designed to be operationally *safe* (not actively *prevented*), which is a meaningfully weaker guarantee worth remembering (duplicate events do produce duplicate `decision_logs` rows once persistence is on).

**Graph topology** (`graph.py`): `INGEST_EVENT → (error? AUDIT : CUSTOMER_RESPONDED? EXTRACT_PROMISE : LOAD_CONTEXT) → LOAD_CONTEXT → (PROMISE_CREATED? SCORE_PTP : BUILD_FEATURES → ML_SCORING → RETRIEVE_CASES → ECONOMICS → POLICY → DECISION → ACTION) → UPDATE_STATE → AUDIT`. Three conditional edges total. The `LOAD_CONTEXT`-vs-`BUILD_FEATURES` branch point specifically exists to avoid a real bug caught in review: checking the event type any later (e.g. at `ML_SCORING`) would let `BUILD_FEATURES` run the wrong feature builder first, silently scoring PTP against recovery-shaped (due-date-cutoff) features instead of promise-shaped (T-cutoff) ones.

**Account state machine** (`state_machine.py`): `determine_next_state()` is the *only* place in the project that decides `(current_state, event, ...) → next_state` — every node that used to inline a placeholder mapping was rewired to call into it. Two-phase design: Phase A computes `intermediate` (path labels narrating what happened this round, purely event-driven), Phase B picks `next_state` in strict priority (paid always wins → dispute overlay → intermediate's own resting candidate → fresh action-outcome mapping). `path` contract: always `[...intermediate, next_state]`, deduplicated. Key resolved ambiguities: disputes supersede the broken-promise narrative for the *persisted* state (narrative still preserved in `path`); `KEPT` is a real, re-readable resting state, not a dead end; `BROKEN`/`REASSESS` are real but never literally persisted (the graph already reassessed by the time `UPDATE_STATE` runs, so the fresh action wins). **A real bug was caught here in review**: the first implementation let `REASSESS` (a purely transient label) win as the resting state instead of the fresh `selected_action` — fixed by splitting `_event_narrative()` into separate `intermediate`/`resting_candidate` return values.

**Action/tool layer** (`tools.py`): email/WhatsApp/voice/human-handoff are simulated (no contact-info field exists anywhere in the schema — confirmed, not assumed, a deliberate Day-1 scope decision); `create_payment_link` is the one real integration, `razorpay-python`, test mode. Money is `Decimal` from this module's boundary inward (the ML pipeline upstream legitimately stays `float` for scoring) — converted via `Decimal(str(x))`, never `Decimal(x)` directly. **Idempotency**: `reference_id=str(invoice_id)` on the Razorpay payment link — the first draft deliberately omitted this to dodge a test-rerun nuisance, which was the wrong fix (it also threw away the actual protection against a worker-crash-then-retry creating two payment links for one invoice); a rejected duplicate `reference_id` is now treated as an idempotent success, not a failure. The 4 simulated tools have a deterministic `failure_mode: bool = False` test seam — never randomness, so production behavior stays fully reproducible.

**Retry/fallback** (`resilience.py`): `call_with_retry()` is deliberately mechanism-only — it has no opinion about what "success" means for a given result shape or what to do when retries are exhausted; both are the caller's job. This was a real correction in review: the first draft would have baked `dispatch_action`'s "fall back to WAIT" directly into the retry utility, which looks reusable but isn't — Subtask 7's LLM extraction needs a completely different fallback ("treat the promise as unextracted," not "WAIT"). `dispatch_action`'s own fallback: **DO NOT GUESS a different channel, always WAIT** — `proposed_action` (Economics' original recommendation) stays untouched so the audit trail can show "wanted to ESCALATE, tool failed twice, fell back to WAIT." `ingest_event` no longer raises on an invalid event (would crash the whole `.invoke()`) — it sets `state["error"]`, and the graph's first conditional edge routes it straight to `AUDIT`, skipping the entire assessment pipeline but still getting recorded.

**Promise extraction + PTP activation** (`promise_extraction.py`, plus `build_live_ptp_feature_row()` added to `app/ml/features.py` and `score_ptp_probability()` added to `app/decision/service.py`): first real LLM call in the project — **Groq, `openai/gpt-oss-120b`**, JSON-mode, `temperature=0`, wired through `call_with_retry` with its own fallback (`None` on two failed/malformed attempts — never fabricate a promise). The LLM extracts; it never decides credibility — that's the PTP model, finally wired live for the first time (Day 2/3 explicitly couldn't, since the live pool was a genuine blank slate). `source` is read from the triggering event's own payload, never LLM-inferred. **The literal `payment_promises` DB write happens in `SCORE_PTP`, not `EXTRACT_PROMISE`** — `confidence_score` (`NOT NULL` on the model) is the PTP model's own calibrated probability, the honest real-system value (unlike the synthetic historical data's fabricated-from-ground-truth `confidence_score`), and it only exists once scoring has actually run. The write is an **upsert** (never more than one `OPEN` promise per invoice) — a real collision the review caught: two `CUSTOMER_RESPONDED` events extracting successfully before the first promise resolves is a realistic scenario (a customer revising their promise), not just a test-rerun artifact.

**Event-driven reassessment loop** (`scanners.py`): `scan_for_review_timeouts()`/`scan_for_broken_promises()` are plain functions invoked by a demo/test driver with an explicit `as_of` — **not a scheduled job**; that's an explicit, stated-out-loud scope cut (a production deployment would run these as a periodic scan job). The two scanners' candidate `account_state` sets are disjoint by construction (`PROMISE` is exclusively the broken-promise scanner's territory, excluded from the timeout scanner's list, which itself excludes `DISPUTE_REVIEW` — waiting on a human, not the automated system) — asserted at import time and covered by a named regression test, not just true by inspection. `scan_for_broken_promises` checks cumulative payments against `promised_amount` before reporting broken, so a partially-kept promise routes through `KEPT` instead of being misreported.

**Full audit trail** (`audit.py`): persistence is **opt-in, defaulting to off** — `write_audit`/`run_invoice(persist=...)` mirrors Day 3's `decide()`-vs-`persist_decision()` split exactly, since dozens of Day-4 tests call `run_invoice()` expecting it to be a no-op. The builders (`build_decision_log`/`build_account_state_updates`) are defensive across three genuinely different `GraphState` shapes (normal pipeline / promise-creation / invalid-event) — the `AccountState` update is skipped entirely for the invalid-event shape (no `next_state` exists to write), but `decision_logs` is still written unconditionally, recording the rejection, which was the entire point of routing invalid events to `AUDIT` in the first place. Reused Day 3's `_action_ev_to_dict`/`_retrieved_case_to_dict` directly from `app/decision/persist.py` — verified safe first (both operate on a single always-fully-populated dataclass with no internal iteration), not assumed safe from "same types."

**Full agent simulation** (`simulate_scenarios.py`): the 6 named scenarios (successful recovery, broken promise, dispute, already-paid false alarm, low economic value, tool/LLM failure), reusing named demo fixtures wherever one exists so the same `invoice_number` shows up on every rehearsal. **Scenario E (low economic value → `CLOSED_ABANDONED`) is genuinely unreachable by any real live invoice today** — verified directly, not assumed: `WAIT` never wins under the current Economics config even at the amount/probability floor (this is Day 3's own already-documented "PAYMENT_LINK dominates" finding showing up again, now at the point someone actually tried to trigger the rule that depends on it *not* dominating), and no live invoice has `prior_contact_count >= MAX_CONTACT_ATTEMPTS` since nothing writes to `recovery_actions` for the live pool. Per explicit decision, demonstrated via `determine_next_state()` called directly with a constructed context, clearly labeled illustrative rather than presented as a real invoice's own decision — re-tuning the economics to force it to fire would be the exact curve-fitting Day 3 already rejected doing, in a new guise.

**Final integration pass** (`final_integration_pass.py`): full 900-live-invoice pass through the real graph, **run dry (`persist=False`) first, on purpose, before ever touching the permanent write** — and it caught two real bugs a persisted run would have made far more annoying to unwind: (1) the "no hidden-ground-truth identifiers" check initially failed on its own denylist definition (`FORBIDDEN_IDENTIFIERS` necessarily contains the words it's searching for) — fixed by excluding the script from its own scan; (2) "no placeholder `recovery_probability`" genuinely failed for 74/900 invoices, traced to the float32/float64 precision gap described in the gotchas list above, fixed in Day-2 code with no retraining needed. Both confirmed fixed directly before the real write ran. **Final numbers**: `wait` 425 (47.2%), `whatsapp` 206 (22.9%), `escalate` 166 (18.4%), `voice` 71 (7.9%), `stop` 32 (3.6%); resulting states `wait` 397, `remind` 249, `escalate` 166, `dispute_review` 56 (6.2%, closely matching the generator's documented flat 6% dispute rate — an end-to-end cross-check the whole pipeline is behaving consistently with known ground truth), `closed_paid` 32. `CLOSED_ABANDONED: 0`, confirming Scenario E's structural finding at full scale, not just the handful of cases checked earlier. All 7 safety checks pass: no duplicate processing, no policy bypass, no business-hours violations, zero LLM/`EXTRACT_PROMISE` invocations (every event in this pass is `INVOICE_OVERDUE`), every result has a real score, no placeholder scores, no hidden-ground-truth identifiers. **This has been run for real (`--persist`)** — `account_state`/`decision_logs` for the full live pool now reflect real Day-4-computed values, not Day-1 placeholders, permanently until Day 5's `seed_demo.py` exists to reset them.

**Testing**: 104 new tests across `test_agent_contract.py`, `test_agent_graph.py`, `test_agent_demo_parity.py`, `test_state_machine.py`, `test_tools.py`, `test_resilience.py`, `test_promise_extraction.py`, `test_scanners.py`, `test_reassessment_loop.py`, `test_audit.py` — 222 total project-wide. Some `test_promise_extraction.py`/`test_reassessment_loop.py` tests require `LLM_API_KEY` and skip gracefully (`pytest.mark.skipif`) if it isn't set.

**Known, harmless side effects of testing/rehearsal, so they aren't mistaken for something else later:** `simulate_scenarios.py` and the real `final_integration_pass.py --persist` run both write real `decision_logs`/`account_state` rows across the invoices they touch (the latter: all 900). This is expected and intentional as of Day 4's completion, not a leftover test artifact to clean up — Day 5's `seed_demo.py` is what resets to a curated demo state when needed.

## Day-1 (work PC) checklist status

Done: GitHub/SSH/git-identity setup, project structure (backend/frontend split), `.env.example`, Docker Postgres+pgvector, all 11 tables + migrations, synthetic generator (all entity types), validation suite (all 7 checks + reproducibility), demo fixtures, pytest suite (12 tests, all passing).

## Day-2 checklist status

Done: `app/ml/` package (config, features, labels, splits, evaluate, train_recovery, train_ptp, persist), recovery model trained+calibrated+sanity-checked, PTP model trained+calibrated+sanity-checked, future-leakage regression tests, model artifacts + FeatureSnapshot rows persisted, full pytest suite green (30 tests), `DECISIONS.md` written. See "Day 2: ML layer" above for the full summary.

Explicitly not done (by decision, not oversight): expected-payment-date regression model (skipped), SHAP explanations (deferred/optional).

## Day-3 checklist status

Done: Economics Engine, pgvector embedding migration + `case_embeddings` corpus (9,000 rows), hybrid BM25+vector retrieval (relevance verified, 2.00x baseline), Policy/Safety Gate (8 rules + tests), Deterministic Decision Service (`build_live_feature_table()`, live scoring, full orchestration), state/audit wiring (`decision_logs` + `account_state`, decision trace verified end-to-end), Evaluation (baseline vs. engine, real numbers, escalation diagnostic), frontend scaffold (3 screens, mock data mirroring real shapes), final integration pass (6 demo scenarios, full 900-invoice pass, no-LLM confirmed, no-leakage confirmed via adversarial test, 118/118 tests passing). See "Day 3: Decision intelligence layer" above for the full summary, including every bug found and every deliberate assumption.

Explicitly not done / deferred, by decision: PTP model wiring (genuinely blocked — live pool has zero promises until Day 4 creates one), real persistence of all 900 decisions to `decision_logs`/`account_state` (the compute path is proven at full scale; only one test invoice has actually been persisted so far — running it for real is closer to an operational/Day-5 `seed_demo.py` concern than a Day-3 testing one), frontend visual/CSS design pass (Day 5/6, user's explicit instruction), live API wiring for the frontend (Day 6), segment-aware uplift/friction (flat across archetype, stated as a scope cut in `config.py`).

**Known, harmless side effect of testing, so it isn't mistaken for something else later:** `tests/test_decision_persist.py::test_already_paid_false_alarm_decision_trace_is_reconstructible_from_db` genuinely commits to the real dev DB (that's the point — it proves the persistence path actually writes, not just that the function runs). One specific `already_paid_false_alarm` live invoice's `account_state` row is therefore already `current_state=CLOSED_PAID` with a real `decision_logs` row, while the other 899 live invoices are still at Day-1's seed placeholders — don't be confused by this one outlier if inspecting the DB before Day 5's `seed_demo.py` resets everything to a curated state.

**Carried-forward commitment for Day 5** (also saved as a persistent project memory, since Day 5 is likely a separate session): the Attribution Engine must use its randomized-holdout result to produce **corrected** `ACTION_UPLIFT` values (at minimum for `strategic_enterprise`'s `ESCALATE` uplift, the diagnosed-wrong case above) — not just measure and report the incremental-recovery gap. Showing the escalation-appropriateness finding now only lands as real progress if Day 5 actually closes it.

## Day-4 checklist status

Done, all 11 subtasks: state/event contract, LangGraph orchestration skeleton (verified parity with Day-3's `decide()` on all 6 demo fixtures before adding any new behavior), account state machine (+ `DISPUTE_REVIEW` migration), bounded action/tool interfaces (real Razorpay test-mode integration, idempotent), retry/fallback/error handling (generic mechanism, caller-owned fallback semantics, invalid-event routing), promise extraction + PTP activation (first real LLM call, PTP model finally wired live), event-driven reassessment loop (scanners, disjoint candidate states), full audit trail (opt-in persistence, 3-shape-defensive builders), full agent simulation (6 named scenarios, 1 correctly labeled illustrative), final Day-4 integration pass (dry run first by explicit design, 2 real bugs caught and fixed before the permanent write, then run for real across all 900). See "Day 4: LangGraph orchestration layer" above for the full summary, including every bug found and every deliberate assumption.

Explicitly not done / deferred, by decision: dashboard API endpoints and frontend live-data wiring (both explicitly moved back to Day 5/6 per the master doc's own original day-by-day plan — Day 4 stayed focused on the orchestration/agent core, per CLAUDE.md's own standing warning to protect its time), real Redis-backed event ingestion (direct in-process function calls instead, a stated scope cut, not a gap), a real scheduler for the reassessment scanners (plain functions invoked on demand, production would need a periodic job), event-ID-based deduplication (reprocessing is safe, not actively prevented), segment-aware LLM explanation narrative for the audit trail (the `DECISION` node is a documented seam for this, never built — Day 4's LLM use stayed scoped to promise extraction only, never influencing the deterministic action choice).

**Carried-forward commitment for Day 5** (unchanged from the Day-3 checklist above, still not yet done): the Attribution Engine must use its randomized-holdout result to produce **corrected** `ACTION_UPLIFT` values, not just measure and report the incremental-recovery gap. Also carried forward: `seed_demo.py` (Day 5, per the master doc) is now more clearly needed than ever — the full live pool's `account_state`/`decision_logs` are permanently populated with real Day-4 values as of this session, so a reset script is what makes repeatable demo recording possible, not optional polish.

## Tonight: Day-1 home-PC transfer

Per the user's own plan: prove the Day-1 foundation moves between environments via `pg_dump`/`pg_restore`, not by re-running the generator on a new machine (that only proves code-determinism, not actual data portability — both get validated, separately, on purpose).

1. At work, once the dataset above is in its final validated state: `pg_dump -U postgres -d receivables_ai -Fc -f receivables_day1.dump` (against the Docker container, e.g. via `docker exec` or a port-5433 connection), verify with `pg_restore --list receivables_day1.dump`.
2. **Never commit the dump to git** — `.gitignore` already excludes `*.dump`/`*.dmp`. Since the repo folder lives inside OneDrive (`...\Desktop\b2b-receivables-intelligence`), placing the dump in a gitignored subfolder there lets OneDrive sync it to the home PC automatically — no manual transfer step needed, as long as the same OneDrive account is signed in on both machines.
3. At home: clone/pull the repo, stand up the same Docker Postgres setup (`pgvector/pgvector:pg16`, port 5433 — or pull pg18 fresh there, doesn't need to match this machine's image choice), create an empty `receivables_ai` db with pgvector enabled, then `pg_restore` the dump directly — this restores schema + data in one shot. Don't re-run `alembic upgrade head` or the generator to recreate it; that's a different, separate check.
4. Separately (per the checklist's own "Final local verification" section), re-run `python -m synthetic.generator` at home with the same `SEED=42` and confirm the fingerprint matches what was produced at work — this is the *code*-portability proof, independent of whether the dump restored correctly.

## Day 5, subtask 8: Deploy target decision (backend + DB)

**Database: Supabase, not Render Postgres.** Both verified live (web search,
not assumed from training data, since hosting free-tier policies change
often) before deciding. Render's free Postgres runs a hard 30-day timer
regardless of usage, then a 14-day grace period, then **permanent
deletion** unless upgraded to paid. Supabase's free tier instead pauses
after 7 days of genuine inactivity (no real query hitting the database --
dashboard visits and cached API responses don't count) but never
force-deletes; a paused project un-pauses with one click, data intact.
Given this project needs to survive an unpredictable judging window after
the 7-day build sprint ends, Supabase's "pause, never delete" failure mode
is safer than Render's "deleted on a fixed clock" one. Trade-off: Supabase
free tier caps at 500MB storage (vs. Render's 1GB) -- expected to be
comfortably enough for this dataset (9,900 invoices + 9,000
case_embeddings + related tables), not yet confirmed post-restore.
pgvector is supported on both (confirmed live for Render; Supabase
supports it on all plans including free).

**Backend: Render Free Web Service**, pointed at the Supabase database via
`DATABASE_URL`. 750 free instance-hours/month. Known trade-off: free web
services spin down after 15 minutes idle, ~30-60s cold start on the next
request -- not a functional problem, just something to remember before
recording the demo video (hit the API once first to warm it up).

**Deployed and verified live** at `https://b2b-receivables-intelligence.onrender.com`
-- `/health`, `/api/invoices`, `/api/metrics`, `/api/attribution` all
checked directly against the live URL and confirmed correct (metrics
internally consistent at 900 total invoices; attribution numbers match the
local pre-ACTION_UPLIFT-fix run exactly, as expected since the experiment
hasn't been re-run since).

**Two real deploy bugs hit and fixed, both worth remembering:**
1. `DATABASE_URL` needs the explicit driver: `postgresql+psycopg://...`,
   not bare `postgresql://...` -- SQLAlchemy defaults an unqualified
   scheme to `psycopg2`, which this project never installs (uses `psycopg`
   v3 throughout). Local `.env` already had this right; the
   Supabase-provided connection string does not include it by default.
2. **None of Day 5's work (subtasks 1-8) had been committed to git before
   the first deploy attempt** -- Render builds from `origin/main`, which
   was still sitting at Day 4's last commit. Caused a confusing
   `alembic: Can't locate revision` error (the migration file genuinely
   didn't exist in that checkout) that had nothing to do with the
   migration itself. Committed as `ecd8bae "attribution and backend api
   calls done"` and pushed before the deploy that actually worked. Lesson:
   a red build log doesn't always mean the code is wrong -- check `git
   status`/`git log` against what the host is actually building from
   before debugging the code itself.

Also hit and fixed during this same stretch: Supabase's Direct connection
resolves IPv6-only (hangs forever, no error, on IPv6-unclean networks --
switched to Session Pooler mid-restore); Supabase installs pgvector into
an `extensions` schema by default, not `public` (our dump's DDL expects
`public.vector` -- fixed via `create extension vector with schema
public`); the first `pip freeze` run in PowerShell silently produced a
UTF-16-encoded requirements.txt (fixed via Git Bash instead).

**No Redis deployed.** Confirmed still unused -- Day 4's own DECISIONS.md
already established direct in-process event handling, `REDIS_URL` an
untouched placeholder. Deploying Upstash or any Redis instance would add
an account and zero function.

**Connection string: use Supabase's SESSION POOLER, not Direct connection
or Transaction Pooler.** Revised after hitting this live: Supabase's
"Direct connection" resolves to an IPv6-only address unless you're on
their paid IPv4 add-on -- on a network without clean IPv6 routing, this
makes pg_restore (and presumably the deployed backend too) hang
indefinitely with zero error output, exactly the symptom hit during the
actual restore attempt. Session Pooler (port 5432, hostname
`*.pooler.supabase.com`, username becomes `postgres.<project-ref>`) is
IPv4-compatible AND -- unlike Transaction Pooler (port 6543) -- preserves
session state/prepared statements, making it the right choice for both
the one-off pg_restore and the long-running Render backend's
`DATABASE_URL`. Lesson: verify against the actual network path (a hang
with no error is a connectivity-layer symptom, not a slow-operation one),
not just against what the provider's docs recommend in the abstract.

**requirements.txt pinned for the first time** (`pip freeze`, 87 packages)
-- was deliberately left unpinned through Day 4 per the working-style
notes below, but deploying to a fresh environment is exactly the moment
version drift becomes a real risk, so this was the right time to do it.
**Gotcha hit and fixed:** the first `pip freeze > requirements.txt`, run in
PowerShell, silently produced a UTF-16-encoded file (every character
visibly space-separated when inspected -- `a l e m b i c` instead of
`alembic`) that `pip install -r requirements.txt` would have failed to
parse on Render's Linux build. PowerShell's `>` redirection is not
reliably UTF-8 in this environment despite general expectations otherwise
-- re-ran via Git Bash's `pip freeze > requirements.txt` instead, which
produced plain ASCII/UTF-8 correctly. Worth remembering for any future
redirect-to-file command in this project: prefer Git Bash over PowerShell
`>` when the output must be plain-text-parseable by another tool.

## Day 6: Frontend live-data wiring — subtasks 1–15 of 17 complete

Full plan is Phase A (functional integration, subtasks 1–8) → Phase B (hosted
verification, 9–10) → Phase C (design system + console redesign + landing
page, 11–13) → Phase D (observability/RAG/LLMOps panels + polish, 14–15) →
Phase E (deploy frontend, 16) → Phase F (demo-recording rehearsal, 17).
Deliberately sequenced functionality-before-visuals, same precedent as every
prior day's "defer polish" decisions. **Phases A through D (subtasks 1–15) are
now done**, tested against real data at every step, not just compiled. Only
Phase E (deploy frontend) and Phase F (demo rehearsal) remain — see "Day 6,
Phase C continued + Phase D" below for the redesign/observability/polish work,
and "End of day (2026-09-02)" further down for what's left and how the home
Mac gets synced to today's state.

**Subtask 1 (types reconciliation):** `frontend/lib/types.ts` rewritten
against the REAL API shapes (`app/api/schemas.py` + `app/agent/audit.py`'s
actual JSONB writers), not the stale Day-3 mock shapes. Real bugs fixed:
`AccountCurrentState` was missing `dispute_review` (added in Day 4, types.ts
never updated); `PolicyChecks` used Day-3's `final_action`/`result` keys,
but virtually every real row is written by Day-4's `audit.py` using
`selected_action`/`policy_result` instead (both kept, legacy ones marked
`@deprecated`, since `schemas.py` returns raw JSONB and either can appear on
the wire). Added types that never existed: `InvoiceTimeline`,
`TimelineEntry`, `MetricsResponse`, `AttributionHeadline`,
`AttributionSliceOut`, `ArchetypeDiagnosticRow`, `AttributionResponse`,
`ToolResult`, `TreatmentGroup`.

**Subtasks 2–4 (connect list/detail/metrics+attribution):** `frontend/lib/api.ts`
(new) is the one typed fetch client for all of `app/api`'s GET routes —
`cache: "no-store"` throughout since every route reads live persisted state.
Invoices list (`app/invoices/page.tsx`) is a Server Component driven
entirely by `searchParams` (status/segment/`invoice_number` filters +
`offset` pagination) — filtering delegated to `InvoiceFilters.tsx` (client
component) so picking a Status applies immediately via `router.push`, no
submit click required (explicit user ask). Invoice Detail
(`app/invoices/[invoiceId]/page.tsx`) fetches invoice+decision+timeline in
parallel; defensive against every field Day-4's `audit.py` only
conditionally populates (`candidate_actions`, `recovery_probability`,
`retrieved_cases`, `selected_action` vs `final_action`, etc. — see
`lib/types.ts`'s own comments for which shape is dominant). Metrics page
adds real per-action/per-segment attribution tables (`GET /api/attribution`,
`include_diagnostics` deliberately left `false` — hidden-ground-truth
archetype fields never belong on a production-facing screen, matching the
discipline `app/attribution/DECISIONS.md` already established). Deleted
`frontend/lib/mockData.ts` and the dead `EscalationAppropriateness` type
once nothing referenced them anymore.

**Subtask 5 (navigation):** `RefreshButton.tsx` (shared client component)
uses `router.refresh()` (confirmed via the installed Next docs — this Next
version's `error.tsx` boundary prop is `retry`, not `reset`, a real
breaking-change trap worth remembering for any future error-boundary code).
Found via direct user testing that `router.refresh()` gives zero visible
feedback when the underlying data hasn't changed — fixed with a
`useTransition`-driven "Refreshing... → Last refreshed HH:MM:SS" state.
Also fixed: the invoices list's failed-fetch "Retry" link used to reset to
the bare `/invoices` URL, discarding the user's active filters — now retries
the same filtered/paginated URL.

**Subtask 6 ("Why this decision?" + LLM panel):** Confirmed via
`app/decision/policy.py`/`persist.py` that the chosen action is fully
deterministic (Economics Engine + Policy Gate) — added an explicit callout
saying so, correcting the master doc's original "LLM drafts a
recommendation" framing against what Day 4 actually scoped (LLM used only
for promise extraction, never the decision). **Real bug found and fixed via
live testing, not just code reading:** `EventType.PROMISE_CREATED` is
synthesized by `extract_promise_node` ONLY on a successful extraction,
replacing the round's `event` before the audit write — so a persisted row
with `trigger_event.event_type == "promise.created"` means the LLM
succeeded, while `"customer.responded"` surviving to the persisted record
means the LLM ran and found nothing. The first implementation had this
backwards (checked only for `"customer.responded"`, missing the success
case entirely) — confirmed via a live test round on `INV-10677`, fixed, and
reconfirmed with a second live round showing the correct 66.5% PTP score.
Deliberately does NOT show model latency/retry count for the LLM call
specifically — `extract_promise_node` never captures that into `GraphState`
(confirmed by reading it), so fabricating it would be dishonest; user chose
"frontend-only honest scope" over extending the backend to capture it.

**Subtask 7 (state timeline):** `GET /api/invoices/{id}/timeline` now
includes `state_transition_path` per decision event (small addition to
`app/api/routes/decisions.py`); frontend renders it as an arrow-joined path
per timeline entry.

**Subtask 8 (safety/failure visualization):** New Invoice Detail section
surfacing dispute/already-paid/policy-blocked-or-escalated/tool-call
outcome from real `policy_checks` fields (`ToolResult` type added, matching
`app/agent/tools.py`'s actual `_tool_result()` shape exactly). **Real bug
found via live testing against the forced-failure demo scenario
(`INV-10184`):** the existing "Proposed X, overridden to Y by policy" text
unconditionally attributed any `proposed_action != selected_action`
mismatch to the Policy Gate — but `dispatch_action`'s tool-failure fallback
(action fails twice → falls back to WAIT) also produces this mismatch, with
`policy_result` still `allowed` (the Gate approved the original action;
nothing about it was overridden by policy). Fixed to branch on
`policy_result`: only says "overridden by policy" when the Gate actually
blocked/escalated, otherwise says "fell back after a tool failure."

**Also found and fixed while testing (not part of any single subtask):**
(1) **`GET /api/invoices` had no way to search by invoice number** — with
~900 invoices and only status/segment filters, a specific demo invoice was
unfindable by paging. Added `invoice_number` (case-insensitive substring
match) to the route and a matching search field in `InvoiceFilters.tsx`.
(2) **Critical `.gitignore` bug, found only because a commit was about to
happen**: the root `.gitignore`'s Python-template `lib/` rule (no leading
slash) was matching `frontend/lib/` at any depth, not just Python
build-artifact `lib/` directories. Confirmed via `git log -- frontend/lib/`
returning nothing that `frontend/lib/` (`types.ts`, `api.ts`, and the
now-deleted `mockData.ts`) had **never been committed once since Day 3** —
existed only on local disk. Fixed with a targeted negation
(`!frontend/lib/` + `!frontend/lib/**`) rather than removing the generic
rule, which still correctly excludes real Python build artifacts elsewhere.
**Lesson for any future gitignore edit in this repo**: a bare pattern with
no leading slash matches at every directory depth, not just the level it
looks like it's targeting — verify with `git log -- <path>` before assuming
something has been tracked, especially before a first commit/push of a
long-lived directory.

**Subtask 9 (hosted integration):** Corrected the plan's own assumed path
first — there is no Redis and no live LangGraph/ML/retrieval call in the
deployed API's request path (every route reads already-persisted state, see
`app/api/DECISIONS.md`), so the real test is `Browser → local frontend →
Render → Supabase`. Verified by pointing `frontend/.env.local` at the
deployed Render URL: 27.9s cold start on the first request (matches the
documented Render free-tier trade-off exactly), fast thereafter, no CORS or
serialization errors. Reverted `.env.local` back to `localhost:8000`
afterward per the established local/hosted split.

**Subtask 10 (demo-case routing):** New `GET /api/demo-fixtures`
(`app/api/routes/demo.py`) reads `synthetic/demo_fixtures.json` server-side
and resolves each fixture to its current real `invoice_id` — single source
of truth, survives a future `seed_demo.py` re-pin automatically (chosen
over hardcoding UUIDs frontend-side). `DemoCaseMenu.tsx` in the root nav
(plain `<details>/<summary>`, no client JS) lists all 6 fixtures plus two
extra entries for the categories with no single pinned invoice: **Dispute**
links to the existing `current_state=dispute_review` filter (56 real
invoices, no need to pick one server-side); **Abandoned** links to
`current_state=closed_abandoned`, which correctly shows an empty list —
that emptiness IS the already-documented Day-4 finding (0 live invoices
resolve here today), not something to fake around.

**Not yet done — subtasks 16–17 only** (Phase C's design system/console
redesign/landing page and Phase D's observability panel + recruiter/demo
polish are all done, see "Day 6, Phase C continued + Phase D" below): deploy
frontend (Vercel) → demo-recording rehearsal.

**Known local/remote data-parity caveat for resuming on a different
machine:** the local Docker Postgres now has extra ad-hoc test rows (a few
manually-fired `CUSTOMER_RESPONDED`/forced-failure rounds against
`INV-10677`/`INV-10184`, used to verify subtasks 6 and 8 live) that only
exist on the machine they were run on — never pushed (the DB isn't in git),
and not present in Supabase either. Harmless (append-only decision_logs,
same accepted-side-effect category as `simulate_scenarios.py`'s own runs),
but don't be surprised if a fresh machine's local DB or Supabase shows a
different "latest" decision for those two invoices than what was screenshotted
during this session.

## Day 6, Phase C: metrics staleness bug + attribution rerun (2026-09-02)

**SUPERSEDED — see "⚠ CURRENT CANONICAL STATE" near the top of this file.**
The specific numbers below (-3.1% pooled, +₹1,482,200 net EV, etc.) were
correct for the work-PC dataset instance that existed on 2026-09-02. That
instance no longer exists — 2026-09-03's cross-machine reconciliation
restored this DB from the home Mac's dump, which is a different (though
business-column-identical) dataset with a positive pooled attribution
result. The bug/investigation narrative below is still accurate history;
only the headline figures are stale.

Found while redesigning the landing page: the "Net EV improvement" and
"Measured incremental recovery" proof numbers were both showing negative,
which would read badly to a recruiter viewing the site. Investigated
properly (queried the DB directly, ran the real evaluation/attribution
scripts) rather than just restyling around it -- two distinct real bugs
found and fixed, not a frontend issue at all:

**Bug 1 -- `/api/metrics` graded old decisions against new economics.**
`_live_pool_outcomes()` read each invoice's `next_action` as persisted back
in Day 4's original batch run, then recomputed its EV using Day 5's
corrected ESCALATE economics -- an inconsistent comparison (confirmed: a
genuinely fresh `run_full_live_pass()` gave +Rs.1.48M vs. the stale
approach's -Rs.168K, same population). Fixed by adding a new
**`evaluation_snapshots`** table (current-snapshot overwrite, one row per
strategy, same pattern as `attribution_experiment_results`) and
**`app/decision/persist_evaluation.py`** (`python -m
app.decision.persist_evaluation`) -- a fresh run takes ~55s, too slow for a
page load, so it's precomputed and `/api/metrics` just reads the latest
snapshot now. **Re-run this any time the live pool or economics config
changes**, or the dashboard will silently go stale again exactly like this.

**Bug 2 -- the Day-5 attribution experiment's pooled headline was
distorted by the (already-known) ESCALATE composition bug**, not a flaw in
the product. Broken down by action, WAIT/WHATSAPP/VOICE were all positive;
ESCALATE alone was negative and large enough in dollar terms to drag the
flat pooled average down. Fix: re-ran the FULL Day-5 pipeline with the
corrected economics (`day5_pre_attribution.dump` still existed, made this
possible) -- restore pre-attribution snapshot → `alembic stamp head` (the
restore reverts newer-migration tables' bookkeeping but not their
structure -- see below) → `python -m app.attribution.persist` →
`python -m app.attribution.evaluate` → `python -m
app.agent.final_integration_pass --persist` → `python -m
app.decision.persist_evaluation` → `python -m synthetic.seed_demo`. Result:
ESCALATE volume dropped 85→25 invoices and its composition shifted away
from `strategic_enterprise` (the fix's real, verified effect) -- but the
pooled headline is *still* slightly negative (-3.1%), now for an honest,
different reason: a single 50/50 split across many small segment×action
cells carries real sampling noise (every cell's z-score is under 1.5,
i.e., none of it is statistically distinguishable from zero at this
sample size), not stratified on the hidden archetype dimension by design.
Net EV improvement stayed solidly positive throughout: **+Rs.1,482,200**.

**A real, separate data bug found while verifying the rerun**: demo
fixture `high_value_act` (INV-10706) had two payments dated 2026-09-03 (a
real-world future date, unrelated to the simulated timeline) sitting in
its ledger from some earlier session -- pre-point-in-time-cutoff, so
`assignment.py`'s eligibility check correctly didn't count them as "already
paid" as of the experiment's `as_of` date (that part is correct
point-in-time-safety, not a bug), but it meant the invoice wrongly stayed
eligible. Checked all 812 eligible invoices for this pattern: only one
other (INV-10110) had it, with zero practical effect (simulated as
not-recovered). Fixed INV-10706 directly (deleted the stray payments,
reverted status/paid_at, removed its attribution_records row) rather than
re-running the whole experiment again for a 1-invoice edge case.

**Gotcha, worth remembering for any future dump restore**: restoring an
OLDER pg_dump into a DB that has since had NEWER migrations applied
reverts `alembic_version` to the dump's revision, but tables/columns added
by migrations *after* the dump was taken either don't get touched at all
(if the whole table postdates the dump -- fine, structurally current) or
get **reverted to their old structure** (if the table predates the dump
but gained columns afterward -- e.g. `attribution_records` lost its
`action`/`counterfactual_action` columns this way, caught immediately by
the first attribution rerun attempt failing with `UndefinedColumn`). Never
just `alembic stamp head` after a restore without first diffing every
table that existed in both the dump and pre-restore state against the
current models -- stamping only fixes the bookkeeping, not a silently
reverted structure.

**Landing page framing decision** (once implemented): lead with Net EV
improvement + engine recovery rate (both solid, stable); for the
channel-level attribution stat, show "3 of 4 channels show positive
measured lift" rather than the flat pooled number, with the full honest
breakdown (including ESCALATE's still-negative, now-small-sample-noise
result) staying one click away on the metrics page.

**All of the above is LOCAL ONLY as of this note** -- Supabase (the
deployed backend's database) has NOT been touched and still reflects
whatever state it was in before this rerun. See the updated demo-recording
reminder below: this now needs to be pushed to Supabase (fresh dump +
restore, or a full re-run of this same script sequence against Supabase's
`DATABASE_URL`) before recording, in addition to the existing
`seed_demo.py` step already noted there.

## Day 6, Phase C continued + Phase D: metrics redesign, observability page, demo polish (2026-09-02)

Subtasks 12 (metrics page, the last unstyled console screen), 14
(Observability), and 15 (recruiter/demo polish) done in this stretch, on top
of the design system + invoices/detail console redesign + landing page
already covered earlier in this file's Day 6 material. Full creative freedom
per the user's own instruction ("show as much graph and anything you want...
just everything meaningful"), iterated over several rounds of direct
screenshot feedback exactly like the earlier pages.

**Metrics page full redesign** (`frontend/app/metrics/`): `RecoveryGauges.tsx`
(two `RadialGauge`s, baseline vs. engine recovery rate), restyled
`ComparisonChart.tsx` (gross/cost+friction/net, grouped bars), new
`DecisionMixChart.tsx` (donut pair, each strategy's Wait/Intervened/Stop
split), new `AttributionCompareChart.tsx` (treatment vs. control, recovery
rate + recovered amount), new `SliceLiftChart.tsx` (incremental net recovery
per action/segment, green/red by sign), restyled `SliceTable.tsx`. Every
number traces directly to `MetricsResponse`/`AttributionResponse` fields --
same no-fabrication discipline as every other page.

**Real bugs found and fixed via direct user testing, not just code review:**
- `RadialGauge`'s strategy-name label was rendered *inside* the ring's own
  fixed diameter -- a long name ("Baseline (email everyone)") wrapped to 3
  lines and spilled past the stroke. Fixed by making the `label` prop
  optional and moving the caption to a normal (wrapping-safe) block below
  the gauge instead of an absolutely-positioned span inside it. While fixing
  this, `RadialGauge.tsx` was **moved from `invoices/[invoiceId]/` to
  `app/RadialGauge.tsx`** (shared) since the metrics page needed it too --
  update the import path if referencing this component from memory.
- `DecisionMixChart`'s two donuts only used half the card's width, leaving
  the other half visibly empty. Root cause: a `flex-row` container whose
  direct children were plain wrapper `<div>`s with no `flex-1` -- they
  shrank to their content's width instead of claiming half the row. Fixed
  by switching to `grid grid-cols-2`, which forces each cell to actually own
  50% regardless of content size.
- Wait and Stop rendered as two near-identical greys in that same donut
  (`status-wait` vs. `text-faint`) -- confirmed by the user, not just a
  contrast-ratio check. Changed to amber (Wait) / red (Stop) / accent blue
  (Intervened) -- three unambiguous hues, at the deliberate cost of "Stop"
  no longer matching `lib/ui.tsx`'s own neutral-tone convention used
  elsewhere on the console. Glanceable distinction won over strict
  tone-mapping consistency here.
- A `SignalStrengthChart` (z-score / statistical-significance bar chart) was
  built, then hit a duplicate-React-key crash: it was fed the FULL
  segment×action cube (`attribution.slices` unfiltered), but its label logic
  collapsed to just the segment name whenever one was present -- so a
  cross-cell row like `("SMB", "escalate")` rendered under the same `"SMB"`
  label as the plain by-segment-only row. Root-caused and fixed (filtered to
  just the pooled + by-action + by-segment marginal rows), then the
  **component was removed entirely** minutes later per explicit user
  request, along with the explanatory `<p>` caption blocks added under
  several other charts (`ComparisonChart`, `AttributionCompareChart`,
  `SliceLiftChart`) and the "Incremental recovered amount" KPI tile (kept
  "Incremental net recovery" instead). Noted here so a future session
  doesn't go looking for a z-score chart or explanatory captions that used
  to exist in this session's history but are gone by explicit request --
  `frontend/app/metrics/SignalStrengthChart.tsx` no longer exists.

**Observability page** (subtask 14, new): `frontend/app/observability/page.tsx`
-- a plain Server Component with **no fetch calls at all**, per the plan's
own explicit "small, mostly static reported numbers... NOT a new live-eval
endpoint" instruction. Presents three sections of already-documented,
already-real Day 2-4 figures: model calibration (Recovery/PTP ROC-AUC/PR-AUC/
Brier/broken-promise F1, both experiments), retrieval quality (self-retrieval
@1, 2.00x archetype-cohesion baseline), agent/LLM reliability (Groq config,
retry/fallback design, the final-integration-pass's 7/7 safety checks, test
counts). Added to `ConsoleSidebar.tsx`'s nav (Gauge icon, between Metrics and
the demo-scenarios flyout). `lib/ui.tsx` gained a new shared `IconStat`
component, extracted from the metrics page's local `KpiCard` once
observability needed the identical icon-badged-tile pattern -- both pages
import the same primitive now, no duplicate component.

**Recruiter/demo polish** (subtask 15): `app/metrics/loading.tsx` (a
skeleton matching the page's real section layout -- metrics was the one
console page with no loading state yet, notable given the Render free
tier's documented ~28s cold start); `app/metrics/error.tsx` and
`app/observability/error.tsx` (safety-net boundaries matching the existing
`invoices/error.tsx` convention -- expected failures stay handled inline in
each page's own try/catch); `app/not-found.tsx` (a branded 404 -- genuinely
reachable, not just decorative, since the invoice detail page already calls
`notFound()` on an unknown invoice ID); `app/PageTransition.tsx` (a
pathname-keyed Framer Motion fade, wired into both branches of
`SiteChrome.tsx` -- the one page-level transition gap; every other animation
in the app was already component-local). **Deliberately did NOT build a
mobile/phone-width console redesign** when auditing for this subtask --
confirmed this is an already-documented, deliberate desktop-first decision
from the invoices-page redesign (see that page's own code comment: "console
pages are desktop-first already -- the sidebar nav itself is desktop-only"),
not a newly-found gap, and flagged it to the user rather than silently
expanding scope to fix it.

**As of this note, none of today's Phase C-continued/Phase D frontend work
above has been committed to git yet** -- see "End of day (2026-09-02)" right
below for the plan to get both the work PC and the home Mac in sync once it
is.

## End of day (2026-09-02): syncing today's work to the home Mac

Two separate kinds of "today's work" need to reach the home Mac, and they
sync differently:

1. **Frontend code** (the metrics redesign + observability page + demo
   polish above): a normal `git commit` + `push` on the work PC, then
   `git pull` on the Mac. No new npm packages were added this session
   (recharts/framer-motion/lucide-react were all already installed), so
   `npm install` on the Mac is a safety check, not a required step.
2. **Local Postgres data** (the 2026-09-02 metrics-staleness fix +
   attribution rerun documented above, plus the `evaluation_snapshots`
   migration) -- this is **not** in git at all (`*.dump` is gitignored by
   design, and the DB itself obviously isn't tracked). Per the
   already-documented "Switching machines" note further below, the home
   Mac's local Postgres was only ever synced with Day-1 data and has never
   caught up through Days 2-6 -- today's fix makes that gap concretely
   wrong (stale/broken metrics and attribution numbers), not just
   incomplete, so a real transfer is worth doing now rather than deferring
   again. Same mechanism as the original Day-1 transfer (see "Tonight:
   Day-1 home-PC transfer" above), just re-run with today's dump.

**On the work PC** (run from the repo root; places the dump directly inside
the OneDrive-synced repo folder, same as the Day-1 transfer, so no manual
file transfer step is needed):
```powershell
docker exec receivables-postgres pg_dump -U postgres -d receivables_ai -Fc -f /tmp/receivables_day6_phaseCD.dump
docker cp receivables-postgres:/tmp/receivables_day6_phaseCD.dump .\receivables_day6_phaseCD.dump
```
Then commit + push the frontend code whenever ready (not run automatically --
per the standing "never commit unless explicitly asked" rule below).

**On the Mac** (after confirming OneDrive has actually finished syncing the
new `.dump` file over -- check its size/modified time match the work PC's
before restoring):
```bash
cd ~/path/to/b2b-receivables-intelligence
git pull

cd frontend
npm install

cd ../backend
source venv/bin/activate
docker start receivables-postgres    # or `docker-compose up -d` if the container was never created on this machine

docker cp ../receivables_day6_phaseCD.dump receivables-postgres:/tmp/receivables_day6_phaseCD.dump
docker exec receivables-postgres pg_restore --clean --if-exists --no-owner -U postgres -d receivables_ai /tmp/receivables_day6_phaseCD.dump

alembic upgrade head    # sanity check -- should report already at head, the dump carries its own correct alembic_version
pytest -v               # confirm parity with the work PC

# then, to actually look at it:
uvicorn app.main:app --reload --port 8000    # backend, in one terminal
cd ../frontend && npm run dev                 # frontend, in another -- http://localhost:3000
```

This is a **full replace** (`--clean --if-exists`) of the Mac's local
`receivables_ai` database, not a merge -- correct here since the goal is
exact parity with the work PC's current state, but worth knowing if the Mac
ever has its own local-only test data worth keeping (per the precedent in
"Known local/remote data-parity caveat" above, it currently doesn't, but
check before restoring if that's changed).

**Not covered by this transfer, and not needed for it:** `backend/app/ml/`
model artifacts (`.joblib` files, gitignored, disk-only). The FastAPI routes
all read already-persisted DB state -- no live ML/LangGraph/retrieval calls
happen in the request path (`app/api/DECISIONS.md`) -- so the Mac's backend
+ frontend will show fully correct, identical results after the steps above
with zero need to retrain or re-persist anything. Artifacts only matter if
actively re-running training/decision/agent scripts on the Mac itself.

## Attribution metric honesty fixes (2026-09-02, after the "frontend done" commit)

**SUPERSEDED numbers — see "⚠ CURRENT CANONICAL STATE" near the top of this
file.** The pooled result on the current (2026-09-03-restored) DB is
positive on both metrics, not negative — this section's "~-3%"/"-3.1pp"
references were correct for the dataset instance that existed then, not the
current one. The frontend fixes described below (both metrics shown,
sign-aware coloring, low-n dimming) are still live and still correct code —
only the specific numbers are stale. **The CUPED follow-up plan below was
executed 2026-09-03** — see the current-state section for the feasibility
result.

Investigated the pooled attribution experiment's negative headline (~-3%)
properly, at the user's request, rather than tuning anything until it looked
better -- queried `attribution_experiment_results` directly instead of
trusting stale example numbers. Found a genuinely important thing: **the
amount-weighted and count-based recovery rates disagree in SIGN on the exact
same 811-invoice population** -- amount-weighted: treatment 33.2% vs. control
36.3% (-3.1pp); count-based (fraction of invoices recovered): treatment 62.2%
vs. control 60.1% (+2.1pp). `app/attribution/DECISIONS.md` already documents
that `recovery_rate_diff_z` is built on the COUNT-based rate specifically
("the natural quantity for a binomial variance"), but the API never actually
exposed that rate -- the dashboard could only ever show the noisier,
untested metric. Every z-score across all 20 slices (pooled + 3 segments + 4
actions + combinations) is under 1.5 -- nothing here is statistically
distinguishable from zero at this sample size, especially the small cells
(Mid-Market x ESCALATE is 7 treatment invoices).

**Three real fixes made, all frontend/API, no economics/data changed:**
1. **`lib/ui.tsx`**: `IconStat` had no way to render red -- the metrics
   page's "Incremental recovery"/"Incremental net recovery" tiles hardcoded
   `tone="success"`/`"accent"` regardless of the actual number's sign. Added
   a `danger` tone plus a `signTone(value)` helper; every incremental figure
   on the page now colors itself from its real sign.
2. **`app/api/schemas.py` + both `routes/attribution.py`/`routes/metrics.py`**:
   added `treatment_count_recovery_rate`/`control_count_recovery_rate`
   (nullable, already-existing DB columns, just never wired through) to
   `AttributionHeadline` and `AttributionSliceOut`. `frontend/app/metrics/page.tsx`
   now shows both metrics side by side ("By recovered amount (₹-weighted)"
   vs. "By invoice count (statistically tested)"), with the z-score/plain-
   language significance note attached to the one it's actually valid for.
   `AttributionCompareChart.tsx` gained a third mini bar-chart panel for the
   count-based comparison.
3. **`SliceLiftChart.tsx`/`SliceTable.tsx`**: any action/segment slice with
   fewer than 15 invoices per arm now renders at reduced opacity with an
   explanatory caption, so a 7-invoice cell doesn't visually compete with a
   200-invoice one.

**A pre-existing, unrelated test failure found while verifying these
fixes**: `tests/test_api_attribution.py::test_get_attribution_with_diagnostics_includes_archetype_breakdown_and_warnings`
fails on `assert "consistency_warnings" in body` -- confirmed via `git
stash` (ran the same test against the pre-fix code) that this predates
today's changes entirely, not something introduced here. Working theory,
not yet verified: the Day-5/6 ESCALATE-composition fix may have genuinely
eliminated the aggregation inconsistency `check_aggregation_consistency`
used to catch, making the test's assumption ("a warning always fires")
stale rather than the check itself being broken. **Not fixed yet** -- left
for a future session, see the handoff prompt already given to the user.

**CUPED variance reduction** (using the Day-2 recovery model's pre-treatment
calibrated probability as a covariate -- `X = probability` for the count
metric, `X = probability x amount` for the amount-weighted one) was
discussed and scoped as a legitimate follow-up, explicitly NOT to make the
negative number positive but to reduce the real chance-imbalance noise the
two-metrics-disagreeing-in-sign finding above points to. Not built yet --
the agreed plan is a cheap feasibility check first (compute `Corr(X,Y)` and
raw-vs-CUPED SE for both metrics) before committing to the full
implementation, since a small correlation isn't worth ~2h of work. If
built: keep raw and CUPED-adjusted estimates both (never replace), log a
"not used to select a preferred sign" rule in `app/attribution/DECISIONS.md`,
and add tests for unbiasedness, the covariate being genuinely pre-treatment,
and variance actually dropping.

## Home-Mac session (2026-09-02 evening–night): root-cause classifier + demo-consistency bug fixes

This entire session ran on the **home Mac**, not the work PC — the "Switching
machines" note below (written earlier the same day) already flagged that this
Mac's local Postgres was never re-synced past Day 1. The user had made DB
changes and a fresh dump on the work PC earlier that day but the dump never
made it over. Everything in this section happened against the home Mac's
local DB, independent of (and not yet reconciled with) whatever state the
work PC is actually in.

**RESOLVED 2026-09-03 — see "⚠ CURRENT CANONICAL STATE" near the top of
this file for the full root-cause account and the fix.** Summary: the home
Mac had run `synthetic.generator` fresh rather than restoring a transferred
dump, producing a different (business-column-identical, UUID-different)
dataset instance — which is why its own attribution numbers legitimately
differed from the work PC's. This work PC's DB has since been restored
from the home Mac's dump and is now the one canonical instance; the
INV-10706 fix mentioned below was real but was chasing a symptom of this
much larger effect, which is why it didn't close the gap. The paragraph
below is preserved as accurate history of what was known/tried *at the
time*, not as an open question anymore.

**Unresolved cross-machine DB discrepancy (carries forward, see handoff
prompt given to the user for a fresh session on the work PC):** the home
Mac's local attribution numbers didn't match this file's own documented
figures (pooled amount-weighted rate showed positive/+6-7% here vs. the
documented -3.1%). One real, confirmed cause was found and fixed (`INV-10706`
had a stray `attribution_records` row predating the one-invoice fix already
documented above — deleted, `evaluate.py` rerun) but this did **not** fully
close the gap, and the root cause of the remaining discrepancy was never
fully identified. Given time pressure, the user chose to treat this Mac's
current DB as the working state for tonight rather than keep chasing it —
**this is a deliberate, temporary call, not a resolution.** A fresh Claude
Code session was asked to investigate this properly on the work PC; check
for its findings/report before assuming either machine's numbers are
"correct."

**Also found and fixed along the way:** `evaluation_snapshots` (the table
from the "metrics staleness bug" fix above) was missing on this Mac entirely
— an `alembic upgrade head` had never been run here after that migration was
authored. Applied; `persist_evaluation.py` rerun.

### Root-cause classifier (new capability) — `app/ml/train_root_cause.py`

Fills a real gap identified against the Track-03 problem statement's own
"decides ... *why* it's late" claim: `true_root_cause` (cash_flow_stress /
dispute / oversight) was previously only ever used for the `dispute` value
(via `detect_dispute()`'s deterministic passthrough) — `cash_flow_stress` vs.
`oversight` was generated in the synthetic data but never predicted or
surfaced anywhere.

**Deliberately 2-class, not 3-class**: trained only on non-disputed
historical rows, predicting cash_flow_stress vs. oversight. Dispute is
excluded because it's already a reliable, deterministic, real-world-
observable signal the Policy Gate reads directly — having a model
re-predict it would be redundant and strictly worse. Evaluation output is
explicit that this answers "cash-flow stress vs. oversight *given the
invoice is not disputed*," never reported as a three-way production
accuracy number.

- **Methodology**: identical to Day 2's recovery/PTP models — same
  `build_feature_table()` (due_date cutoff, point-in-time safe, unchanged),
  same Experiment A time-based split, XGBoost + isotonic calibration.
  `app/ml/splits.py` gained `split_root_cause_table()`;
  `app/ml/labels.py` gained `root_cause_label()` (asserts it's never called
  on a disputed row).
- **Results**: ROC-AUC ≈0.757 (test), PR-AUC ≈0.648, Brier ≈0.196
  (calibrated). Archetype sanity check (verification-only, hidden ground
  truth) tracks the generator's own per-archetype `root_cause_weights`
  closely across all 7 non-disputed archetypes (e.g. `cash_constrained`:
  true 0.90 vs. predicted mean 0.79, observed 0.90).
- **Persisted** via `app/ml/persist.py` (now trains/saves all 3 models in
  one run) — `root_cause_model.joblib` + `root_cause_calibrator.joblib`.

**Live wiring — "context, not selector" by explicit design**: the pipeline
is Root Cause → Recovery Probability → Economics → Policy Gate → Final
Action, but Economics and Policy remain the sole decision authority. Root
cause only perturbs one input to Economics, via a small, **confidence-
gated, bounded** additive nudge to specific actions' uplift —
`ROOT_CAUSE_UPLIFT_ADJUSTMENT` in `app/decision/config.py` (cash_flow_stress
→ +0.03 PAYMENT_LINK; oversight → +0.02 EMAIL/WHATSAPP), applied only when
`root_cause_probability >= ROOT_CAUSE_CONFIDENCE_THRESHOLD` (0.6). Sized
specifically so it can only tip a genuinely close EV race, never override a
clear winner or bypass the materiality-gated abstention rule — confirmed by
tests (`test_economics.py`), including one live case where it flipped a
real invoice (`INV-10040`, the `low_value_stop` demo fixture) from WHATSAPP
to PAYMENT_LINK on a ~₹45 margin.

- `app/decision/economics.py`: `action_uplift()`/`probability_given_action()`/
  `compute_action_ev()`/`rank_actions()`/`recommend_action()` all gained
  optional `root_cause_label`/`root_cause_probability` params, defaulting to
  `None`/`0.0` (fully backward compatible — every existing caller/test
  unaffected).
- `app/decision/service.py`: `predict_root_cause()` added, called only when
  `not is_disputed`; wired into `decide_from_feature_row()`; `Decision`
  dataclass gained `root_cause_label`/`root_cause_confidence` fields.
- `app/decision/persist.py`: `decision_logs.model_scores["root_cause"]` —
  no migration needed (JSONB).
- **LangGraph agent layer wired too** (`app/agent/state.py` — `GraphState`
  gained `root_cause_label`/`root_cause_confidence`; `nodes.py` — `score_ml`
  now computes root cause before recovery probability, `run_economics`
  passes it through; `audit.py` — `_build_model_scores` includes it). This
  was a deliberate architectural-consistency fix: the LangGraph path (what
  `final_integration_pass`/the actual persisted 900-invoice decisions use)
  had NOT been wired in the first pass, only the Decision Service path had
  — meaning root cause would have shown up in the Metrics page's EV
  numbers but never in any real per-invoice decision trace. Fixed before
  it shipped half-done.
- **Frontend**: `lib/types.ts` gained `RootCauseScore`/`ModelScores.root_cause`.
  Invoice Detail page shows it as a compact row inside the existing
  "Predictive models" card (deliberately not a new grid column — it IS
  another model's output, lowest-risk placement). Observability page
  gained a third model-calibration card alongside Recovery/PTP.

### `decision_logs` had no reliable creation-order column — real bug, fixed

`timestamp` is the *business* event moment — identical across an entire
batch run (every invoice processed by the same `final_integration_pass`
invocation shares it) — so `ORDER BY timestamp DESC` alone could not break
ties, and Postgres doesn't guarantee row order without an explicit
tiebreaker. This meant `GET /api/invoices/{id}/decision` could
non-deterministically serve a **stale** row instead of the true latest one
whenever an invoice had been reprocessed more than once — confirmed live
(a root-cause-populated row silently lost to an older row with the exact
same timestamp). Fixed with a real `created_at` column (server-default
`now()`, migration `834e0783e3f1`) plus `ORDER BY timestamp DESC,
created_at DESC` in both `get_decision` and `get_timeline`
(`app/api/routes/decisions.py`), and the same fix in
`tests/test_audit.py`'s `_fetch_decision_log` helper (which also had a
false "content is deterministic across reruns" assumption baked in — it
isn't, simulated tools' `external_id` is a random UUID per dispatch).

**Caveat for any pre-migration row**: existing rows all got backfilled with
the SAME `created_at` (the moment the migration ran), so ties among
rows that already existed before this fix stay arbitrary — only rows
written *after* the migration get a genuinely distinct, orderable
`created_at`. Not retroactively fixable without knowing true historical
insert order, which was never tracked.

### Live pool: 900 → 391 open invoices (expected, not a bug)

The Day-5 attribution experiment's outcome simulation already flipped 509
of the original 900 live invoices to `invoices.status = PAID` (writing a
real payment + updating `account_state` directly). `build_live_feature_table()`
filters `status == OPEN`, so `final_integration_pass` (dry run and
`--persist`) now only ever processes the remaining 391 — this is the
correct, permanent steady-state going forward, not a regression. Confirmed
via direct query: `262 + 247 = 509` invoices across both attribution arms
flipped to PAID, `900 - 509 = 391` remaining OPEN, matching exactly.

### Header/timeline inconsistency for attribution-resolved invoices — real bug, fixed

For any of the 509 invoices attribution already resolved, `account_state`
(updated directly by attribution's `_apply_ledger_write_back`) correctly
shows `CLOSED · PAID`, but `decision_logs`/the Timeline — only ever updated
by a genuine decision-engine assessment, which never runs again once an
invoice leaves the open pool — kept showing whatever was decided *before*
the payment, with zero indication a payment happened since. Confirmed live
on multiple real invoices (e.g. a "wait -- no policy constraints triggered"
decision sitting right below a "CLOSED · PAID" header).

**Fix**: `app/attribution/persist.py` gained `build_closing_decision_log()`
— every future attribution-simulated recovery now automatically appends an
honest closing `decision_logs` entry ("recovered via the Day-5 attribution
experiment's randomized-holdout simulation, not a fresh assessment" —
`model_scores` stay explicit `None`, never fabricated). Wired into
`_apply_ledger_write_back()`. A one-off, idempotent, safe-to-rerun backfill
script (`app/attribution/backfill_closing_decision_logs.py`) retroactively
added the same entry for all 509 already-affected invoices (skips any
invoice that already has one, via a `CLOSING_ENTRY_MARKER` substring check
on `reason`).

**A real ordering bug was found and fixed WITHIN this same fix, live,
before it shipped**: the closing entry's timestamp can't simply be
`payment_date` — the real decision engine always business-dates its
assessments at the project's fixed "today" (`DEFAULT_AS_OF`, ~Aug 27,
2026), while attribution's `payment_date` is a *counterfactual* date
computed relative to the invoice's own `due_date`, which is very often
chronologically **earlier** than Aug 27. Using `payment_date` as-is made
the closing entry sort *before* the stale assessment it was meant to
supersede — confirmed live (shipped once, caught by the user re-checking
the actual page, not by a test). Fixed: `build_closing_decision_log()` now
queries `MAX(timestamp)` for that invoice and guarantees the closing entry
sorts strictly after it (`+1 minute` if needed), so it's always the true
last word in the timeline regardless of the business-date quirk. The first
(wrong-ordering) batch of 509 backfilled entries was deleted and
regenerated with the fix in place.

### `reset_and_reassess()` payment cleanup — two real bugs found and fixed in sequence

1. Original cleanup only deleted `Payment` rows with
   `method == "attribution_simulation"` — missed `app/agent/simulate_scenarios.py`'s
   Scenario A, which writes its own payment (previously `method="upi"`) as
   part of its "successful recovery" narrative for the `high_value_act`
   fixture (`INV-10706`). Confirmed live: after Scenario A ran once, that
   fixture was permanently stuck showing "already paid" on every future
   reassessment, since nothing ever cleaned up its payment.
2. **First fix attempt over-corrected**: made cleanup delete *all* Payment
   rows for the invoice unconditionally. This broke a different fixture —
   `already_paid_suppress` (`INV-10298`) needs its real, organic,
   generator-created payment to stay (that fixture's entire point is a real
   ledger payment despite `invoices.status` staying `open`) — and the
   generator's own `rng.choice(["bank_transfer", "upi", "cheque", "card"])`
   can coincidentally also pick `"upi"`, making method-based filtering
   ambiguous against a blanket delete. Confirmed live: this exact fixture
   broke immediately (`next_state=remind` instead of `CLOSED_PAID`) in the
   very next full-suite run.
3. **Correct fix**: gave Scenario A's payment its own unambiguous method
   string (`"scenario_rehearsal"`, distinct from the generator's random
   choices), and made cleanup conditional again — but on
   `SYNTHETIC_PAYMENT_METHODS = (ATTRIBUTION_WRITE_BACK_METHOD,
   SCENARIO_REHEARSAL_METHOD)` instead of write-back-only. Never touches an
   organic payment; always catches both known synthetic sources.
4. **The over-correction in step 2 had already committed real damage before
   the fix landed**: the unconditional-delete version genuinely ran (via
   `test_reset_and_reassess_already_paid_suppress_stays_suppressed`) and
   deleted `INV-10298`'s real organic payment from the DB. Confirmed via
   direct query (zero `payments` rows for that invoice afterward). Manually
   reconstructed a replacement matching `synthetic/generator.py`'s own
   `already_paid_false_alarm` logic exactly (`amount = invoice.amount`,
   `payment_date` within `due_date - [0,5] days`, `status=COMPLETED`) —
   **not bit-identical to the original random draw** (the exact seeded
   `rng.randint`/`rng.choice` outcome for this one row is unrecoverable),
   so this one invoice's payment will no longer match
   `synthetic/validators.py --fingerprint`'s exact reproducibility hash if
   that's ever rerun — a known, accepted, one-row exception, not a bug to
   chase. Scope confirmed contained to this single invoice: `reset_and_reassess`
   only ever runs against the 6 named demo fixtures, and of those, only
   `already_paid_suppress` is the `already_paid_false_alarm` archetype (the
   only one with an organic payment to lose in the first place).

### Demo fixture label staleness — cosmetic but user-facing, fixed

`synthetic/demo_fixtures.json`/`.py`'s `expected_action` field (rendered
verbatim in the frontend's "Example scenarios" menu subtitle, e.g. "decides
ESCALATE") was written once at pinning time and never updated after later
legitimate economics corrections changed the real answer.
`chronic_late_escalate` said "escalate" (real answer: `voice`, per the
already-documented Day-5 ESCALATE fix); `promise_breaker_reassess` said
"reassess" (never literally a persisted value, per Day-4 design — real
single-shot answer: `voice`). Both updated to say `voice`. Also clarified:
`app/api/routes/demo.py`'s `_LABELS` dict (the human-readable "Reliable
payer (correct abstention)"-style names shown in the menu) is a *separate*,
deliberately-curated mapping — 4 of the 6 map onto
`simulate_scenarios.py`'s own named scenarios (A/B/D/F), reusing the same
invoice rather than pinning a 7th. This is intentional design, not a
mismatch — but it means running `final_integration_pass --persist` (a
plain batch pass) can silently overwrite a scenario-specific narrative
(e.g. Scenario F's forced tool-failure demo on `INV-10184`) with an
unrelated plain decision. **Always run `python -m app.agent.simulate_scenarios`
last**, after any batch pass, before recording — it re-establishes the
correct narrative content for all 6 fixtures, and (thanks to the
`created_at` fix above) reliably wins the ordering now.

### Chart tooltip text-color bug — frontend, fixed, all 4 charts

`contentStyle` (background/border) was set on every `<Tooltip>` but
`itemStyle`/`labelStyle` (text color) was missing or incomplete on all 4
Metrics-page charts that use one (`SliceLiftChart`, `AttributionCompareChart`,
`DecisionMixChart`, `ComparisonChart`) — Recharts fell back to its own
default (black) text on hover, illegible against the dark tooltip
background. Fixed in all 4.

### Invoice-list status filter — 9 of 14 options were guaranteed dead ends, pruned

Confirmed via direct query that only 5 of the dropdown's 14
`AccountCurrentState` values ever actually return results (`wait`,
`remind`, `escalate`, `dispute_review`, `closed_paid`); 9 were empty.
5 of those 9 are **structurally permanent** dead ends per this project's
own design docs — `assessment`, `monitoring`, `broken`, `reassess`, and
plain `closed` are defined in the enum but never assigned by any rule in
the codebase (0 rows across the whole dataset, not just today). Removed
those 5 from `frontend/app/invoices/InvoiceFilters.tsx`'s
`CURRENT_STATE_OPTIONS`; kept `overdue`/`promise`/`kept`/`closed_abandoned`
even though currently empty, since those are genuinely reachable given a
different event sequence (a live promise round, etc.) — `closed_abandoned`
in particular is deliberately kept even at 0 results, matching the
`DemoCaseMenu`'s own existing "intentionally empty, and that's the point"
framing for that state.

### Testing

Ran the full backend suite many times across this session as fixes landed.
One more real gap surfaced on the last full run:
`tests/test_demo_scenarios.py::test_high_value_scenario_takes_an_active_intervention`
calls `decide()` directly with no cleanup (a Day-3-era test, predates
`simulate_scenarios.py` entirely) — so it's order-dependent on whatever
last touched `INV-10706` in the same session. After re-running
`simulate_scenarios.py` (Scenario A ends with that invoice paid), this test
failed on its old assumption. Fixed the same way `chronic_late_escalate`'s
test was already reframed: now accepts `STOP` as an equally valid,
Day-5/6-correct outcome alongside the five active-intervention types,
with a docstring explaining why (mirrors the `high_value_act`
low_value_stop/already_paid_suppress fixes above exactly — same root
pattern, different call site). **Confirmed fully green**: full suite,
307 tests, 0 failures, at the end of this session.

### Outstanding for the next session (before anything else)

**All 4 items below are now resolved/superseded as of 2026-09-03 — see
"⚠ CURRENT CANONICAL STATE" at the top of this file. Preserved for
history.**

1. ~~**Resolve the cross-machine DB discrepancy**~~ — done 2026-09-03, work
   PC's DB restored from this Mac's dump and is now the one canonical
   instance. **Reversed direction**: rather than the home Mac sending
   another dump to the work PC, the home Mac should now `git pull` (gets
   the survivorship-bias fix too) and re-run the same local pipeline
   (`app.ml.persist` → `final_integration_pass --persist` →
   `persist_evaluation` → `seed_demo`) against its OWN local DB — since
   that DB is the literal origin of the dump the work PC restored, this
   reproduces the identical canonical state without transferring anything.
2. ~~**Make a fresh dump of this Mac's DB**~~ — superseded by the above; no
   dump transfer needed in either direction now.
3. ~~CUPED variance reduction~~ — feasibility check run 2026-09-03 (see
   current-state section), passed the bar. Full build pending.
4. Then: remaining bug sweep, hosting (Vercel + Supabase sync, per the Day
   6 "What's next" section below), demo-recording rehearsal. Still
   applies.

## What's next (for future-session context)

Days 1–5 are all done (see their sections above). **Day 6, subtasks 1–15 of
17 done** — Phases A, B, C, and D are all complete; see "Day 6: Frontend
live-data wiring" and "Day 6, Phase C continued + Phase D" above for the full
account of what was built and every real bug found/fixed along the way.
Frontend is now fully wired to the live backend across all 4 console screens
(invoice list, invoice detail/explainability, metrics+attribution,
observability), hosted-integration-verified against the real deployed
Render+Supabase stack, has a working demo-case selector, and has been through
a full design/polish pass (design system, console redesign, landing page,
loading/error/404 states, page transitions).

**Remaining for Day 6 — only subtasks 16–17:**
1. **Deploy frontend** (Vercel) + add its origin to the backend's CORS
   allowlist (`app/main.py` currently only allows `http://localhost:3000`).
   Per the user's own plan (2026-09-02), this happens in a later session
   ("tomorrow"), alongside pushing today's local-only DB fix (see "End of
   day" above) to Supabase.
2. **Demo-mode rehearsal** — the exact click path for recording (Landing →
   Console → Invoice → Decision → Evidence → Economics → Policy → Action →
   Timeline → Experiment), no searching around during the real recording.
   Naturally follows #1 since it needs the real hosted URLs to rehearse
   against.

Day 6 evening–7 (unchanged from the original plan): README, pitch deck,
video script/recording, submission.

**IMPORTANT — REMIND USER BEFORE ANY DEMO RECORDING SESSION, OR AT END OF SESSION IF RECORDING HASN'T HAPPENED YET:** the video must showcase the hosted stack (deployed frontend + Render backend + Supabase DB), not `localhost`. Local `.env` should point at local Docker Postgres by default for all Day 6 dev work — Render's own `DATABASE_URL` (set in its dashboard) is independent of local `.env` and always points at Supabase already. But right before actually recording:
1. Temporarily point local `.env` (or run scripts with `DATABASE_URL` overridden) at Supabase.
2. **Push the 2026-09-02 metrics-fix + attribution-rerun work** (see the section above this one) to Supabase — it currently only exists locally. Either: (a) take a fresh local `pg_dump` and restore it into Supabase (matches this project's established transfer mechanism), or (b) re-run the same script sequence directly against Supabase (`persist.py` → `evaluate.py` → `final_integration_pass --persist` → `persist_evaluation.py`). Apply the `evaluation_snapshots` migration to Supabase first (`alembic upgrade head` against it) if using approach (b) or if the dump predates that table.
3. Run `python -m synthetic.seed_demo` against Supabase to reset the 6 curated demo fixtures there (a Day-5 restore from `deploy.dump` had reverted Supabase's fixtures to their broken pre-seed-demo state — local was fixed via this script on 2026-09-04 and again on 2026-09-02, Supabase has not been touched since, as of this note).
4. Point `.env` back to local afterward.
5. Record against the live hosted URLs, not localhost.

See the Day 5 sections above (subtask 8 deploy notes, subtask 9 seed_demo.py) and the "Day 6, Phase C: metrics staleness bug + attribution rerun" section above for the full history of why this local/Supabase split exists and what went wrong when it was blurred.

**Switching machines (work PC → home PC) mid–Day 6, this session:** after
this commit, `frontend/lib/` (previously never-tracked due to the
`.gitignore` bug fixed today) is finally in git, so a fresh `git pull` at
home gets the real, current frontend — verify this by checking
`frontend/lib/types.ts` and `api.ts` actually exist post-pull, not by
assuming. The home PC's **local Postgres was only ever synced with Day-1's
data** (see the "Tonight: Day-1 home-PC transfer" section above) — it has
never been re-synced through Days 2–6, so it will NOT have the ML
models/decision_logs/attribution results/demo fixtures the frontend now
expects. Two options for continuing Day 6 (mostly design/polish work, which
needs *some* real app screens to look at) at home: (a) point
`frontend/.env.local` at the deployed Render URL (`https://b2b-receivables-intelligence.onrender.com`)
and design against the real hosted Supabase data directly — simplest,
matches what was already verified working in subtask 9, but Supabase's 6
demo fixtures are currently in their stale broken state (see the reminder
above) until `seed_demo.py` is run against it; or (b) do a fresh
`pg_dump`/`pg_restore` transfer of the work PC's current local DB, same
mechanism as the original Day-1 transfer. (a) is recommended for Day 6's
remaining design-focused subtasks, given the time pressure and that a
Postgres re-sync is a detour with no design-work benefit.
