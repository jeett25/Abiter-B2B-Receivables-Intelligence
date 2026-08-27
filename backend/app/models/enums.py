import enum

from sqlalchemy import Enum as SAEnum


class InvoiceStatus(str, enum.Enum):
    OPEN = "open"
    DISPUTED = "disputed"
    PROMISED = "promised"
    PAID = "paid"
    WRITTEN_OFF = "written_off"


class PromiseStatus(str, enum.Enum):
    OPEN = "open"
    KEPT = "kept"
    BROKEN = "broken"


class PaymentStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"


class ActionType(str, enum.Enum):
    WAIT = "wait"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    PAYMENT_LINK = "payment_link"
    VOICE = "voice"
    ESCALATE = "escalate"
    STOP = "stop"


class PolicyResult(str, enum.Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"


class AccountCurrentState(str, enum.Enum):
    OVERDUE = "overdue"
    ASSESSMENT = "assessment"
    WAIT = "wait"
    REMIND = "remind"
    ESCALATE = "escalate"
    PROMISE = "promise"
    MONITORING = "monitoring"
    KEPT = "kept"
    BROKEN = "broken"
    REASSESS = "reassess"
    CLOSED = "closed"


class TreatmentGroup(str, enum.Enum):
    ACTED = "acted"
    CONTROL = "control"


# Shared SQLAlchemy Enum instances: reuse the same object wherever a Postgres
# enum type is referenced from more than one table, so Alembic/SQLAlchemy
# treat it as one native type instead of trying to create it twice.
invoice_status_enum = SAEnum(InvoiceStatus, name="invoice_status")
promise_status_enum = SAEnum(PromiseStatus, name="promise_status")
payment_status_enum = SAEnum(PaymentStatus, name="payment_status")
action_type_enum = SAEnum(ActionType, name="action_type")
policy_result_enum = SAEnum(PolicyResult, name="policy_result")
account_current_state_enum = SAEnum(AccountCurrentState, name="account_current_state")
treatment_group_enum = SAEnum(TreatmentGroup, name="treatment_group")
