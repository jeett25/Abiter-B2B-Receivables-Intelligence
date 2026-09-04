"""Subtask 10 -- full agent simulation, the 6 named scenarios.

Runnable directly: python -m app.agent.simulate_scenarios

This is a narrated rehearsal script, not a pytest suite -- most of the
underlying mechanics are already proven by existing tests (Scenario B is
Subtask 8's reassessment-loop test, Scenario F is Subtask 6's forced-
failure test, Scenario D is already in test_agent_demo_parity.py); this
script's job is assembling them into one coherent, watchable story, with C
and E filled in for real.

Runs with persist=True -- this leaves real decision_logs/account_state rows
behind, same accepted-side-effect precedent as test_decision_persist.py/
test_audit.py, not a dry run.

Reuses named demo fixtures (synthetic/demo_fixtures.json) wherever a
scenario has a natural match, rather than an arbitrary live invoice, so the
same invoice_number shows up every time this is rehearsed/recorded:
  A (successful)      -> high_value_act
  B (broken promise)  -> promise_breaker_reassess (fits thematically too)
  D (already paid)    -> already_paid_suppress
  F (tool failure)    -> chronic_late_escalate (guaranteed VOICE post-Day-5's
                          ESCALATE amount-threshold fix -- was ESCALATE at
                          Day-3 time; see docs/decision-DECISIONS.md and
                          synthetic/seed_demo.py -- same fixture
                          test_resilience.py's forced-failure test uses,
                          now forcing execute_voice, not request_human_handoff)
  G (correct abstention, added 2026-09-04) -> reliable_payer_wait -- mirrors
                          A's mechanism (assess, then manually inject a
                          payment dated after the decision) but for a WAIT
                          case: proves "assessed high-probability organic
                          recovery, chose not to spend, was later paid
                          anyway" without relying on the attribution
                          experiment's own uncontrolled timing (which broke
                          this fixture's previous pin -- see
                          synthetic/demo_fixtures.py's comment for the
                          full history).
C (dispute) and E (low economic value) have no matching fixture -- C queries
for a real disputed live invoice directly; E scans the live pool via Day-3's
fast run_full_live_pass() (loads tables once, no LLM/embedding calls) for a
real invoice that genuinely resolves to STOP today, rather than assuming one.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select

from app.agent import nodes
from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.agent.scanners import scan_for_broken_promises
from app.agent.state_machine import TransitionContext, determine_next_state
from app.core.db import SessionLocal
from app.decision.service import DEFAULT_AS_OF, run_full_live_pass
from app.models import DecisionLog as DecisionLogModel
from app.models import Invoice, Payment, PaymentPromise
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus

FIXTURES = json.loads((Path(__file__).parent.parent.parent / "synthetic" / "demo_fixtures.json").read_text())
DAY1 = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
DAY10 = DAY1 + timedelta(days=10)

# Must match synthetic/seed_demo.py's SYNTHETIC_PAYMENT_METHODS exactly --
# both are the only places in the codebase that ever write these literal
# method strings, so deleting by them can never remove an organic
# generator-created payment (see seed_demo.py's own comment for the
# already_paid_suppress incident that established this boundary).
SYNTHETIC_PAYMENT_METHODS = ("attribution_simulation", "scenario_rehearsal")


def _clear_prior_rounds(invoice_id) -> None:
    """Deletes any decision_logs/payment_promises/synthetic-payment left
    over from a PRIOR rehearsal of this same fixture, so this run produces
    exactly one clean narrative.

    Why this exists: decision_logs sort by business timestamp
    (`Event.occurred_at`), not by when a script actually ran. This module's
    scenarios use fixed DAY1/DAY10 timestamps (2026-08-24 / 2026-09-03) --
    chronologically EARLIER than synthetic/seed_demo.py's DEFAULT_AS_OF
    (~2026-08-27). So if seed_demo.py's reset_and_reassess() ran first
    (real execution order) and left its own DEFAULT_AS_OF-timestamped row
    behind, that row would sort in the MIDDLE of (or after) this scenario's
    own DAY1..DAY10 timeline once this scenario runs -- a confusing "ghost
    round" a viewer can't place, and exactly what made the tool-failure and
    broken-promise demos read as contradictory. Clearing first, every time,
    makes this scenario's own narrative the only one on record regardless
    of what ran before it or how many times this has been rehearsed across
    past sessions."""
    session = SessionLocal()
    try:
        synthetic_ids = (
            session.execute(
                select(Payment.id).where(Payment.invoice_id == invoice_id, Payment.method.in_(SYNTHETIC_PAYMENT_METHODS))
            )
            .scalars()
            .all()
        )
        if synthetic_ids:
            session.execute(delete(Payment).where(Payment.id.in_(synthetic_ids)))
            invoice = session.get(Invoice, invoice_id)
            invoice.status = InvoiceStatus.OPEN
            invoice.paid_at = None
        session.execute(delete(DecisionLogModel).where(DecisionLogModel.invoice_id == invoice_id))
        session.execute(delete(PaymentPromise).where(PaymentPromise.invoice_id == invoice_id))
        session.commit()
    finally:
        session.close()


def _banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _step(label: str, **fields) -> None:
    print(f"\n-- {label}")
    for key, value in fields.items():
        print(f"   {key}: {value}")


def _invoice_id_by_number(invoice_number: str):
    session = SessionLocal()
    try:
        return session.execute(select(Invoice.id).where(Invoice.invoice_number == invoice_number)).scalar_one()
    finally:
        session.close()


def _invoice_row(invoice_id):
    session = SessionLocal()
    try:
        return session.get(Invoice, invoice_id)
    finally:
        session.close()


def scenario_a_successful() -> None:
    _banner("SCENARIO A -- successful recovery: OVERDUE -> assess -> contact -> payment -> CLOSED_PAID")
    invoice_id = _invoice_id_by_number(FIXTURES["high_value_act"]["invoice_number"])
    _clear_prior_rounds(invoice_id)

    overdue = run_invoice(
        invoice_id, event=Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DAY1), persist=True
    )
    _step(
        "assessment",
        recovery_probability=f"{overdue['recovery_probability']:.3f}",
        selected_action=overdue["selected_action"].value,
        next_state=overdue["next_state"].value,
    )

    invoice = _invoice_row(invoice_id)
    # Capped at DEFAULT_AS_OF - 1 day, same rule app/attribution/persist.py
    # uses -- DAY10 (2026-09-03) is after the dataset's frozen "now"
    # (REFERENCE_DATE, mirrored by DEFAULT_AS_OF), so writing it literally
    # to the ledger would permanently fail
    # synthetic/validators.py's temporal-consistency check on every future
    # run of this rehearsal script. The narrative's own DAY10 timestamp
    # (used for the PAYMENT_RECEIVED event below) is unaffected -- only the
    # persisted payment_date is capped.
    ledger_payment_date = min(DAY10.date(), DEFAULT_AS_OF.date() - timedelta(days=1))
    session = SessionLocal()
    try:
        # method is a distinct marker ("scenario_rehearsal"), not a random
        # "upi"/"bank_transfer" like the generator's own organic payments --
        # synthetic/seed_demo.py's reset_and_reassess() relies on this exact
        # string to clean up ONLY this rehearsal's own payment on a rerun,
        # never an organic one (confirmed live: a plain method="upi" here
        # was indistinguishable from the generator's own random choice of
        # "upi" for other fixtures, corrupting already_paid_suppress's real
        # organic payment on cleanup).
        session.add(
            Payment(
                invoice_id=invoice_id,
                amount=Decimal(str(invoice.amount)),
                payment_date=ledger_payment_date,
                method="scenario_rehearsal",
            )
        )
        session.commit()
    finally:
        session.close()

    payment_event = Event(
        event_type=EventType.PAYMENT_RECEIVED,
        invoice_id=invoice_id,
        occurred_at=DAY10,
        payload={"amount": float(invoice.amount), "payment_date": DAY10.date().isoformat(), "method": "upi"},
    )
    paid = run_invoice(invoice_id, event=payment_event, persist=True)
    _step("payment received", next_state=paid["next_state"].value, is_actually_paid=paid["is_actually_paid"])
    print(f"\nVERDICT: {'PASS' if paid['next_state'] == AccountCurrentState.CLOSED_PAID else 'UNEXPECTED'}")


def scenario_b_broken_promise() -> None:
    _banner("SCENARIO B -- broken promise: OVERDUE -> promise -> broken -> REASSESS -> next action")
    invoice_id = _invoice_id_by_number(FIXTURES["promise_breaker_reassess"]["invoice_number"])
    _clear_prior_rounds(invoice_id)

    promise_event = Event(
        event_type=EventType.CUSTOMER_RESPONDED,
        invoice_id=invoice_id,
        occurred_at=DAY1,
        payload={"channel": "whatsapp", "transcript": "I'll pay Rs 50,000 this Friday."},
    )
    promised = run_invoice(invoice_id, event=promise_event, persist=True)
    ptp = promised.get("ptp_probability")
    _step(
        "promise attempt",
        next_state=promised["next_state"].value,
        ptp_probability=f"{ptp:.3f}" if ptp is not None else "N/A (no promise extracted)",
    )

    if promised["next_state"] != AccountCurrentState.PROMISE:
        print("\nVERDICT: SKIPPED -- no promise extracted this run (LLM found no concrete commitment); rerun to retry.")
        return

    broken_events = scan_for_broken_promises(DAY10)
    matching = [e for e in broken_events if e.invoice_id == invoice_id]
    if not matching:
        print("\nVERDICT: UNEXPECTED -- promise not yet found broken by DAY10.")
        return

    reassessed = run_invoice(invoice_id, event=matching[0], persist=True)
    _step(
        "reassessed after broken promise",
        path=[s.value for s in reassessed["state_transition_path"]],
        next_state=reassessed["next_state"].value,
    )
    print(f"\nVERDICT: {'PASS' if AccountCurrentState.BROKEN in reassessed['state_transition_path'] else 'UNEXPECTED'}")


def scenario_c_dispute() -> None:
    _banner("SCENARIO C -- dispute: OVERDUE -> dispute detected -> collection actions blocked -> DISPUTE_REVIEW")
    session = SessionLocal()
    try:
        invoice_id = session.execute(
            select(Invoice.id).where(Invoice.status == InvoiceStatus.OPEN, Invoice.true_root_cause == "dispute").limit(1)
        ).scalar_one()
    finally:
        session.close()

    result = run_invoice(
        invoice_id, event=Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DAY1), persist=True
    )
    escalation_candidates = [ev.action_type for ev in result["economics_ranking"]]
    _step(
        "assessment on a disputed invoice",
        candidate_actions=[a.value for a in escalation_candidates],
        escalate_or_voice_offered=any(a in (ActionType.ESCALATE, ActionType.VOICE) for a in escalation_candidates),
        next_state=result["next_state"].value,
    )
    print(f"\nVERDICT: {'PASS' if result['next_state'] == AccountCurrentState.DISPUTE_REVIEW else 'UNEXPECTED'}")


def scenario_d_already_paid() -> None:
    _banner("SCENARIO D -- already paid (false alarm): ledger check catches it despite invoices.status='open'")
    invoice_id = _invoice_id_by_number(FIXTURES["already_paid_suppress"]["invoice_number"])
    _clear_prior_rounds(invoice_id)

    result = run_invoice(
        invoice_id, event=Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DAY1), persist=True
    )
    _step("assessment", is_actually_paid=result["is_actually_paid"], next_state=result["next_state"].value)
    print(f"\nVERDICT: {'PASS' if result['next_state'] == AccountCurrentState.CLOSED_PAID else 'UNEXPECTED'}")


def scenario_e_low_value() -> None:
    _banner("SCENARIO E -- low economic value: OVERDUE -> low pursuit value -> CLOSED_ABANDONED")
    print("\nScanning the live pool via the fast Day-3 batch pass for a real invoice that resolves to STOP...")
    decisions = run_full_live_pass(as_of=DAY1)
    candidate = next((d for d in decisions if d.final_action == ActionType.STOP and not d.is_actually_paid), None)

    if candidate is not None:
        invoice = _invoice_row(candidate.invoice_id)
        print(f"Found: {invoice.invoice_number} (amount Rs.{invoice.amount:,.0f}, base_probability={candidate.base_probability:.3f})")
        result = run_invoice(
            candidate.invoice_id,
            event=Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=candidate.invoice_id, occurred_at=DAY1),
            persist=True,
        )
        _step("assessment", selected_action=result["selected_action"].value, next_state=result["next_state"].value)
        print(f"\nVERDICT: {'PASS' if result['next_state'] == AccountCurrentState.CLOSED_ABANDONED else 'UNEXPECTED'}")
        return

    print(
        "\nNo live invoice resolves to STOP today -- verified structural reason, not a scan bug: "
        "WAIT never wins under the current economics config, even at the amount/probability floor "
        "(WHATSAPP's EV beats WAIT's by a wide margin down to Rs.5,000/p=0.01), and no live invoice has "
        "prior_contact_count >= MAX_CONTACT_ATTEMPTS since nothing writes to recovery_actions for the live "
        "pool. See docs/agent-DECISIONS.md for the full verification. Demonstrating the mechanism directly "
        "instead -- ILLUSTRATIVE: this is determine_next_state() called with a constructed context, not a "
        "real invoice's own decision, but it's the exact same function every real invocation relies on."
    )
    illustrative_context = TransitionContext(
        current_state=AccountCurrentState.WAIT,
        event=Event(event_type=EventType.REVIEW_TIMEOUT, invoice_id=uuid4(), occurred_at=DAY1),
        is_disputed=False,
        is_actually_paid=False,
        selected_action=ActionType.STOP,
    )
    transition = determine_next_state(illustrative_context)
    _step(
        "illustrative low-value abstention (constructed context, not a real invoice)",
        next_state=transition.next_state.value,
        path=[s.value for s in transition.path],
    )
    print(f"\nVERDICT: {'PASS (illustrative)' if transition.next_state == AccountCurrentState.CLOSED_ABANDONED else 'UNEXPECTED'}")


def scenario_g_correct_abstention() -> None:
    _banner("SCENARIO G -- correct abstention: OVERDUE -> assess -> WAIT (no intervention) -> payment -> CLOSED_PAID")
    invoice_id = _invoice_id_by_number(FIXTURES["reliable_payer_wait"]["invoice_number"])
    _clear_prior_rounds(invoice_id)

    overdue = run_invoice(
        invoice_id, event=Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DAY1), persist=True
    )
    _step(
        "assessment",
        recovery_probability=f"{overdue['recovery_probability']:.3f}",
        selected_action=overdue["selected_action"].value,
        next_state=overdue["next_state"].value,
    )
    if overdue["selected_action"] != ActionType.WAIT:
        print(
            "\nVERDICT: SKIPPED -- this invoice no longer resolves to WAIT on its own economics merit; "
            "re-pin FIXTURES['reliable_payer_wait'] to a different still-open, high-recovery-probability invoice."
        )
        return

    invoice = _invoice_row(invoice_id)
    # Same DEFAULT_AS_OF-1-day cap as Scenario A, same reason: DAY10
    # postdates the dataset's frozen "now" for a fresh run of this script.
    ledger_payment_date = min(DAY10.date(), DEFAULT_AS_OF.date() - timedelta(days=1))
    session = SessionLocal()
    try:
        session.add(
            Payment(
                invoice_id=invoice_id,
                amount=Decimal(str(invoice.amount)),
                payment_date=ledger_payment_date,
                # Same rehearsal-marker convention as Scenario A -- lets
                # synthetic/seed_demo.py's reset_and_reassess() clean up only
                # this manufactured payment on a rerun, never an organic one.
                method="scenario_rehearsal",
            )
        )
        session.commit()
    finally:
        session.close()

    payment_event = Event(
        event_type=EventType.PAYMENT_RECEIVED,
        invoice_id=invoice_id,
        occurred_at=DAY10,
        payload={"amount": float(invoice.amount), "payment_date": DAY10.date().isoformat(), "method": "bank_transfer"},
    )
    paid = run_invoice(invoice_id, event=payment_event, persist=True)
    _step(
        "payment received (no intervention preceded it)",
        next_state=paid["next_state"].value,
        is_actually_paid=paid["is_actually_paid"],
    )
    print(f"\nVERDICT: {'PASS' if paid['next_state'] == AccountCurrentState.CLOSED_PAID else 'UNEXPECTED'}")


def scenario_f_tool_failure() -> None:
    _banner("SCENARIO F -- tool/LLM failure: action -> failure -> retry -> fallback -> safe state -> audit")
    invoice_id = _invoice_id_by_number(FIXTURES["chronic_late_escalate"]["invoice_number"])
    _clear_prior_rounds(invoice_id)

    def _forced_failure(*, invoice_number, amount, now, failure_mode=False):
        return {
            "success": False,
            "action": "voice",
            "external_id": None,
            "message": "[forced failure for demo]",
            "timestamp": now.isoformat(),
        }

    original = nodes.execute_voice
    nodes.execute_voice = _forced_failure
    try:
        result = run_invoice(
            invoice_id,
            event=Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DAY1),
            persist=True,
        )
    finally:
        nodes.execute_voice = original

    _step(
        "forced voice-call failure",
        proposed_action=result["proposed_action"].value,
        selected_action_after_fallback=result["selected_action"].value,
        next_state=result["next_state"].value,
        error=result["error"],
    )
    survived = result["next_state"] == AccountCurrentState.WAIT and result["error"] is not None
    print(f"\nVERDICT: {'PASS -- system stayed alive, fell back safely, failure recorded' if survived else 'UNEXPECTED'}")


def main() -> None:
    for scenario in (
        scenario_a_successful,
        scenario_b_broken_promise,
        scenario_c_dispute,
        scenario_d_already_paid,
        scenario_e_low_value,
        scenario_f_tool_failure,
        scenario_g_correct_abstention,
    ):
        try:
            scenario()
        except Exception as exc:  # noqa: BLE001 -- one scenario's failure shouldn't stop the rehearsal
            print(f"\nVERDICT: ERROR -- {exc!r}")


if __name__ == "__main__":
    main()
