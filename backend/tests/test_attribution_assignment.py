"""app/attribution/assignment.py tests: pure-function eligibility/assignment
unit tests (no DB), plus one integration checkpoint against the real live
pool mirroring subtask 1's own printed checkpoint."""
import uuid

from app.attribution.assignment import (
    ExperimentCandidate,
    assign_treatment_groups,
    build_experiment_population,
    is_experiment_eligible,
)
from app.models.enums import TreatmentGroup


def _candidate(segment="smb", disputed=False, paid=False, invoice_id=None):
    return ExperimentCandidate(
        invoice_id=invoice_id or uuid.uuid4(),
        customer_segment=segment,
        is_disputed=disputed,
        is_actually_paid=paid,
    )


def test_already_paid_invoice_is_not_eligible():
    assert is_experiment_eligible(_candidate(paid=True)) is False


def test_disputed_invoice_is_not_eligible():
    assert is_experiment_eligible(_candidate(disputed=True)) is False


def test_ordinary_invoice_is_eligible():
    assert is_experiment_eligible(_candidate()) is True


def test_ineligible_candidates_never_receive_an_assignment():
    candidates = [_candidate(paid=True), _candidate(disputed=True), _candidate()]
    assignment = assign_treatment_groups(candidates)
    assert len(assignment) == 1
    assert candidates[2].invoice_id in assignment


def test_assignment_is_reproducible_given_the_same_seed():
    candidates = [_candidate() for _ in range(200)]
    a = assign_treatment_groups(candidates)
    b = assign_treatment_groups(candidates)
    assert a == b


def test_different_seed_can_change_assignment():
    candidates = [_candidate() for _ in range(200)]
    a = assign_treatment_groups(candidates, seed=1)
    b = assign_treatment_groups(candidates, seed=2)
    assert a != b


def test_no_invoice_appears_in_both_groups():
    candidates = [_candidate() for _ in range(200)]
    assignment = assign_treatment_groups(candidates)
    treated = {inv_id for inv_id, g in assignment.items() if g == TreatmentGroup.ACTED}
    controlled = {inv_id for inv_id, g in assignment.items() if g == TreatmentGroup.CONTROL}
    assert treated.isdisjoint(controlled)
    assert treated | controlled == set(assignment.keys())


def test_split_is_exactly_balanced_within_a_stratum_of_even_size():
    candidates = [_candidate() for _ in range(200)]
    assignment = assign_treatment_groups(candidates)
    n_treated = sum(1 for g in assignment.values() if g == TreatmentGroup.ACTED)
    n_controlled = sum(1 for g in assignment.values() if g == TreatmentGroup.CONTROL)
    assert n_treated == n_controlled == 100


def test_strata_are_balanced_independently():
    candidates = [_candidate(segment="smb") for _ in range(50)] + [
        _candidate(segment="enterprise") for _ in range(30)
    ]
    assignment = assign_treatment_groups(candidates)

    smb = [c for c in candidates if c.customer_segment == "smb"]
    enterprise = [c for c in candidates if c.customer_segment == "enterprise"]

    smb_treated = sum(1 for c in smb if assignment[c.invoice_id] == TreatmentGroup.ACTED)
    enterprise_treated = sum(1 for c in enterprise if assignment[c.invoice_id] == TreatmentGroup.ACTED)

    assert smb_treated == 25
    assert enterprise_treated == 15


def test_build_experiment_population_against_real_live_pool(db_session):
    candidates = build_experiment_population()
    assert len(candidates) > 0
    assert all(isinstance(c, ExperimentCandidate) for c in candidates)

    eligible = [c for c in candidates if is_experiment_eligible(c)]
    excluded = [c for c in candidates if not is_experiment_eligible(c)]
    assert len(eligible) + len(excluded) == len(candidates)
    # The already_paid_false_alarm archetype guarantees at least one
    # genuinely-paid-but-status-open live invoice exists (see CLAUDE.md).
    assert any(c.is_actually_paid for c in excluded)

    assignment_a = assign_treatment_groups(candidates)
    assignment_b = assign_treatment_groups(candidates)
    assert assignment_a == assignment_b

    treated = {inv_id for inv_id, g in assignment_a.items() if g == TreatmentGroup.ACTED}
    controlled = {inv_id for inv_id, g in assignment_a.items() if g == TreatmentGroup.CONTROL}
    assert treated.isdisjoint(controlled)
    assert len(treated) + len(controlled) == len(eligible)
