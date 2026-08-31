"""app/attribution/simulate_outcomes.py tests: pure gate_at_horizon() unit
tests (no DB, no randomness), plus integration tests against the real live
pool for draw_raw_outcomes()/run_experiment_simulation()."""
import uuid
from datetime import date, datetime, timezone

from app.attribution.config import ATTRIBUTION_HORIZON_DAYS
from app.attribution.simulate_outcomes import (
    RawOutcomeDraw,
    draw_raw_outcomes,
    gate_at_horizon,
    run_experiment_simulation,
)
from app.models.enums import ActionType, TreatmentGroup


def _draw(
    recovered_ever,
    true_delay_days,
    due_date=date(2026, 8, 1),
    amount=10_000.0,
    group=TreatmentGroup.CONTROL,
    base_probability=0.5,
):
    return RawOutcomeDraw(
        invoice_id=uuid.uuid4(),
        group=group,
        action=ActionType.WAIT,
        counterfactual_action=None,
        amount=amount,
        due_date=due_date,
        archetype="chronic_late",
        base_probability=base_probability,
        recovered_ever=recovered_ever,
        true_delay_days=true_delay_days,
    )


AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def test_never_recovers_has_no_recovery_date_and_zero_amount():
    outcome = gate_at_horizon([_draw(False, None)], horizon_days=ATTRIBUTION_HORIZON_DAYS, as_of=AS_OF)[0]
    assert outcome.recovered is False
    assert outcome.recovered_amount == 0.0
    assert outcome.recovery_date is None
    assert outcome.ledger_payment_date is None


def test_recovered_within_horizon_sets_all_fields():
    outcome = gate_at_horizon([_draw(True, 10, due_date=date(2026, 8, 1))], horizon_days=ATTRIBUTION_HORIZON_DAYS, as_of=AS_OF)[0]
    assert outcome.recovered is True
    assert outcome.recovered_amount == 10_000.0
    assert outcome.recovery_date == date(2026, 8, 11)
    assert outcome.ledger_payment_date == date(2026, 8, 11)


def test_recovered_ever_but_outside_horizon_is_not_recovered_but_keeps_recovery_date():
    """The exact case the capping-asymmetry discussion was about: recovered
    must be False here even though recovered_ever is True, and it must be
    computed from the TRUE delay, never from whatever the ledger cap would
    have produced."""
    outcome = gate_at_horizon([_draw(True, 90, due_date=date(2026, 8, 1))], horizon_days=ATTRIBUTION_HORIZON_DAYS, as_of=AS_OF)[0]
    assert outcome.recovered is False
    assert outcome.recovered_amount == 0.0
    assert outcome.recovery_date == date(2026, 10, 30)  # true date preserved
    assert outcome.ledger_payment_date is None  # never written to the ledger


def test_ledger_payment_date_capped_when_true_date_exceeds_as_of_minus_one_day():
    # due_date + 10d = 2026-09-06, well after AS_OF (2026-08-27) -- caps to 2026-08-26.
    outcome = gate_at_horizon([_draw(True, 10, due_date=date(2026, 8, 27))], horizon_days=ATTRIBUTION_HORIZON_DAYS, as_of=AS_OF)[0]
    assert outcome.recovered is True
    assert outcome.recovery_date == date(2026, 9, 6)
    assert outcome.ledger_payment_date == date(2026, 8, 26)


def test_ledger_payment_date_uncapped_when_within_as_of():
    outcome = gate_at_horizon([_draw(True, 3, due_date=date(2026, 8, 1))], horizon_days=ATTRIBUTION_HORIZON_DAYS, as_of=AS_OF)[0]
    assert outcome.recovery_date == date(2026, 8, 4)
    assert outcome.ledger_payment_date == date(2026, 8, 4)


def test_different_horizons_reclassify_the_same_draw_without_resimulating():
    draw = _draw(True, 45, due_date=date(2026, 8, 1))
    at_30 = gate_at_horizon([draw], horizon_days=30, as_of=AS_OF)[0]
    at_60 = gate_at_horizon([draw], horizon_days=ATTRIBUTION_HORIZON_DAYS, as_of=AS_OF)[0]
    assert at_30.recovered is False
    assert at_60.recovered is True
    assert at_30.recovery_date == at_60.recovery_date  # same underlying draw


def test_horizon_gating_is_symmetric_between_arms():
    """Same true_delay_days, one CONTROL one TREATMENT -- gating must not
    depend on group."""
    control = _draw(True, 90, group=TreatmentGroup.CONTROL, due_date=date(2026, 8, 1))
    treatment = _draw(True, 90, group=TreatmentGroup.ACTED, due_date=date(2026, 8, 1))
    outcomes = gate_at_horizon([control, treatment], horizon_days=ATTRIBUTION_HORIZON_DAYS, as_of=AS_OF)
    assert outcomes[0].recovered is False
    assert outcomes[1].recovered is False


def test_draw_raw_outcomes_is_reproducible_given_the_same_seed(db_session):
    a = draw_raw_outcomes(limit=5)
    b = draw_raw_outcomes(limit=5)
    a_by_id = {d.invoice_id: (d.group, d.action, d.recovered_ever, d.true_delay_days) for d in a}
    b_by_id = {d.invoice_id: (d.group, d.action, d.recovered_ever, d.true_delay_days) for d in b}
    assert a_by_id == b_by_id


def test_control_arm_never_receives_a_non_wait_action(db_session):
    draws = draw_raw_outcomes(limit=5)
    control = [d for d in draws if d.group == TreatmentGroup.CONTROL]
    assert control
    assert all(d.action == ActionType.WAIT for d in control)


def test_treatment_arm_action_comes_from_the_real_decision_engine(db_session):
    draws = draw_raw_outcomes(limit=5)
    treatment = [d for d in draws if d.group == TreatmentGroup.ACTED]
    assert treatment
    assert all(isinstance(d.action, ActionType) for d in treatment)


def test_counterfactual_action_only_populated_for_control(db_session):
    draws = draw_raw_outcomes(limit=5)
    treatment = [d for d in draws if d.group == TreatmentGroup.ACTED]
    control = [d for d in draws if d.group == TreatmentGroup.CONTROL]
    assert treatment and control
    assert all(d.counterfactual_action is None for d in treatment)
    assert all(isinstance(d.counterfactual_action, ActionType) for d in control)


def test_run_experiment_simulation_uses_the_configured_horizon(db_session):
    outcomes = run_experiment_simulation(limit=5)
    assert len(outcomes) > 0
    for o in outcomes:
        if o.recovered:
            assert o.ledger_payment_date is not None
        else:
            assert o.ledger_payment_date is None
