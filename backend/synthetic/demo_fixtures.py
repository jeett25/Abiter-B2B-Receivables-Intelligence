"""Selects and pins the 6 curated demo invoices from the live pool.

Run after synthetic.generator has populated the database. Selection is
deterministic given the same SEED=42 dataset -- it picks the invoice that best
matches each scenario's criteria and records its invoice_number so reruns and
recorded demos always reference the same six invoices.

Run with: python -m synthetic.demo_fixtures
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AccountState, Customer, Invoice
from app.models.enums import AccountCurrentState

FIXTURES_PATH = Path(__file__).parent / "demo_fixtures.json"

# archetypes considered for each scenario, and how to break ties among matches
SCENARIOS: dict[str, dict] = {
    "reliable_payer_wait": {
        "archetypes": ["reliable_payer"],
        "order": "amount_asc",
        # NOTE (2026-09-04): demo_fixtures.json's actual pinned invoice for
        # this key is manually overridden to INV-10545, NOT re-derived from
        # this scenario's own selection criteria. History: this key was
        # previously pinned to INV-10765 specifically because it had already
        # organically recovered via the Day-5 attribution control arm --
        # "concrete proof a WAIT decision was correct." That pin broke: by
        # the time it was actually recorded, the closing decision_logs entry
        # (dated at DEFAULT_AS_OF for ordering reasons) sorted AFTER the
        # invoice's real payment date, making the demo page read as
        # "recommended WAIT, then chose STOP, after already being paid
        # weeks earlier" -- a confusing, backwards-looking story. Root
        # cause: any invoice resolved through the attribution experiment's
        # organic simulation has a payment date anchored to its own
        # due_date, which is structurally almost always BEFORE the fixed
        # decision-engine clock (DEFAULT_AS_OF) -- so "assessed, then later
        # paid" can never read cleanly from an already-resolved invoice.
        # INV-10545 fixes this the same way high_value_act/Scenario A does:
        # a genuinely still-open invoice (99% recovery probability, real
        # WAIT decision, in the experiment's ACTED/treatment arm so nothing
        # external suppressed action either) plus a deliberate, deterministic
        # follow-up rehearsal (app/agent/simulate_scenarios.py's
        # scenario_g_correct_abstention) that injects a payment dated AFTER
        # the WAIT decision on purpose. Re-running select_demo_fixtures()
        # would silently discard this pin and select an ordinary open
        # invoice instead; don't run it for this key without updating this
        # comment together with simulate_scenarios.py's scenario_g and
        # seed_demo.py's check_reliable_payer_wait.
        "expected_action": "wait",
    },
    "chronic_late_escalate": {
        "archetypes": ["chronic_late"],
        "order": "amount_desc",
        # Was "escalate" -- Day 5's ESCALATE_LARGE_AMOUNT_THRESHOLD_INR
        # correction legitimately moved this invoice's real answer to VOICE
        # (see docs/decision-DECISIONS.md). Fixture key kept as-is (stable
        # identifier, direct proof of the Day-5 finding in action), but this
        # label is shown to viewers verbatim in the demo-case menu -- it
        # must describe what clicking through actually shows, not the
        # original pre-correction guess.
        "expected_action": "voice",
    },
    "promise_breaker_reassess": {
        "archetypes": ["promise_breaker"],
        "order": "amount_desc",
        # Was "reassess" -- REASSESS is a transient path label, never a
        # literally persisted decision (see docs/agent-DECISIONS.md); a
        # single fresh assessment always lands on a real action instead.
        # Labeled with this fixture's actual current decision so the menu
        # doesn't promise something a first click-through won't show.
        "expected_action": "voice",
    },
    "low_value_stop": {
        "archetypes": ["cash_constrained", "chronic_late", "promise_breaker"],
        "order": "amount_asc",
        "expected_action": "stop",
    },
    "high_value_act": {
        "archetypes": ["chronic_late"],
        "order": "amount_desc",
        # NOTE (2026-09-04): demo_fixtures.json's actual pinned invoice for
        # this key is manually overridden to INV-10023, NOT re-derived from
        # this scenario's own selection criteria. History: the original pin
        # (INV-10706) organically drifted after a real ML retrain fixed a
        # survivorship-bias bug (see docs/ml-DECISIONS.md) -- its recovery
        # probability rose to ~0.95, at which point diminishing-returns
        # economics correctly started picking WAIT instead of an active
        # channel, quietly turning "successful recovery, worth real effort"
        # into a duplicate of reliable_payer_wait's own no-intervention
        # story. INV-10023 fixes this: real ₹500,000 invoice, ~10.3%
        # recovery probability today, robustly justifying VOICE on its own
        # economics merit (not a razor-thin margin like low_value_stop's).
        # Re-running select_demo_fixtures() would silently discard this pin
        # and select an ordinary OVERDUE-state invoice instead (this one has
        # already transitioned to `remind`, so the query wouldn't even find
        # it); don't run it for this key without updating this comment
        # together with app/agent/simulate_scenarios.py's scenario_a.
        "expected_action": "act",
    },
    "already_paid_suppress": {
        "archetypes": ["already_paid_false_alarm"],
        "order": "amount_desc",
        "expected_action": "stop_suppress",
    },
}


def _select_invoice(session, archetypes: list[str], order: str) -> Invoice | None:
    query = (
        select(Invoice)
        .join(Customer, Invoice.customer_id == Customer.id)
        .join(AccountState, AccountState.invoice_id == Invoice.id)
        .where(AccountState.current_state == AccountCurrentState.OVERDUE)
        .where(Customer.archetype.in_(archetypes))
    )
    query = query.order_by(Invoice.amount.desc() if order == "amount_desc" else Invoice.amount.asc())
    return session.execute(query.limit(1)).scalar_one_or_none()


def select_demo_fixtures() -> dict[str, dict]:
    session = SessionLocal()
    try:
        results: dict[str, dict] = {}
        used_invoice_ids: set = set()

        for key, scenario in SCENARIOS.items():
            invoice = _select_invoice(session, scenario["archetypes"], scenario["order"])
            # Avoid picking the exact same invoice for two different scenarios.
            if invoice is not None and invoice.id in used_invoice_ids:
                query = (
                    select(Invoice)
                    .join(Customer, Invoice.customer_id == Customer.id)
                    .join(AccountState, AccountState.invoice_id == Invoice.id)
                    .where(AccountState.current_state == AccountCurrentState.OVERDUE)
                    .where(Customer.archetype.in_(scenario["archetypes"]))
                    .where(Invoice.id.notin_(used_invoice_ids))
                    .order_by(Invoice.amount.desc() if scenario["order"] == "amount_desc" else Invoice.amount.asc())
                    .limit(1)
                )
                invoice = session.execute(query).scalar_one_or_none()

            if invoice is not None:
                used_invoice_ids.add(invoice.id)
                results[key] = {
                    "invoice_number": invoice.invoice_number,
                    "expected_action": scenario["expected_action"],
                }

        FIXTURES_PATH.write_text(json.dumps(results, indent=2))
        return results
    finally:
        session.close()


if __name__ == "__main__":
    fixtures = select_demo_fixtures()
    for key, data in fixtures.items():
        print(f"{key}: {data['invoice_number']} (expected: {data['expected_action']})")
