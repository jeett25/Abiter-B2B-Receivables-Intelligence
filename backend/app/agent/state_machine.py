"""The account state machine -- Subtask 4.

Centralizes every (current_state, event, ...) -> next_state decision in this
project. Nothing else infers or sets an account-state transition
independently (see docs/agent-DECISIONS.md's UPDATE_STATE-is-scaffolding
entry, which this module retires).

Mirrors app.decision.policy's shape deliberately: a small frozen context
object in, a small frozen verdict object out, evaluated as an ordered,
first-match-wins rule cascade -- same pattern as PolicyContext/PolicyVerdict/
evaluate_policy, different rules.

path contract (consumed by Subtask 9's audit narrative): always
[...intermediate states..., next_state], deduplicated if next_state already
equals the last intermediate entry. See this module's tests for worked
examples.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agent.events import Event, EventType
from app.models.enums import AccountCurrentState, ActionType

# Mirrors economics.CANDIDATE_ACTIONS minus STOP, which determine_next_state
# handles via is_actually_paid/selected_action directly (STOP maps to one of
# two CLOSED_* states depending on why, never a single static entry here).
_ACTION_TO_STATE: dict[ActionType, AccountCurrentState] = {
    ActionType.WAIT: AccountCurrentState.WAIT,
    ActionType.EMAIL: AccountCurrentState.REMIND,
    ActionType.WHATSAPP: AccountCurrentState.REMIND,
    ActionType.PAYMENT_LINK: AccountCurrentState.REMIND,
    ActionType.VOICE: AccountCurrentState.REMIND,
    ActionType.ESCALATE: AccountCurrentState.ESCALATE,
}


@dataclass(frozen=True)
class TransitionContext:
    current_state: AccountCurrentState
    event: Event
    is_disputed: bool
    is_actually_paid: bool
    selected_action: ActionType  # this round's fresh economics+policy outcome


@dataclass(frozen=True)
class StateTransition:
    next_state: AccountCurrentState
    path: list[AccountCurrentState]


def _event_narrative(
    context: TransitionContext,
) -> tuple[list[AccountCurrentState], AccountCurrentState | None]:
    """Returns (path labels narrating what happened this round, a
    resting-state candidate or None). BROKEN/REASSESS narrate PROMISE_BROKEN
    but are never resting-state candidates themselves -- the graph has
    already run a fresh assessment by the time this executes, so the
    resting value after a broken promise is always the fresh
    selected_action (determine_next_state's fallthrough), never REASSESS
    itself. PROMISE and KEPT, by contrast, genuinely are valid resting
    states absent an overriding paid/disputed condition."""
    event_type = context.event.event_type

    if event_type == EventType.PROMISE_CREATED:
        return [AccountCurrentState.PROMISE], AccountCurrentState.PROMISE

    if event_type == EventType.PROMISE_BROKEN:
        return [AccountCurrentState.BROKEN, AccountCurrentState.REASSESS], None

    if context.current_state == AccountCurrentState.PROMISE and event_type in (
        EventType.PAYMENT_RECEIVED,
        EventType.PAYMENT_PARTIAL,
    ):
        return [AccountCurrentState.KEPT], AccountCurrentState.KEPT

    return [], None


def determine_next_state(context: TransitionContext) -> StateTransition:
    intermediate, resting_candidate = _event_narrative(context)

    if context.is_actually_paid:
        next_state = AccountCurrentState.CLOSED_PAID
    elif context.is_disputed:
        # Disputes take priority over the broken-promise/action narrative for
        # the PERSISTED resting state -- intentional, not rule-order
        # accident. The promise-related event (if any) is still preserved in
        # `path` below; it just never becomes the resting current_state
        # while the dispute is open. See DECISIONS.md for the resulting
        # de-facto-absorbing-state consequence.
        next_state = AccountCurrentState.DISPUTE_REVIEW
    elif resting_candidate is not None:
        next_state = resting_candidate
    elif context.selected_action == ActionType.STOP:
        next_state = AccountCurrentState.CLOSED_ABANDONED
    else:
        next_state = _ACTION_TO_STATE[context.selected_action]

    if intermediate and intermediate[-1] == next_state:
        path = intermediate
    else:
        path = intermediate + [next_state]

    return StateTransition(next_state=next_state, path=path)
