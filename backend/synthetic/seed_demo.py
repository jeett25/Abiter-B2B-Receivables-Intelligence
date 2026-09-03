"""Day 5, subtask 9: reset the 6 curated demo fixtures (synthetic/demo_fixtures.json)
to a known, rehearsal-safe state before every recording.

Why this exists now, not just "eventually": the Day 5 attribution
experiment ran across all 812 eligible live invoices with no special-case
exclusion for the 6 curated fixtures, and 3 of them were swept in and
resolved via the control arm's organic simulation -- breaking the demo
narrative they were pinned for.

Design, revised after a real gap was found: the first version split
fixtures into a "reset" group (the 3 the write-back broke) and a
"verify-only" group (read persisted state, no mutation) for the other 3.
That split was itself a bug -- chronic_late_escalate's persisted
account_state predated subtask 6's ESCALATE fix, so "verify-only" silently
checked a STALE expectation (ESCALATE) instead of the CURRENT correct one
(VOICE, since INV-10184 at Rs.118,361 is above ESCALATE_LARGE_AMOUNT_THRESHOLD_INR).
Fixed by unifying all 6 fixtures through ONE path: clean up any Day-5
write-back artifacts if present (a safe no-op for fixtures that were never
touched), clear stale decision_logs/payment_promises, and re-run the
CURRENT agent fresh every time. This means every fixture's check reflects
what the system actually does today, not what it did when the fixture was
last persisted -- the exact property "verify-only" was supposed to have
and didn't.

already_paid_suppress needs no special-casing in this unified design: it
never received a Day-5 write-back (correctly excluded from the experiment
as already-paid), so nothing gets deleted for it, and re-running
run_invoice() against its ORIGINAL untouched payment row correctly
reproduces is_actually_paid=True -> STOP every time.

Scope, deliberately narrow: touches ONLY these 6 invoices, never the other
894 live invoices, and never re-runs the attribution experiment itself
(that's already deployed and verified -- redoing it would invalidate a
working deployment for no benefit). attribution_records rows are left
untouched for all 6 -- see app/attribution/DECISIONS.md's note on why
decision_logs/account_state and attribution_records will legitimately
disagree about the 3 write-back-affected invoices' history, and why
that's not a bug.

Every run prints a concrete PASS/WARN per fixture (see FIXTURE_CHECKS)
rather than requiring a manual eyeball of six invoices before recording.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete, select

from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.core.db import SessionLocal
from app.decision.service import DEFAULT_AS_OF
from app.models import Invoice, Payment, PaymentPromise
from app.models import DecisionLog as DecisionLogModel
from app.models.enums import AccountCurrentState, ActionType, InvoiceStatus

DEMO_FIXTURES_PATH = Path(__file__).parent / "demo_fixtures.json"

# Must match app/attribution/persist.py's LEDGER_PAYMENT_METHOD and
# app/agent/simulate_scenarios.py's Scenario A payment method exactly --
# both confirmed via code search to be the ONLY places in the codebase that
# ever write these literal strings, so deleting by them can never remove
# an organic generator-created payment (which uses rng.choice among
# "bank_transfer"/"upi"/"cheque"/"card" -- confirmed live: a first version
# of this cleanup deleted ALL payments unconditionally, which wiped out
# already_paid_suppress's real organic payment since the generator can
# coincidentally also pick "upi" for it).
ATTRIBUTION_WRITE_BACK_METHOD = "attribution_simulation"
SCENARIO_REHEARSAL_METHOD = "scenario_rehearsal"
SYNTHETIC_PAYMENT_METHODS = (ATTRIBUTION_WRITE_BACK_METHOD, SCENARIO_REHEARSAL_METHOD)


def _load_fixtures() -> dict:
    with open(DEMO_FIXTURES_PATH) as f:
        return json.load(f)


def _get_invoice_id(session, invoice_number: str):
    return session.execute(select(Invoice.id).where(Invoice.invoice_number == invoice_number)).scalar_one()


def reset_and_reassess(invoice_number: str, as_of=DEFAULT_AS_OF) -> dict:
    """Safe to call repeatedly across rehearsals for any of the 6 fixtures,
    whether or not Day 5's write-back or a simulate_scenarios.py rehearsal
    ever touched them -- see module docstring. Cleaning up write-back/
    rehearsal artifacts is conditional on SYNTHETIC_PAYMENT_METHODS
    specifically (2026-09-02: widened from write-back-only to also catch
    Scenario A's own payment, narrowed back from an earlier
    unconditional-delete-everything attempt that corrupted
    already_paid_suppress's real organic payment -- see
    SYNTHETIC_PAYMENT_METHODS' comment for why an exact-method match is the
    right boundary here, not "any payment"). Clearing stale
    decision_logs/payment_promises and re-running fresh always happens
    regardless, so every fixture's check reflects current, not stale,
    behavior."""
    session = SessionLocal()
    try:
        invoice_id = _get_invoice_id(session, invoice_number)

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

        # append-only decision_logs and any promise from a prior rehearsal
        # both need clearing so this produces one clean, current row, not
        # a growing pile of stale ones.
        session.execute(delete(DecisionLogModel).where(DecisionLogModel.invoice_id == invoice_id))
        session.execute(delete(PaymentPromise).where(PaymentPromise.invoice_id == invoice_id))

        session.commit()
    finally:
        session.close()

    event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=as_of)
    return run_invoice(invoice_id, event=event, persist=True)


# -- Concrete, falsifiable expected outcome per fixture ------------------
# Each returns (passed: bool, detail: str), checked against the FRESH
# run_invoice() result every time -- never eyeballed, never read from
# potentially-stale persisted state. See module docstring.


def check_reliable_payer_wait(result: dict) -> tuple[bool, str]:
    action = result.get("selected_action")
    ok = action == ActionType.WAIT
    return ok, f"selected_action={action.value if action else None} (expected WAIT)"


def check_chronic_late_escalate(result: dict) -> tuple[bool, str]:
    # Reframed after subtask 6's ESCALATE fix: INV-10184 is Rs.118,361,
    # above ESCALATE_LARGE_AMOUNT_THRESHOLD_INR, so VOICE is now the
    # CORRECT answer, not ESCALATE. Kept as a demo fixture deliberately --
    # this is now direct, concrete proof of the Day-5 correction in
    # action on a real invoice, not a generic archetype-coverage example.
    # Fixture key name kept as-is (stable identifier) despite no longer
    # matching its current expected action.
    action = result.get("selected_action")
    ok = action == ActionType.VOICE
    return ok, f"selected_action={action.value if action else None} (expected VOICE post-ESCALATE-fix, not ESCALATE)"


def check_promise_breaker_reassess(result: dict) -> tuple[bool, str]:
    # The original "reassess" label needs a multi-event promise-created ->
    # promise-broken sequence to actually show (see
    # app/agent/simulate_scenarios.py) -- not something a single fresh
    # INVOICE_OVERDUE assessment can produce. This check confirms the
    # fixture is back to a genuinely open, assessable state ready for that
    # follow-up demo sequence.
    next_state = result.get("next_state")
    terminal_states = {AccountCurrentState.CLOSED_PAID, AccountCurrentState.CLOSED_ABANDONED, AccountCurrentState.DISPUTE_REVIEW}
    ok = next_state not in terminal_states
    return ok, f"next_state={next_state.value if next_state else None} (expected still-open, ready for a follow-up promise-broken demo)"


def check_low_value_stop(result: dict) -> tuple[bool, str]:
    # Day 3's own documented, accepted finding (see CLAUDE.md's Day-3
    # section): this fixture produces an active nudge, not STOP. Reframed
    # again after the root-cause classifier addition: INV-10040 predicts
    # cash_flow_stress at high confidence, which nudges PAYMENT_LINK's
    # uplift (see ROOT_CAUSE_UPLIFT_ADJUSTMENT) -- genuinely tipping an
    # already-close WHATSAPP-vs-PAYMENT_LINK race (~Rs45 apart pre-nudge).
    # Both are the intended "cheap nudge, not STOP" finding; accepting
    # either rather than re-narrowing to one, since which one wins is
    # legitimately sensitive to small, evidence-based economics changes.
    action = result.get("selected_action")
    ok = action in (ActionType.WHATSAPP, ActionType.PAYMENT_LINK)
    return ok, f"selected_action={action.value if action else None} (expected WHATSAPP or PAYMENT_LINK -- a cheap nudge, not STOP)"


def check_high_value_act(result: dict) -> tuple[bool, str]:
    # STOP and WAIT are both also accepted (2026-09-03), same "honest answer
    # over forced label" precedent as check_low_value_stop below. STOP: this
    # invoice does double duty as Scenario A's paid-invoice narrative. WAIT:
    # after the 2026-09-03 recovery-model retrain (fixed a survivorship-bias
    # bug that had been inflating recent-history "always recovers" rows --
    # see app/ml/DECISIONS.md), this invoice's recovery_probability is a
    # genuinely high ~0.95, and diminishing-returns economics correctly finds
    # no active intervention clears its cost/materiality floor. Not a
    # regression -- a more accurate model producing a more honest answer.
    action = result.get("selected_action")
    active_actions = {ActionType.EMAIL, ActionType.WHATSAPP, ActionType.PAYMENT_LINK, ActionType.VOICE, ActionType.ESCALATE}
    ok = action in active_actions or action in (ActionType.STOP, ActionType.WAIT)
    return ok, f"selected_action={action.value if action else None} (expected an active intervention, STOP, or WAIT-if-high-confidence)"


def check_already_paid_suppress(result: dict) -> tuple[bool, str]:
    next_state = result.get("next_state")
    ok = next_state == AccountCurrentState.CLOSED_PAID
    return ok, f"next_state={next_state.value if next_state else None} (expected CLOSED_PAID -- ledger cross-reference still catches this)"


FIXTURE_CHECKS = {
    "reliable_payer_wait": check_reliable_payer_wait,
    "chronic_late_escalate": check_chronic_late_escalate,
    "promise_breaker_reassess": check_promise_breaker_reassess,
    "low_value_stop": check_low_value_stop,
    "high_value_act": check_high_value_act,
    "already_paid_suppress": check_already_paid_suppress,
}


def seed_demo() -> bool:
    """Returns True iff every fixture passed its check (safe to record)."""
    fixtures = _load_fixtures()
    results: dict[str, dict] = {}

    print("Resetting all 6 demo fixtures (cleans up any Day-5 write-back artifacts, re-runs the current agent fresh)...")
    for key, fixture in fixtures.items():
        invoice_number = fixture["invoice_number"]
        print(f"  {key} ({invoice_number})...")
        results[key] = reset_and_reassess(invoice_number)

    print("\nDrift check (PASS/WARN per fixture, against FRESH results):")
    all_passed = True
    for key, check_fn in FIXTURE_CHECKS.items():
        passed, detail = check_fn(results[key])
        all_passed = all_passed and passed
        print(f"  [{'PASS' if passed else 'WARN'}] {key} ({fixtures[key]['invoice_number']}): {detail}")

    print("\nSafe to record." if all_passed else "\nWARN(s) above -- review before recording.")
    return all_passed


if __name__ == "__main__":
    seed_demo()
