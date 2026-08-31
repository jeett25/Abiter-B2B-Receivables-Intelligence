"""FastAPI dashboard API -- Day 5, subtask 7.

Run locally: uvicorn app.main:app --reload  (from backend/)
OpenAPI docs at /docs, free credibility signal per the master doc -- no
extra work needed, FastAPI generates it from these routers' response_models.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import attribution, decisions, invoices, metrics

app = FastAPI(
    title="B2B Receivables Decision Intelligence API",
    description="Read-only dashboard API over invoices/account_state/decision_logs/attribution_records.",
)

# Local Next.js dev server only for now -- add the deployed frontend origin
# once Day 6 deploys it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(invoices.router)
app.include_router(decisions.router)
app.include_router(metrics.router)
app.include_router(attribution.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
