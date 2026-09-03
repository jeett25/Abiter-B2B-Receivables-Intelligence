# B2B Receivables Decision Intelligence

**Submission for Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery)**
Webstie Link : https://arbiter-brown-five.vercel.app/

Not a collections bot. A decision engine that, for every overdue B2B invoice, decides:

- **Whether** chasing it is worth it (expected-value economics, not "email everyone")
- **Why** it's late (a root-cause classifier: cash-flow stress vs. oversight vs. dispute)
- **How confident** to be in any payment promise a customer makes (a calibrated Promise-to-Pay model)
- **Which** intervention is cheapest-and-effective (WhatsApp, voice, escalation, a real payment link)
- Executes it inside **compliant guardrails** (a deterministic policy/safety gate — business hours, contact caps, dispute handling, human-approval routing)
- **Proves** how much money it actually caused to come in vs. what would have arrived anyway, via a randomized holdout/attribution experiment

Every recommendation is explainable end to end: the recovery-probability score, the root cause, the retrieved similar historical cases, the expected-value table across every candidate action, and the exact policy rule that approved or blocked it.

---

## Live demo

| | |
|---|---|
| **App** | _add Vercel URL after deploy_ |
| **API** | https://b2b-receivables-intelligence.onrender.com (`/docs` for interactive OpenAPI) |
| **Video walkthrough** | _add link_ |

> The hosted backend is on Render's free tier and spins down after 15 minutes idle — the first request after a while can take ~30–60s to wake up.

---

## What's inside

A full-stack decision system built on real historical data, not a wrapper around an LLM prompt:

- **11-table Postgres schema** (+pgvector) modeling merchants, customers, invoices, payments, promises, interactions, recovery actions, decision logs, account state, and attribution records
- **A 9,900-invoice synthetic dataset**, generated from 8 behaviorally distinct customer archetypes with realistic payment/delay/dispute patterns, deterministic and reproducible (`SEED=42`)
- **Three calibrated XGBoost models**: Recovery Probability, Promise-to-Pay credibility, and Root-Cause classification — all point-in-time-safe (every feature is computed strictly as of the moment a real decision would have to be made, no future leakage)
- **A hybrid retrieval engine** (BM25 + pgvector + structured filters, fused via Reciprocal Rank Fusion) that surfaces similar historical cases to justify each recommendation
- **A deterministic Economics Engine + Policy/Safety Gate** — expected-value ranking across candidate actions, then an 8-rule compliance cascade (already-paid detection, dispute handling, contact caps, cooldowns, business hours, human-approval routing for large amounts) that has the final say, never the model
- **A LangGraph-orchestrated agent layer** that ties scoring → retrieval → economics → policy → action dispatch → audit into one event-driven pipeline, with real (test-mode) Razorpay payment-link integration and LLM-based promise extraction (Groq)
- **A randomized-holdout Attribution Engine** that measures incremental recovery against a true control group — not just an expected-value estimate — with CUPED variance reduction on top
- **A Next.js console** — invoice list/detail with full decision explainability, a metrics + attribution dashboard, and an observability page for model/retrieval/agent reliability

Every one of these layers is backed by an evidence-based decisions log (see [`docs/`](docs/)) — real bugs found, real trade-offs made, and why.

---

## Architecture

```
┌─────────────┐      ┌──────────────────────────────────────────────┐      ┌─────────────┐
│   Next.js    │◄────►│                FastAPI (Render)               │◄────►│  Postgres    │
│  console     │ REST │  /api/invoices  /api/invoices/{id}/decision   │ SQL  │  + pgvector  │
│  (Vercel)    │      │  /api/metrics   /api/attribution              │      │  (Supabase)  │
└─────────────┘      │  /api/demo-fixtures                            │      └──────┬──────┘
                       └──────────────────────────────────────────────┘             │
                                                                                       │ offline / batch
                       ┌──────────────────────────────────────────────┐             │
                       │        LangGraph agent (backend/app/agent)     │◄────────────┘
                       │  ingest → build features → score (Recovery /   │
                       │  PTP / Root Cause) → retrieve similar cases →  │
                       │  economics (EV per action) → policy gate →     │
                       │  dispatch action → persist decision + state    │
                       └──────────────────────────────────────────────┘
```

