# CLAUDE.md — B2B Receivables Decision Intelligence

Single source of truth for this project across sessions. Read this first in any new session before touching code.

## What this is

Submission for **Razorpay AI Buildathon 2026, Track 03 (AI Revenue Recovery)**. Not "an AI collections bot" — a decision engine that, for every overdue B2B invoice, decides *whether* chasing it is worth it, *why* it's late, *how confident* to be in any payment promise, *which* intervention is cheapest-and-effective, executes it inside compliant guardrails, and *proves* how much money it actually caused to come in vs. what would have arrived anyway (via a randomized holdout/attribution engine).

Full architecture spec (11-table Postgres+pgvector schema, XGBoost recovery/PTP models, LangGraph orchestration, deterministic policy gate, attribution engine, Next.js frontend) was provided by the user as a markdown doc at the start of the project — not stored in the repo, but its content is what everything below implements. Key sections referenced throughout this file: §4 (data model), §5 (ML layer), §6 (synthetic dataset), §9 (five completeness gaps), §10 (7-day build plan).

7-day build plan, ending with a demo video submission. Days 1–4 are all done (see their sections below). **Day 5 starts next session.**

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

## What's next (for future-session context)

Days 1–4 are all done (see their sections above). **Day 5, in progress this session**: attribution engine (randomized holdout, ACTION_UPLIFT correction for ESCALATE actually applied — see app/attribution/ and app/decision/ DECISIONS.md files) and the dashboard API (app/api/, 6 endpoints, see app/api/DECISIONS.md) are both done. **Remaining for Day 5**: execute the deploy (target decided — see the "Day 5, subtask 8" section above; steps prepared, execution in progress) and `seed_demo.py` (still genuinely load-bearing, not just polish — the live pool's `account_state`/`payments` have now been permanently mutated twice, once by Day 4's final_integration_pass and once by Day 5's attribution write-back, so this is what makes repeatable demo recording possible).

Day 6: frontend wiring to the live backend (now that Day 5 built the API it needs) + the deferred visual/CSS design pass, deploy frontend, deliberate failure-handling demo dry-run (Day 4 already has a rehearsed version of this in `simulate_scenarios.py`'s Scenario F — reuse it, don't rebuild it). Day 6 evening–7: README, pitch deck, video script/recording, submission.
