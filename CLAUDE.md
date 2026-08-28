# CLAUDE.md — B2B Receivables Decision Intelligence

Single source of truth for this project across sessions. Read this first in any new session before touching code.

## What this is

Submission for **Razorpay AI Buildathon 2026, Track 03 (AI Revenue Recovery)**. Not "an AI collections bot" — a decision engine that, for every overdue B2B invoice, decides *whether* chasing it is worth it, *why* it's late, *how confident* to be in any payment promise, *which* intervention is cheapest-and-effective, executes it inside compliant guardrails, and *proves* how much money it actually caused to come in vs. what would have arrived anyway (via a randomized holdout/attribution engine).

Full architecture spec (11-table Postgres+pgvector schema, XGBoost recovery/PTP models, LangGraph orchestration, deterministic policy gate, attribution engine, Next.js frontend) was provided by the user as a markdown doc at the start of the project — not stored in the repo, but its content is what everything below implements. Key sections referenced throughout this file: §4 (data model), §5 (ML layer), §6 (synthetic dataset), §9 (five completeness gaps), §10 (7-day build plan).

7-day build plan, ending with a demo video submission. Day 1 (2026-08-27) and Day 2 (2026-08-28) are both done. **Day 3 starts next session.**

## Repo layout

```
b2b-receivables-intelligence/
  README.md, .gitignore, CLAUDE.md          <- repo root
  backend/
    app/
      core/            config.py (pydantic-settings), db.py (SQLAlchemy engine/session/Base)
      models/          11 SQLAlchemy models + enums.py (see Schema below)
      ml/              Day-2 feature engineering + Recovery/PTP models -- see "Day 2: ML layer" below
        config.py        HORIZON_DAYS, recency windows, split ratios, calibration bounds, SEED -- no synthetic/ import
        features.py      DB->pandas, is_resolved_before(), rolling+recency features, outstanding_ratio
        labels.py        recovery_label(), build_ptp_table(), T-reconstruction, class-balance diagnostics
        splits.py        Experiment A (time-based, 4-way) and B (customer-based) splits
        evaluate.py      classification_metrics(), reliability_table(), archetype_sanity_check()
        train_recovery.py  fit + isotonic-calibrate + evaluate recovery model, CLI entry
        train_ptp.py       fit + Platt-calibrate + evaluate PTP model, CLI entry
        persist.py         joblib save/load + FeatureSnapshot DB writer, CLI entry
        DECISIONS.md       evidence-backed modeling decisions log -- read this before changing any ML default
        artifacts/         gitignored -- .joblib models + metrics.json, regenerate via `python -m app.ml.persist`
    alembic/           migrations (env.py hand-authored, not `alembic init`-generated)
    synthetic/
      archetypes.py    8 archetypes' ground-truth parameters
      generator.py     deterministic dataset generator (SEED=42)
      validators.py    validation suite + dataset summary + reproducibility fingerprint
      demo_fixtures.py selects/pins 6 curated demo invoices -> demo_fixtures.json
    tests/             pytest suite (DB foundation + generator/validation + ML tests, 30 total)
    docker-compose.yml Postgres+pgvector container definition
    requirements.txt   Python deps (see exact versions below) -- now includes xgboost, scikit-learn (Day 2)
    .env.example / .env (.env gitignored, never committed)
  frontend/            empty placeholder — Next.js app lands later (per the 7-day plan, Day 3 scaffold / Day 6 wiring)
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

## Schema (11 tables — architecture doc §4)

`merchants`, `customers`, `invoices`, `payments`, `payment_promises`, `interactions`, `recovery_actions`, `decision_logs`, `account_state`, `attribution_records`, `feature_snapshots`. All UUID primary keys (Python-generated via `uuid.uuid4()`, **explicitly set at construction time** — see gotcha below). Full column-by-column breakdown was given in-session; the model files in `backend/app/models/` are the authoritative source now.

Notable deviations/additions beyond the doc's literal field list (all deliberate, confirmed with user):
- `invoices.invoice_number` — human-readable label (`INV-1042`) for demo/dashboard legibility; UUID stays the real key.
- `invoices.true_root_cause` — synthetic-only ground truth (`cash_flow_stress`/`dispute`/`oversight`), added via a second migration, supports a future root-cause classification stage implied by the pitch ("decides ... *why* it's late").
- `customers.archetype`, `true_recovery_probability`, `true_promise_keep_probability` — synthetic-only ground truth, hidden from ML models, used only by the generator/validators.
- `account_state` and `attribution_records` use `invoice_id` as their primary key (1:1 per invoice) since the doc's own field list for those two tables never included a separate `id`.
- Enums beyond the doc's explicit ones: `payments.status`, `recovery_actions.action_type` (WAIT/EMAIL/WHATSAPP/PAYMENT_LINK/VOICE/ESCALATE/STOP — from architecture §3), `recovery_actions.policy_result` (allowed/blocked/escalated). Doc-explicit enums: `invoices.status`, `payment_promises.status`, `account_state.current_state` (full §9 state machine), `attribution_records.treatment_group`.
- pgvector extension is enabled but **no vector column exists yet** — deferred to Day 3 (hybrid retrieval), added via its own migration then so the embedding dimension isn't guessed prematurely.

Migrations: `f77b57a510b7_initial_schema.py` (all 11 tables), `f53cb24488a8_add_invoice_root_cause.py` (the one added column). Both applied (`alembic upgrade head` succeeded, verified via psql `\dt` and pgAdmin).

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

## Day-1 (work PC) checklist status

Done: GitHub/SSH/git-identity setup, project structure (backend/frontend split), `.env.example`, Docker Postgres+pgvector, all 11 tables + migrations, synthetic generator (all entity types), validation suite (all 7 checks + reproducibility), demo fixtures, pytest suite (12 tests, all passing).

## Day-2 checklist status

Done: `app/ml/` package (config, features, labels, splits, evaluate, train_recovery, train_ptp, persist), recovery model trained+calibrated+sanity-checked, PTP model trained+calibrated+sanity-checked, future-leakage regression tests, model artifacts + FeatureSnapshot rows persisted, full pytest suite green (30 tests), `DECISIONS.md` written. See "Day 2: ML layer" above for the full summary.

Explicitly not done (by decision, not oversight): expected-payment-date regression model (skipped), SHAP explanations (deferred/optional).

## Tonight: Day-1 home-PC transfer

Per the user's own plan: prove the Day-1 foundation moves between environments via `pg_dump`/`pg_restore`, not by re-running the generator on a new machine (that only proves code-determinism, not actual data portability — both get validated, separately, on purpose).

1. At work, once the dataset above is in its final validated state: `pg_dump -U postgres -d receivables_ai -Fc -f receivables_day1.dump` (against the Docker container, e.g. via `docker exec` or a port-5433 connection), verify with `pg_restore --list receivables_day1.dump`.
2. **Never commit the dump to git** — `.gitignore` already excludes `*.dump`/`*.dmp`. Since the repo folder lives inside OneDrive (`...\Desktop\b2b-receivables-intelligence`), placing the dump in a gitignored subfolder there lets OneDrive sync it to the home PC automatically — no manual transfer step needed, as long as the same OneDrive account is signed in on both machines.
3. At home: clone/pull the repo, stand up the same Docker Postgres setup (`pgvector/pgvector:pg16`, port 5433 — or pull pg18 fresh there, doesn't need to match this machine's image choice), create an empty `receivables_ai` db with pgvector enabled, then `pg_restore` the dump directly — this restores schema + data in one shot. Don't re-run `alembic upgrade head` or the generator to recreate it; that's a different, separate check.
4. Separately (per the checklist's own "Final local verification" section), re-run `python -m synthetic.generator` at home with the same `SEED=42` and confirm the fingerprint matches what was produced at work — this is the *code*-portability proof, independent of whether the dump restored correctly.

## What's next (remaining 5-day plan, for future-session context)

Day 1 and Day 2 are both done (see their sections above). **Day 3 next**: hybrid BM25+pgvector retrieval, Economics Engine (`EV(a) = P(recovery|a,x) * Amount - Cost - Friction` — the calibrated, clipped recovery/PTP probabilities from Day 2 feed directly into this), Policy/Safety Gate, Next.js frontend scaffold (3 screens), and the pgvector embedding-column migration deferred from Day 1. Day 4: LangGraph orchestration, account state machine, action/tool layer incl. real Razorpay test-mode Payment Links. Day 5: attribution engine (randomized holdout), dashboard API, deploy backend+DB, `seed_demo.py`. Day 6: frontend wiring, deploy frontend, deliberate failure-handling demo. Day 6 evening–7: README, pitch deck, video script/recording, submission.
