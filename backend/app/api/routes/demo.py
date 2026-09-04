"""Subtask 10 (Day 6) -- expose the 6 curated demo fixtures over the API so
the frontend has a single source of truth for their invoice_ids, instead of
hardcoding them and silently going stale if synthetic/seed_demo.py ever
re-pins different invoices.

Reads the exact same synthetic/demo_fixtures.json that
app/agent/simulate_scenarios.py and synthetic/seed_demo.py already read from
-- never duplicated or copied.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Invoice

router = APIRouter(prefix="/api/demo-fixtures", tags=["demo"])

_FIXTURES_PATH = Path(__file__).parent.parent.parent.parent / "synthetic" / "demo_fixtures.json"

# Human-readable labels -- demo_fixtures.json's own keys are stable
# identifiers (see its own history in CLAUDE.md/seed_demo.py), not meant for
# display. 5 of these map directly onto app/agent/simulate_scenarios.py's
# named scenarios (A/B/D/F/G, the last added 2026-09-04); the other
# (low_value_stop) is a real Day-1 curated case without its own lettered
# scenario, included anyway since it's a genuine, useful economics example.
_LABELS = {
    "high_value_act": "Successful recovery",
    "promise_breaker_reassess": "Broken promise",
    "already_paid_suppress": "Already paid (false alarm)",
    "chronic_late_escalate": "Tool/LLM failure (forced, rehearsed)",
    "reliable_payer_wait": "High-confidence abstention",
    "low_value_stop": "Low value (cheapest justified action)",
}

# 2026-09-03: added after a real gap was found -- the menu label alone gives
# no context once you've clicked through to the Invoice Detail page itself,
# so a first-time viewer (a recruiter, not someone who's read the source)
# has no way to tell "the voice call failed" apart from an actual bug, or
# realize a WAIT decision was independently validated by a real outcome.
# Written for that reader specifically: plain language, states what's being
# demonstrated AND why it's a deliberate, meaningful example, not a random
# invoice. Kept in this same file as _LABELS (one source of truth for both,
# no drift risk) rather than duplicated in the frontend.
_EXPLANATIONS = {
    "reliable_payer_wait": (
        "Arbiter predicted 99% recovery and chose WAIT while the invoice was still eligible for "
        "intervention -- nothing external prevented it from acting. A later payment confirmed the "
        "account recovered without an intervention. The STOP shown in the current state is a later "
        "safety closure after the payment was recorded, not the original recommendation -- see the "
        "Timeline below for the actual sequence."
    ),
    "chronic_late_escalate": (
        "This invoice's real, economically-justified action is VOICE. To prove the system doesn't "
        "panic or improvise when a tool call fails, this run deliberately forces the voice-call API "
        "to fail. Watch it retry, exhaust its retries, and safely fall back to WAIT -- recording the "
        "failure honestly instead of guessing a different channel. This is the resilience design "
        "working as intended, not a bug. (Its 'Attribution' badge reflects a separate, retrospective "
        "measurement label from the Day-5 experiment -- that label never gates the live agent's real "
        "dispatch, which independently evaluates and acts on every live invoice regardless of group.)"
    ),
    "promise_breaker_reassess": (
        "A real (simulated) customer WhatsApp message is sent, a live LLM call extracts a payment "
        "promise from it, and once that promise is confirmed broken, the system automatically "
        "reassesses and produces a fresh decision -- demonstrating the event-driven reassessment "
        "loop, not a one-shot script. This exact run was rehearsed and persisted ahead of time, so "
        "what you're viewing now is fixed; only a fresh rerun of the rehearsal script would call the "
        "LLM again and could vary slightly."
    ),
    "low_value_stop": (
        "Even for a customer archetype with weaker payment history, this invoice is small enough "
        "that most interventions net only a little more than doing nothing. The engine still picks "
        "the cheapest economically-justified action rather than an expensive channel -- correct cost "
        "discipline, distinct from the reliable-payer case above, which abstains entirely. (Its "
        "'Attribution' badge is the same retrospective, non-gating label described on the tool-failure "
        "scenario.)"
    ),
    "high_value_act": (
        "A ₹500,000 invoice from a genuinely higher-risk customer (~10% organic recovery probability) "
        "-- economically worth a real, assertive channel, unlike the abstention cases above. A fresh "
        "assessment dispatches VOICE for real, then this scenario manually injects a payment-received "
        "event to demonstrate the full chain: active intervention, then payment, then the account "
        "correctly closing out to CLOSED_PAID."
    ),
    "already_paid_suppress": (
        "A real payment already exists for this invoice, but its status field hasn't been reconciled "
        "yet -- a common real-world lag. The Policy Gate checks the actual payment ledger directly, "
        "never just the status flag, and correctly stops any further contact rather than chasing "
        "someone who's already paid."
    ),
}


class DemoFixtureOut(BaseModel):
    key: str
    label: str
    explanation: str
    invoice_number: str
    invoice_id: UUID
    expected_action: str


@router.get("", response_model=list[DemoFixtureOut])
def list_demo_fixtures(db: Annotated[Session, Depends(get_db)]):
    fixtures = json.loads(_FIXTURES_PATH.read_text())
    numbers = [f["invoice_number"] for f in fixtures.values()]
    rows = db.execute(select(Invoice.invoice_number, Invoice.id).where(Invoice.invoice_number.in_(numbers))).all()
    id_by_number = {r.invoice_number: r.id for r in rows}

    out: list[DemoFixtureOut] = []
    for key, fixture in fixtures.items():
        invoice_number = fixture["invoice_number"]
        invoice_id = id_by_number.get(invoice_number)
        if invoice_id is None:
            # Defensive only -- would mean the DB and demo_fixtures.json have
            # drifted (e.g. a fresh regenerate without re-pinning). Skip
            # rather than 500 the whole list for one missing row.
            continue
        out.append(
            DemoFixtureOut(
                key=key,
                label=_LABELS.get(key, key),
                explanation=_EXPLANATIONS.get(key, ""),
                invoice_number=invoice_number,
                invoice_id=invoice_id,
                expected_action=fixture["expected_action"],
            )
        )
    return out
