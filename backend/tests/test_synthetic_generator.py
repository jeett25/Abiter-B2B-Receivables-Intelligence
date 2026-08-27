"""Synthetic generator tests: archetype math (pure, no DB) and dataset
validation (DB-backed, assumes synthetic.generator has already been run)."""
import json
import random

from sqlalchemy import select

from app.models import Invoice
from app.models.enums import ActionType
from synthetic.archetypes import AMOUNT_MAX, AMOUNT_MIN, ARCHETYPES, DISPUTE_RATE, INTERVENTION_COSTS
from synthetic.demo_fixtures import FIXTURES_PATH, SCENARIOS
from synthetic.generator import _draw_intervention_cost, _draw_root_cause, _lognormal_amount
from synthetic.validators import run_all_validations


def test_archetype_population_shares_sum_to_one():
    total = sum(a.population_share for a in ARCHETYPES.values())
    assert abs(total - 1.0) < 1e-9


def test_lognormal_amount_respects_bounds():
    rng = random.Random(123)
    for archetype in ARCHETYPES.values():
        for _ in range(200):
            amount = _lognormal_amount(rng, archetype.amount_lognormal_mean, archetype.amount_lognormal_sigma)
            assert AMOUNT_MIN <= float(amount) <= AMOUNT_MAX


def test_intervention_cost_within_configured_range():
    rng = random.Random(123)
    voice_low, voice_high = INTERVENTION_COSTS[ActionType.VOICE]
    escalate_low, escalate_high = INTERVENTION_COSTS[ActionType.ESCALATE]
    for _ in range(200):
        voice_cost = _draw_intervention_cost(rng, ActionType.VOICE)
        assert voice_low <= float(voice_cost) <= voice_high

        escalate_cost = _draw_intervention_cost(rng, ActionType.ESCALATE)
        assert escalate_low <= float(escalate_cost) <= escalate_high


def test_dispute_rate_matches_target_within_tolerance():
    rng = random.Random(123)
    archetype = ARCHETYPES["slightly_late"]
    n = 20000
    disputes = sum(1 for _ in range(n) if _draw_root_cause(rng, archetype) == "dispute")
    observed_rate = disputes / n
    assert abs(observed_rate - DISPUTE_RATE) < 0.01


def test_validation_suite_passes_on_generated_dataset(db_session):
    results = run_all_validations(db_session)
    failures = {name: violations for name, violations in results.items() if violations}
    assert not failures, f"Validation failures: {failures}"


def test_demo_fixtures_file_has_all_six_scenarios_and_valid_invoices(db_session):
    assert FIXTURES_PATH.exists(), "Run `python -m synthetic.demo_fixtures` first"
    data = json.loads(FIXTURES_PATH.read_text())
    assert set(data.keys()) == set(SCENARIOS.keys())

    for key, entry in data.items():
        invoice = db_session.execute(
            select(Invoice).where(Invoice.invoice_number == entry["invoice_number"])
        ).scalar_one_or_none()
        assert invoice is not None, f"{key}: invoice {entry['invoice_number']} not found in database"
