"""synthetic/seed_demo.py tests -- real side effects against the dev DB are
deliberate here, same precedent as test_decision_persist.py/test_audit.py:
this script's entire purpose is keeping the 6 demo fixtures healthy, so
running its reset+check logic as part of the test suite is itself a
continuous verification that the demo still works, not an unwanted
mutation to avoid."""
from synthetic.seed_demo import FIXTURE_CHECKS, _load_fixtures, reset_and_reassess, seed_demo


def test_fixture_checks_cover_every_fixture_in_demo_fixtures_json():
    fixtures = _load_fixtures()
    assert set(FIXTURE_CHECKS.keys()) == set(fixtures.keys())


def test_reset_and_reassess_reliable_payer_wait_passes_its_own_check(db_session):
    fixtures = _load_fixtures()
    result = reset_and_reassess(fixtures["reliable_payer_wait"]["invoice_number"])
    passed, detail = FIXTURE_CHECKS["reliable_payer_wait"](result)
    assert passed, detail


def test_reset_and_reassess_chronic_late_escalate_now_expects_voice(db_session):
    """Reframed after subtask 6's ESCALATE fix -- INV-10184 (Rs.118,361) is
    above ESCALATE_LARGE_AMOUNT_THRESHOLD_INR, so VOICE is the correct
    current answer, not the pre-Day-5 ESCALATE. See app/decision/DECISIONS.md."""
    fixtures = _load_fixtures()
    result = reset_and_reassess(fixtures["chronic_late_escalate"]["invoice_number"])
    passed, detail = FIXTURE_CHECKS["chronic_late_escalate"](result)
    assert passed, detail


def test_reset_and_reassess_promise_breaker_reassess_passes_its_own_check(db_session):
    fixtures = _load_fixtures()
    result = reset_and_reassess(fixtures["promise_breaker_reassess"]["invoice_number"])
    passed, detail = FIXTURE_CHECKS["promise_breaker_reassess"](result)
    assert passed, detail


def test_reset_and_reassess_low_value_stop_passes_its_own_check(db_session):
    fixtures = _load_fixtures()
    result = reset_and_reassess(fixtures["low_value_stop"]["invoice_number"])
    passed, detail = FIXTURE_CHECKS["low_value_stop"](result)
    assert passed, detail


def test_reset_and_reassess_high_value_act_passes_its_own_check(db_session):
    fixtures = _load_fixtures()
    result = reset_and_reassess(fixtures["high_value_act"]["invoice_number"])
    passed, detail = FIXTURE_CHECKS["high_value_act"](result)
    assert passed, detail


def test_reset_and_reassess_already_paid_suppress_stays_suppressed(db_session):
    """Confirms the unified reset path needs no special-casing for this
    fixture: it never received a Day-5 write-back (correctly excluded as
    already-paid), so nothing gets deleted, and re-running against its
    ORIGINAL untouched payment row reproduces is_actually_paid=True ->
    CLOSED_PAID every time."""
    fixtures = _load_fixtures()
    result = reset_and_reassess(fixtures["already_paid_suppress"]["invoice_number"])
    passed, detail = FIXTURE_CHECKS["already_paid_suppress"](result)
    assert passed, detail


def test_seed_demo_end_to_end_reports_all_clear(db_session):
    assert seed_demo() is True
