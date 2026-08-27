# CLAUDE.md — B2B Receivables Decision Intelligence

Single source of truth for this project across sessions. Read this first in any new session before touching code.

## What this is

Submission for **Razorpay AI Buildathon 2026, Track 03 (AI Revenue Recovery)**. Not "an AI collections bot" — a decision engine that, for every overdue B2B invoice, decides *whether* chasing it is worth it, *why* it's late, *how confident* to be in any payment promise, *which* intervention is cheapest-and-effective, executes it inside compliant guardrails, and *proves* how much money it actually caused to come in vs. what would have arrived anyway (via a randomized holdout/attribution engine).

Full architecture spec (11-table Postgres+pgvector schema, XGBoost recovery/PTP models, LangGraph orchestration, deterministic policy gate, attribution engine, Next.js frontend) was provided by the user as a markdown doc at the start of the project — not stored in the repo, but its content is what everything below implements. Key sections referenced throughout this file: §4 (data model), §5 (ML layer), §6 (synthetic dataset), §9 (five completeness gaps), §10 (7-day build plan).

7-day build plan, ending with a demo video submission. **Today (2026-08-27) is Day 1.**

## Repo layout

```
b2b-receivables-intelligence/
  README.md, .gitignore, CLAUDE.md          <- repo root
  backend/
    app/
      core/            config.py (pydantic-settings), db.py (SQLAlchemy engine/session/Base)
      models/          11 SQLAlchemy models + enums.py (see Schema below)
    alembic/           migrations (env.py hand-authored, not `alembic init`-generated)
    synthetic/
      archetypes.py    8 archetypes' ground-truth parameters
      generator.py     deterministic dataset generator (SEED=42)
      validators.py    validation suite + dataset summary + reproducibility fingerprint
      demo_fixtures.py selects/pins 6 curated demo invoices -> demo_fixtures.json
    tests/             pytest suite (DB foundation + generator/validation tests)
    docker-compose.yml Postgres+pgvector container definition
    requirements.txt   Day-1 Python deps (see exact versions below)
    .env.example / .env (.env gitignored, never committed)
  frontend/            empty placeholder — Next.js app lands later (per the 7-day plan, Day 3 scaffold / Day 6 wiring)
```

## Environment (work PC)

- **Python 3.14.5**, venv at `backend/venv` (created via `python -m venv venv`, not `uv` — user's explicit preference despite `uv` being installed). Installed via `pip install -r requirements.txt`, not pinned in the committed `requirements.txt` (it lists bare package names) — actual installed versions, confirmed from `venv/Lib/site-packages/*.dist-info`:
  - fastapi 0.141.1, uvicorn 0.52.4, sqlalchemy 2.0.52, alembic 1.19.1, psycopg 3.3.4 (+psycopg-binary 3.3.4), pgvector (python pkg) 0.5.0, pydantic 2.13.4 / pydantic-settings 2.15.0, python-dotenv 1.2.3, pandas 3.0.5, numpy 2.5.2, faker 40.37.0, pytest 9.1.1.
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

## ML methodology requirements for Day 2 (specified in advance, not yet implemented)

- **Customer-level train/test split (80/20 by customer, never by row)** — split customers first, take all their invoices with them, to prevent per-customer aggregate-feature leakage.
- **Time-based holdout** — train on months 1–9 of the historical pool, evaluate on months 10–11 (the pool's 12-month window was specifically sized for this). Every rolling/aggregate feature must only use data available as of that invoice's own `issue_date` — no future leakage.

## Day-1 (work PC) checklist status

Done: GitHub/SSH/git-identity setup, project structure (backend/frontend split), `.env.example`, Docker Postgres+pgvector, all 11 tables + migrations, synthetic generator (all entity types), validation suite (all 7 checks + reproducibility), demo fixtures, pytest suite (12 tests, all passing).

Left today: final commit/push of this CLAUDE.md itself (do after this file is reviewed), then the **Day-1 home-PC leg** — see below.

## Tonight: Day-1 home-PC transfer

Per the user's own plan: prove the Day-1 foundation moves between environments via `pg_dump`/`pg_restore`, not by re-running the generator on a new machine (that only proves code-determinism, not actual data portability — both get validated, separately, on purpose).

1. At work, once the dataset above is in its final validated state: `pg_dump -U postgres -d receivables_ai -Fc -f receivables_day1.dump` (against the Docker container, e.g. via `docker exec` or a port-5433 connection), verify with `pg_restore --list receivables_day1.dump`.
2. **Never commit the dump to git** — `.gitignore` already excludes `*.dump`/`*.dmp`. Since the repo folder lives inside OneDrive (`...\Desktop\b2b-receivables-intelligence`), placing the dump in a gitignored subfolder there lets OneDrive sync it to the home PC automatically — no manual transfer step needed, as long as the same OneDrive account is signed in on both machines.
3. At home: clone/pull the repo, stand up the same Docker Postgres setup (`pgvector/pgvector:pg16`, port 5433 — or pull pg18 fresh there, doesn't need to match this machine's image choice), create an empty `receivables_ai` db with pgvector enabled, then `pg_restore` the dump directly — this restores schema + data in one shot. Don't re-run `alembic upgrade head` or the generator to recreate it; that's a different, separate check.
4. Separately (per the checklist's own "Final local verification" section), re-run `python -m synthetic.generator` at home with the same `SEED=42` and confirm the fingerprint matches what was produced at work — this is the *code*-portability proof, independent of whether the dump restored correctly.

## What's next after tonight (remaining 6-day plan, for future-session context)

Day 2: feature engineering, XGBoost recovery-probability + PTP models, calibration, time-aware evaluation per the ML methodology section above. Day 3: hybrid BM25+pgvector retrieval, Economics Engine, Policy/Safety Gate, Next.js frontend scaffold (3 screens). Day 4: LangGraph orchestration, account state machine, action/tool layer incl. real Razorpay test-mode Payment Links. Day 5: attribution engine (randomized holdout), dashboard API, deploy backend+DB, `seed_demo.py`. Day 6: frontend wiring, deploy frontend, deliberate failure-handling demo. Day 6 evening–7: README, pitch deck, video script/recording, submission.
