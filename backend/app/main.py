"""FastAPI dashboard API -- Day 5, subtask 7.

Run locally: uvicorn app.main:app --reload  (from backend/)
OpenAPI docs at /docs, free credibility signal per the master doc -- no
extra work needed, FastAPI generates it from these routers' response_models.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import attribution, decisions, demo, invoices, metrics

app = FastAPI(
    title="B2B Receivables Decision Intelligence API",
    description="Read-only dashboard API over invoices/account_state/decision_logs/attribution_records.",
)

# Local Next.js dev server + the deployed Vercel frontend (Day 6, subtask 16).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://arbiter-brown-five.vercel.app",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(invoices.router)
app.include_router(decisions.router)
app.include_router(metrics.router)
app.include_router(attribution.router)
app.include_router(demo.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
