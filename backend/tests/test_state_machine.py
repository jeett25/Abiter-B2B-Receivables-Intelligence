"""app/agent/state_machine.py tests: pure, no DB required.

Covers every rule in the cascade plus the path contract worked out during
review -- explicitly including PROMISE -> KEPT and
PROMISE -> BROKEN -> REASSESS -> next action, called out by name in this
subtask's own checkpoint.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.agent.events import Event, EventType
from app.agent.state_machine import TransitionContext, determine_next_state
from app.models.enums import AccountCurrentState, ActionType

INVOICE_ID = uuid.uuid4()
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _context(**overrides) -> TransitionContext:
    defaults = dict(
        current_state=AccountCurrentState.OVERDUE,
        event=Event(event_type=EventType.INVOICE_OVERDUE, invoice_id=INVOICE_ID, occurred_at=NOW),
        is_disputed=False,
        is_actually_paid=False,
        selected_action=ActionType.WAIT,
    )
    defaults.update(overrides)
    return TransitionContext(**defaults)


def _event(event_type: EventType, **payload) -> Event:
    return Event(event_type=event_type, invoice_id=INVOICE_ID, occurred_at=NOW, payload=payload)


# -- rule 1: paid always wins --------------------------------------------


def test_actually_paid_wins_regardless_of_event_or_dispute():
    """Paid wins over both the dispute overlay and the broken-promise
    narrative for next_state -- but per the path contract, whatever happened
    this round (BROKEN/REASSESS) is still narrated, exactly like the
    dispute-override cases below preserve PROMISE/BROKEN+REASSESS in path."""
    context = _context(
        event=_event(EventType.PROMISE_BROKEN),
        is_disputed=True,
        is_actually_paid=True,
        selected_action=ActionType.ESCALATE,
    )
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.CLOSED_PAID
    assert result.path == [AccountCurrentState.BROKEN, AccountCurrentState.REASSESS, AccountCurrentState.CLOSED_PAID]


# -- promise created -------------------------------------------------------


def test_promise_created_transitions_to_promise_when_undisputed():
    context = _context(event=_event(EventType.PROMISE_CREATED, promised_amount=200000.0))
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.PROMISE
    assert result.path == [AccountCurrentState.PROMISE]


@pytest.mark.parametrize("selected_action", list(ActionType))
def test_promise_created_next_state_is_independent_of_selected_action(selected_action):
    """Regression test for a cross-subtask invariant Subtask 7's
    update_account_state relies on: determine_next_state must never read
    selected_action for a PROMISE_CREATED event (rule 2 fires before rule 6
    ever looks at it) -- proven directly so a future rule-ordering change
    can't silently break Subtask 7's "inert placeholder" assumption
    (see app/agent/nodes.py's update_account_state) without this catching it."""
    context = _context(event=_event(EventType.PROMISE_CREATED), selected_action=selected_action)
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.PROMISE
    assert result.path == [AccountCurrentState.PROMISE]


def test_promise_created_on_disputed_invoice_still_lands_in_dispute_review():
    """Dispute priority: the promise narrative is preserved in path, but the
    persisted resting state is DISPUTE_REVIEW, not PROMISE."""
    context = _context(event=_event(EventType.PROMISE_CREATED), is_disputed=True)
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.DISPUTE_REVIEW
    assert result.path == [AccountCurrentState.PROMISE, AccountCurrentState.DISPUTE_REVIEW]


# -- promise resolution: KEPT ----------------------------------------------


def test_promise_kept_partial_payment_does_not_close_the_invoice():
    context = _context(
        current_state=AccountCurrentState.PROMISE,
        event=_event(EventType.PAYMENT_PARTIAL, amount=50000.0),
        is_actually_paid=False,
    )
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.KEPT
    assert result.path == [AccountCurrentState.KEPT]


def test_promise_kept_full_payment_closes_the_invoice_but_kept_stays_in_path():
    context = _context(
        current_state=AccountCurrentState.PROMISE,
        event=_event(EventType.PAYMENT_RECEIVED, amount=200000.0),
        is_actually_paid=True,
    )
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.CLOSED_PAID
    assert result.path == [AccountCurrentState.KEPT, AccountCurrentState.CLOSED_PAID]


def test_kept_is_a_readable_resting_state_for_a_later_invocation():
    """No rule branches on current_state == KEPT specially -- a later event
    just flows through the cascade normally, exactly like WAIT/REMIND."""
    context = _context(current_state=AccountCurrentState.KEPT, selected_action=ActionType.WHATSAPP)
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.REMIND
    assert result.path == [AccountCurrentState.REMIND]


# -- promise resolution: BROKEN -> REASSESS --------------------------------


def test_promise_broken_reassesses_to_a_fresh_action_in_one_invocation():
    context = _context(event=_event(EventType.PROMISE_BROKEN, promise_id=str(uuid.uuid4())), selected_action=ActionType.ESCALATE)
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.ESCALATE
    assert result.path == [AccountCurrentState.BROKEN, AccountCurrentState.REASSESS, AccountCurrentState.ESCALATE]


def test_promise_broken_on_disputed_invoice_lands_in_dispute_review():
    context = _context(event=_event(EventType.PROMISE_BROKEN), is_disputed=True, selected_action=ActionType.WHATSAPP)
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.DISPUTE_REVIEW
    assert result.path == [
        AccountCurrentState.BROKEN,
        AccountCurrentState.REASSESS,
        AccountCurrentState.DISPUTE_REVIEW,
    ]


# -- dispute overlay, no promise involved ----------------------------------


def test_disputed_invoice_with_no_promise_event_goes_straight_to_dispute_review():
    context = _context(is_disputed=True, selected_action=ActionType.WHATSAPP)
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.DISPUTE_REVIEW
    assert result.path == [AccountCurrentState.DISPUTE_REVIEW]


# -- ordinary assessment outcome -------------------------------------------


@pytest.mark.parametrize(
    "action,expected",
    [
        (ActionType.WAIT, AccountCurrentState.WAIT),
        (ActionType.EMAIL, AccountCurrentState.REMIND),
        (ActionType.WHATSAPP, AccountCurrentState.REMIND),
        (ActionType.PAYMENT_LINK, AccountCurrentState.REMIND),
        (ActionType.VOICE, AccountCurrentState.REMIND),
        (ActionType.ESCALATE, AccountCurrentState.ESCALATE),
    ],
)
def test_ordinary_action_outcome_mapping(action, expected):
    context = _context(selected_action=action)
    result = determine_next_state(context)
    assert result.next_state == expected
    assert result.path == [expected]


def test_stop_maps_to_closed_abandoned_when_not_actually_paid():
    context = _context(selected_action=ActionType.STOP, is_actually_paid=False)
    result = determine_next_state(context)
    assert result.next_state == AccountCurrentState.CLOSED_ABANDONED
    assert result.path == [AccountCurrentState.CLOSED_ABANDONED]
