"""Subtask 11 -- final Day-4 integration pass: the full 900-invoice live
pool through the real agent graph.

Runnable directly:
  python -m app.agent.final_integration_pass            # dry run, persist=False
  python -m app.agent.final_integration_pass --persist   # the real, permanent write

Defaults to persist=False. Per explicit decision: this is a 900-row,
effectively irreversible write (no seed_demo.py yet to undo it -- that's
Day 5) -- it gets run once dry, the numbers get reviewed, and only then
re-run with --persist. Skipping the dry run "to save a run" would be
inconsistent with every other check in this build having been done
directly rather than assumed.

Deliberately does NOT join against customers.archetype/
true_recovery_probability/true_promise_keep_probability anywhere in this
script, including for diagnostic printing. Day 2/3's sanity-check
functions did that join, but scoped explicitly to verification-only
diagnostics, never mixed into production code. This script's whole job is
proving production-cleanliness at scale -- joining ground truth "just to
eyeball it" here would undermine the very thing it's trying to demonstrate.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from app.agent import nodes
from app.agent.events import Event, EventType
from app.agent.graph import run_invoice
from app.decision.policy import BUSINESS_HOURS_ACTIONS, is_business_hours
from app.decision.service import DEFAULT_AS_OF
from app.ml.config import CALIBRATED_PROBABILITY_CEILING, CALIBRATED_PROBABILITY_FLOOR
from app.ml.features import build_live_feature_table, load_raw_tables
from app.models.enums import ActionType, PolicyResult

FORBIDDEN_IDENTIFIERS = ["archetype", "true_recovery_probability", "true_promise_keep_probability"]
AGENT_DIR = Path(__file__).parent


def _check_no_hidden_ground_truth() -> list[str]:
    """Static check across every .py file in app/agent/ -- matches Day 3's
    own 'no-LLM confirmed via grep' precedent. true_root_cause is NOT
    forbidden (detect_dispute reads it deliberately -- a real-world-
    observable business fact, not a simulation-only parameter; see
    app/decision/policy.py's detect_dispute docstring for the full
    reasoning) -- only the three identifiers with no real-world analogue.

    Excludes this file itself: FORBIDDEN_IDENTIFIERS necessarily contains
    these words as string literals to define the denylist, which is a
    trivial self-match, not a real violation -- caught on the first real
    run of this check (see docs/agent-DECISIONS.md)."""
    violations = []
    for path in AGENT_DIR.glob("*.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text()
        for identifier in FORBIDDEN_IDENTIFIERS:
            if identifier in text:
                violations.append(f"{path.name}: contains '{identifier}'")
    return violations


def run_pass(persist: bool) -> None:
    print(f"Loading raw tables + live feature table once (persist={persist})...")
    engine = None
    tables = load_raw_tables(engine)
    live_feature_table = build_live_feature_table(engine)
    invoice_ids = list(live_feature_table["invoice_id"])
    print(f"{len(invoice_ids)} live invoices loaded.\n")

    config = {"configurable": {"engine": engine, "tables": tables, "live_feature_table": live_feature_table, "persist": persist}}

    extract_promise_calls = {"n": 0}
    original_extract_promise_node = nodes.extract_promise_node

    def _counting_extract_promise_node(state):
        extract_promise_calls["n"] += 1
        return original_extract_promise_node(state)

    nodes.extract_promise_node = _counting_extract_promise_node

    results = []
    errors = []
    try:
        for i, invoice_id in enumerate(invoice_ids, start=1):
            event = Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=invoice_id, occurred_at=DEFAULT_AS_OF)
            try:
                results.append(run_invoice(invoice_id, event=event, config=dict(config)))
            except Exception as exc:  # noqa: BLE001 -- record and continue; report at the end
                errors.append((invoice_id, repr(exc)))
            if i % 100 == 0:
                print(f"  ...{i}/{len(invoice_ids)} processed")
    finally:
        nodes.extract_promise_node = original_extract_promise_node

    print(f"\n{len(results)} decisions produced, {len(errors)} errors.")
    if errors:
        print("ERRORS:")
        for invoice_id, err in errors[:20]:
            print(f"  {invoice_id}: {err}")

    # -- distributions --
    action_counts = Counter(r["selected_action"].value for r in results)
    state_counts = Counter(r["next_state"].value for r in results)

    print("\nFinal action distribution:")
    for action, count in sorted(action_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {action:<14} {count:>4}  ({count / len(results):.1%})")

    print("\nResulting account_state distribution:")
    for state, count in sorted(state_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {state:<18} {count:>4}  ({count / len(results):.1%})")

    # -- safety checks --
    print("\n-- Safety checks --")

    seen_invoice_ids = [r["invoice_id"] for r in results]
    no_duplicates = len(seen_invoice_ids) == len(set(seen_invoice_ids))
    print(f"No duplicate processing: {'PASS' if no_duplicates else 'FAIL'} ({len(set(seen_invoice_ids))} unique / {len(seen_invoice_ids)} total)")

    policy_bypass_violations = [
        r["invoice_id"]
        for r in results
        if r.get("tool_result") is not None
        and (r.get("policy_verdict") is None or r["policy_verdict"].result == PolicyResult.BLOCKED)
    ]
    print(f"No policy bypass on real dispatches: {'PASS' if not policy_bypass_violations else f'FAIL ({len(policy_bypass_violations)})'}")

    business_hours_violations = [
        r["invoice_id"]
        for r in results
        if r.get("tool_result") is not None
        and r["selected_action"] in BUSINESS_HOURS_ACTIONS
        and not is_business_hours(DEFAULT_AS_OF)
    ]
    print(f"No VOICE/ESCALATE dispatched outside business hours: {'PASS' if not business_hours_violations else f'FAIL ({len(business_hours_violations)})'}")

    n_extract_calls = extract_promise_calls["n"]
    llm_check = "PASS" if n_extract_calls == 0 else f"FAIL ({n_extract_calls} calls)"
    print(f"No LLM/EXTRACT_PROMISE invocations (all events are INVOICE_OVERDUE): {llm_check}")

    missing_recovery_probability = [r["invoice_id"] for r in results if "recovery_probability" not in r]
    print(f"Every result has a real recovery_probability: {'PASS' if not missing_recovery_probability else f'FAIL ({len(missing_recovery_probability)})'}")

    placeholder_violations = [
        r["invoice_id"]
        for r in results
        if not (CALIBRATED_PROBABILITY_FLOOR <= r.get("recovery_probability", -1) <= CALIBRATED_PROBABILITY_CEILING)
    ]
    print(f"No placeholder recovery_probability (outside calibration bounds): {'PASS' if not placeholder_violations else f'FAIL ({len(placeholder_violations)})'}")

    ground_truth_violations = _check_no_hidden_ground_truth()
    print(f"No hidden-ground-truth identifiers in app/agent/*.py: {'PASS' if not ground_truth_violations else 'FAIL'}")
    for v in ground_truth_violations:
        print(f"  {v}")

    closed_abandoned_count = state_counts.get("closed_abandoned", 0)
    print(
        f"\nCLOSED_ABANDONED count: {closed_abandoned_count} "
        f"({'expected zero per the verified low-value/max-contacts unreachability finding, see DECISIONS.md' if closed_abandoned_count == 0 else 'NONZERO -- investigate before treating this pass as clean, see chat'})"
    )


if __name__ == "__main__":
    run_pass(persist="--persist" in sys.argv)