The API is **read-only over already-persisted state** — no live model/LLM calls happen in the request path, so the dashboard stays fast and reproducible. Scoring and decisioning run as an offline/batch pipeline (`app.agent.final_integration_pass`) that writes to `decision_logs`/`account_state`, which the API simply reads.

---

## Tech stack

**Backend**: Python 3.14, FastAPI, SQLAlchemy 2.0, Alembic, Postgres 16 + pgvector, XGBoost, scikit-learn, fastembed, LangGraph, Groq (LLM), Razorpay (test mode)
**Frontend**: Next.js 16 (App Router), TypeScript, Tailwind CSS, Recharts, Framer Motion
**Hosting**: Render (API), Supabase (Postgres), Vercel (frontend)
**Testing**: pytest, 300+ tests covering leakage-safety, policy correctness, state-machine transitions, and end-to-end agent scenarios

---

## Repository layout

```
backend/
  app/
    core/        config + DB session
    models/      SQLAlchemy models (12 tables) + enums
    ml/          feature engineering, Recovery/PTP/Root-Cause model training
    decision/    Economics Engine + deterministic Policy/Safety Gate
    retrieval/   hybrid BM25 + pgvector case retrieval
    agent/       LangGraph orchestration, tools, state machine, audit trail
    attribution/ randomized-holdout experiment + CUPED variance reduction
    api/         FastAPI routes (read-only dashboard API)
  synthetic/     dataset generator, validators, demo-fixture pinning
  alembic/       database migrations
  tests/         pytest suite
frontend/
  app/           Next.js pages (invoices, metrics, observability, landing)
  lib/           typed API client + shared types
docs/
  CLAUDE.md               full build log — every decision, every bug found and fixed, day by day
  *-DECISIONS.md           evidence-backed rationale for each subsystem's key defaults
```

---

## Running it locally

### Prerequisites
Python 3.12+, Node 20+, Docker.

### 1. Database
```bash
cd backend
docker compose up -d          # Postgres 16 + pgvector on localhost:5433
```

### 2. Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env          # fill in DATABASE_URL (already defaulted for the Docker setup above)
alembic upgrade head

# generate the synthetic dataset
python -m synthetic.generator
python -m synthetic.demo_fixtures
python -m synthetic.validators

# train + persist the ML models
python -m app.ml.persist

# run the full agent pipeline over the live invoice pool
python -m app.agent.final_integration_pass --persist
python -m app.decision.persist_evaluation
python -m synthetic.seed_demo

uvicorn app.main:app --reload    # http://localhost:8000, docs at /docs
```

### 3. Frontend
```bash
cd frontend
npm install
cp .env.example .env.local    # NEXT_PUBLIC_API_BASE_URL defaults to localhost:8000
npm run dev                    # http://localhost:3000
```

### 4. Run tests
```bash
cd backend && pytest -q
```

---

## Results (current canonical run)

Measured against the 391-invoice live pool at the time of writing — see `docs/CLAUDE.md`'s "Current canonical state" section for the full, always-up-to-date numbers.

| | Baseline ("email everyone") | Decision engine |
|---|---|---|
| Net expected recovered | ₹9,871,714 | ₹11,292,861 |
| Recovery rate | 31.8% | 36.5% |

**Net EV improvement: +₹1,421,147** from the decision layer alone, on the same invoice population, same underlying probability model — isolating the value of the economics + policy layer, not just better prediction.

**Randomized-holdout attribution** (811 eligible invoices, 404 treatment / 407 control): treatment arm recovered **+6.6pp more by value** and **+3.7pp more by count** than the untreated control group — the causal effect of actually intervening, not just a model's estimate of it.

---

## What makes this different from "an AI collections bot"

1. **The LLM never makes the decision.** It's used exactly once — to extract a payment promise from a customer's message. Everything downstream (whether to act, what to do, whether it's compliant) is deterministic and auditable.
2. **Every score is calibrated**, not just ranked — probabilities are isotonic/Platt-calibrated against real historical outcomes, because the Economics Engine multiplies them directly into a rupee figure.
3. **The Policy Gate can override the model.** A dispute, a cooldown window, a max-contact-attempts breach, or outside business hours will block or reroute an otherwise-profitable action — compliance isn't a filter bolted on after the fact, it's structurally the last word.
4. **Impact is measured, not assumed.** A randomized holdout separates "the model predicted recovery" from "our intervention caused recovery" — most systems in this space only ever report the former.
