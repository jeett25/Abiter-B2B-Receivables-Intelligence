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
# display. 4 of these map directly onto app/agent/simulate_scenarios.py's
# named scenarios (A/B/D/F); the other 2 (reliable_payer_wait, low_value_stop)
# are real Day-1 curated cases without their own lettered scenario, included
# anyway since they're genuine, useful abstention examples.
_LABELS = {
    "high_value_act": "Successful recovery",
    "promise_breaker_reassess": "Broken promise",
    "already_paid_suppress": "Already paid (false alarm)",
    "chronic_late_escalate": "Tool/LLM failure (forced, rehearsed)",
    "reliable_payer_wait": "Reliable payer (correct abstention)",
    "low_value_stop": "Low value (correct abstention)",
}


class DemoFixtureOut(BaseModel):
    key: str
    label: str
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
                invoice_number=invoice_number,
                invoice_id=invoice_id,
                expected_action=fixture["expected_action"],
            )
        )
    return out
