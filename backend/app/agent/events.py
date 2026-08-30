from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class EventType(str, enum.Enum):
    INVOICE_OVERDUE = "invoice.overdue"
    PROMISE_CREATED = "promise.created"
    PROMISE_BROKEN = "promise.broken"
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_PARTIAL = "payment.partial"
    CUSTOMER_RESPONDED = "customer.responded"
    ACTION_FAILED = "action.failed"
    REVIEW_TIMEOUT = "review.timeout"


@dataclass(frozen=True, kw_only=True)
class Event:
    event_type: EventType
    invoice_id: uuid.UUID
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
