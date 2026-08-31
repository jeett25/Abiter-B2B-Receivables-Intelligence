from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.engine import Engine

from app.attribution.config import ATTRIBUTION_EXPERIMENT_SEED, TREATMENT_FRACTION
from app.decision.policy import detect_already_paid, detect_dispute
from app.decision.service import DEFAULT_AS_OF
from app.ml.features import load_raw_tables
from app.models.enums import InvoiceStatus, TreatmentGroup


@dataclass(frozen=True)
class ExperimentCandidate:
    invoice_id: object
    customer_segment: str
    is_disputed: bool
    is_actually_paid: bool


def _as_of_naive(as_of) -> pd.Timestamp:
    ts = pd.Timestamp(as_of)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def build_experiment_population(
    engine: Engine | None = None, as_of=DEFAULT_AS_OF
) -> list[ExperimentCandidate]:
    tables = load_raw_tables(engine)
    invoices = tables["invoices"]
    customers = tables["customers"].set_index("id")
    payments = tables["payments"]

    live_invoices = invoices[invoices["status"] == InvoiceStatus.OPEN.value]
    as_of_naive = _as_of_naive(as_of)

    candidates = []
    for _, invoice_row in live_invoices.iterrows():
        customer_row = customers.loc[invoice_row["customer_id"]]

        invoice_payments = payments[payments["invoice_id"] == invoice_row["id"]]
        completed_total = float(
            invoice_payments[invoice_payments["payment_date"] <= as_of_naive]["amount"].sum()
        )
        is_actually_paid = detect_already_paid(float(invoice_row["amount"]), completed_total)
        is_disputed = detect_dispute(invoice_row["true_root_cause"])

        candidates.append(
            ExperimentCandidate(
                invoice_id=invoice_row["id"],
                customer_segment=customer_row["segment"],
                is_disputed=is_disputed,
                is_actually_paid=is_actually_paid,
            )
        )
    return candidates


def is_experiment_eligible(candidate: ExperimentCandidate) -> bool:
    return not candidate.is_actually_paid and not candidate.is_disputed


def assign_treatment_groups(
    candidates: list[ExperimentCandidate],
    seed: int = ATTRIBUTION_EXPERIMENT_SEED,
    treatment_fraction: float = TREATMENT_FRACTION,
) -> dict[object, TreatmentGroup]:
    eligible = [c for c in candidates if is_experiment_eligible(c)]

    by_segment: dict[str, list[ExperimentCandidate]] = {}
    for c in eligible:
        by_segment.setdefault(c.customer_segment, []).append(c)

    assignment: dict[object, TreatmentGroup] = {}
    for segment, group in by_segment.items():
        ordered = sorted(group, key=lambda c: str(c.invoice_id))
        rng = random.Random(f"{seed}:{segment}")
        shuffled = ordered[:]
        rng.shuffle(shuffled)

        split_at = round(len(shuffled) * treatment_fraction)
        for c in shuffled[:split_at]:
            assignment[c.invoice_id] = TreatmentGroup.ACTED
        for c in shuffled[split_at:]:
            assignment[c.invoice_id] = TreatmentGroup.CONTROL

    return assignment


def _print_checkpoint(candidates: list[ExperimentCandidate]) -> None:
    from collections import Counter

    eligible = [c for c in candidates if is_experiment_eligible(c)]
    excluded = [c for c in candidates if not is_experiment_eligible(c)]

    assignment_a = assign_treatment_groups(candidates)
    assignment_b = assign_treatment_groups(candidates)
    assert assignment_a == assignment_b, "assignment is not reproducible given the same seed"

    treated = [inv_id for inv_id, g in assignment_a.items() if g == TreatmentGroup.ACTED]
    controlled = [inv_id for inv_id, g in assignment_a.items() if g == TreatmentGroup.CONTROL]
    assert set(treated).isdisjoint(controlled)

    print(f"Eligible:  {len(eligible)}")
    print(f"Treatment: {len(treated)}")
    print(f"Control:   {len(controlled)}")
    print(f"Excluded:  {len(excluded)}")

    already_paid_excluded = sum(1 for c in excluded if c.is_actually_paid)
    disputed_excluded = sum(1 for c in excluded if c.is_disputed)
    print(f"  (excluded: {already_paid_excluded} already-paid, {disputed_excluded} disputed)")

    segment_counts: Counter = Counter(c.customer_segment for c in eligible)
    print("\nPer-segment balance:")
    for segment in sorted(segment_counts):
        seg_candidates = [c for c in eligible if c.customer_segment == segment]
        seg_treated = sum(1 for c in seg_candidates if assignment_a.get(c.invoice_id) == TreatmentGroup.ACTED)
        seg_controlled = sum(1 for c in seg_candidates if assignment_a.get(c.invoice_id) == TreatmentGroup.CONTROL)
        print(f"  {segment:<20} treatment={seg_treated:>4}  control={seg_controlled:>4}")


if __name__ == "__main__":
    _print_checkpoint(build_experiment_population())
