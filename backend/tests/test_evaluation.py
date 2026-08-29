"""app/decision/evaluation.py tests -- pure, no DB. Decision objects are
built directly rather than via decide(), since evaluation only needs
invoice_id/base_probability/amount/final_action."""
from app.decision.economics import ActionEV
from app.decision.evaluation import (
    StrategyOutcome,
    baseline_outcomes,
    engine_outcomes,
    evaluate_escalation_appropriateness,
    summarize_strategy,
    unnecessary_interventions_avoided,
)
from app.decision.policy import PolicyVerdict
from app.decision.service import Decision
from app.models.enums import ActionType, PolicyResult


def _decision(invoice_id, final_action, base_probability=0.5, amount=10_000.0) -> Decision:
    return Decision(
        invoice_id=invoice_id,
        base_probability=base_probability,
        amount=amount,
        is_disputed=False,
        is_actually_paid=False,
        economics_ranking=[ActionEV(final_action, base_probability, 0.0, 0.0, 0.0)],
        proposed_action=final_action,
        retrieved_cases=[],
        policy_verdict=PolicyVerdict(PolicyResult.ALLOWED, final_action, "test"),
        final_action=final_action,
    )


def test_baseline_outcomes_are_always_email_regardless_of_engine_action():
    decisions = [_decision("a", ActionType.WAIT), _decision("b", ActionType.STOP), _decision("c", ActionType.ESCALATE)]
    outcomes = baseline_outcomes(decisions)
    assert all(o.action == ActionType.EMAIL for o in outcomes)
    # probabilities/amounts reused as-is, not recomputed
    assert [o.base_probability for o in outcomes] == [d.base_probability for d in decisions]


def test_engine_outcomes_use_each_decisions_final_action():
    decisions = [_decision("a", ActionType.WAIT), _decision("b", ActionType.ESCALATE)]
    outcomes = engine_outcomes(decisions)
    assert [o.action for o in outcomes] == [ActionType.WAIT, ActionType.ESCALATE]


def test_summarize_strategy_counts_wait_and_stop_separately_from_interventions():
    outcomes = [
        StrategyOutcome("a", ActionType.WAIT, 0.5, 10_000.0),
        StrategyOutcome("b", ActionType.STOP, 0.1, 5_000.0),
        StrategyOutcome("c", ActionType.EMAIL, 0.5, 10_000.0),
        StrategyOutcome("d", ActionType.ESCALATE, 0.5, 300_000.0),
    ]
    summary = summarize_strategy("test", outcomes)
    assert summary.n_invoices == 4
    assert summary.n_wait == 1
    assert summary.n_stop == 1
    assert summary.n_interventions == 2


def test_summarize_strategy_net_is_gross_minus_cost_minus_friction():
    outcomes = [StrategyOutcome("a", ActionType.WAIT, 0.5, 10_000.0)]
    summary = summarize_strategy("test", outcomes)
    # WAIT: uplift=0, cost=0, friction=0 -> gross=0.5*10000=5000, net=5000
    assert summary.gross_expected_recovered == 5_000.0
    assert summary.total_cost == 0.0
    assert summary.total_friction == 0.0
    assert summary.net_expected_recovered == 5_000.0


def test_summarize_strategy_recovery_rate_is_gross_over_total_amount():
    outcomes = [StrategyOutcome("a", ActionType.WAIT, 0.4, 10_000.0)]
    summary = summarize_strategy("test", outcomes)
    assert summary.recovery_rate == summary.gross_expected_recovered / summary.total_amount


def test_summarize_strategy_empty_list_does_not_divide_by_zero():
    summary = summarize_strategy("empty", [])
    assert summary.n_invoices == 0
    assert summary.recovery_rate == 0.0


def test_unnecessary_interventions_avoided_equals_engine_wait_plus_stop():
    decisions = [
        _decision("a", ActionType.WAIT),
        _decision("b", ActionType.STOP),
        _decision("c", ActionType.EMAIL),
        _decision("d", ActionType.ESCALATE),
    ]
    baseline_summary = summarize_strategy("baseline", baseline_outcomes(decisions))
    engine_summary = summarize_strategy("engine", engine_outcomes(decisions))
    assert unnecessary_interventions_avoided(baseline_summary, engine_summary) == 2


def test_escalation_appropriateness_diagnostic_counts_high_and_low_uplift_shares():
    decisions = [
        _decision("a", ActionType.ESCALATE),
        _decision("b", ActionType.ESCALATE),
        _decision("c", ActionType.ESCALATE),
        _decision("d", ActionType.WAIT),  # not escalated, excluded
    ]
    archetype_by_invoice = {
        "a": "chronic_late",
        "b": "chronic_late",
        "c": "reliable_payer",
        "d": "chronic_late",
    }
    result = evaluate_escalation_appropriateness(decisions, archetype_by_invoice)
    assert result["n_escalated"] == 3
    assert result["high_uplift_share"] == 2 / 3
    assert result["low_uplift_share"] == 1 / 3


def test_escalation_appropriateness_diagnostic_handles_no_escalations():
    decisions = [_decision("a", ActionType.WAIT)]
    result = evaluate_escalation_appropriateness(decisions, {"a": "chronic_late"})
    assert result["n_escalated"] == 0
