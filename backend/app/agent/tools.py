from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import razorpay

from app.agent.state import ToolResult
from app.core.config import settings
from app.models.enums import ActionType


def _tool_result(*, success: bool, action: str, external_id: str | None, message: str, timestamp: datetime) -> ToolResult:
    return {
        "success": success,
        "action": action,
        "external_id": external_id,
        "message": message,
        "timestamp": timestamp.isoformat(),
    }


def _fake_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def execute_email(*, invoice_number: str, amount: Decimal, now: datetime, failure_mode: bool = False) -> ToolResult:
    """Simulated -- no real email service wired, so always succeeds by
    default: there's no real failure mode to model for a call that doesn't
    go anywhere. failure_mode is a deterministic test seam for Subtask 6's
    retry/fallback tests -- never inject randomness here; production
    behavior through this function must stay deterministic."""
    if failure_mode:
        return _tool_result(
            success=False,
            action=ActionType.EMAIL.value,
            external_id=None,
            message=f"[simulated failure] email send failed for invoice {invoice_number}",
            timestamp=now,
        )
    return _tool_result(
        success=True,
        action=ActionType.EMAIL.value,
        external_id=_fake_id("sim-email"),
        message=f"[simulated] payment reminder email sent for invoice {invoice_number} (Rs.{amount:,.0f})",
        timestamp=now,
    )


def execute_whatsapp(*, invoice_number: str, amount: Decimal, now: datetime, failure_mode: bool = False) -> ToolResult:
    """Simulated -- no real WhatsApp Business API wired. See execute_email's
    docstring for failure_mode's purpose."""
    if failure_mode:
        return _tool_result(
            success=False,
            action=ActionType.WHATSAPP.value,
            external_id=None,
            message=f"[simulated failure] WhatsApp send failed for invoice {invoice_number}",
            timestamp=now,
        )
    return _tool_result(
        success=True,
        action=ActionType.WHATSAPP.value,
        external_id=_fake_id("sim-whatsapp"),
        message=f"[simulated] WhatsApp reminder sent for invoice {invoice_number} (Rs.{amount:,.0f})",
        timestamp=now,
    )


def execute_voice(*, invoice_number: str, amount: Decimal, now: datetime, failure_mode: bool = False) -> ToolResult:
    """Simulated -- no real telephony/TTS wired (master doc's optional voice
    channel, stubbed per the Day-4 scope cut). See execute_email's docstring
    for failure_mode's purpose."""
    if failure_mode:
        return _tool_result(
            success=False,
            action=ActionType.VOICE.value,
            external_id=None,
            message=f"[simulated failure] voice call failed for invoice {invoice_number}",
            timestamp=now,
        )
    return _tool_result(
        success=True,
        action=ActionType.VOICE.value,
        external_id=_fake_id("sim-voice"),
        message=f"[simulated] voice call placed for invoice {invoice_number} (Rs.{amount:,.0f})",
        timestamp=now,
    )


def request_human_handoff(
    *, invoice_number: str, reason: str, now: datetime, failure_mode: bool = False
) -> ToolResult:
    """Simulated -- records an escalation-to-human request. No external
    system involved, so external_id is always None regardless of outcome.
    See execute_email's docstring for failure_mode's purpose."""
    if failure_mode:
        return _tool_result(
            success=False,
            action=ActionType.ESCALATE.value,
            external_id=None,
            message=f"[simulated failure] human handoff request failed for invoice {invoice_number}",
            timestamp=now,
        )
    return _tool_result(
        success=True,
        action=ActionType.ESCALATE.value,
        external_id=None,
        message=f"[simulated] human handoff requested for invoice {invoice_number}: {reason}",
        timestamp=now,
    )


_razorpay_client: razorpay.Client | None = None


def _get_razorpay_client() -> razorpay.Client:
    global _razorpay_client
    if _razorpay_client is None:
        _razorpay_client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    return _razorpay_client


def _decimal_to_paise(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _looks_like_duplicate_reference(exc: Exception) -> bool:
    text = str(exc).lower()
    return "reference_id" in text and ("exist" in text or "duplicate" in text)


def create_payment_link(
    *,
    invoice_id: uuid.UUID,
    invoice_number: str,
    amount: Decimal,
    now: datetime,
    client: razorpay.Client | None = None,
) -> ToolResult:
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        return _tool_result(
            success=False,
            action=ActionType.PAYMENT_LINK.value,
            external_id=None,
            message="Razorpay API keys not configured (RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET)",
            timestamp=now,
        )

    razorpay_client = client or _get_razorpay_client()
    reference_id = str(invoice_id)
    try:
        link = razorpay_client.payment_link.create(
            {
                "amount": _decimal_to_paise(amount),  # paise, Razorpay's smallest INR unit
                "currency": "INR",
                "description": f"Payment for invoice {invoice_number}",
                "reference_id": reference_id,
                "notify": {"sms": False, "email": False},
                "reminder_enable": False,
            }
        )
    except Exception as exc:  # noqa: BLE001 -- deliberate boundary catch, see module docstring
        if _looks_like_duplicate_reference(exc):
            return _tool_result(
                success=True,
                action=ActionType.PAYMENT_LINK.value,
                external_id=None,
                message=(
                    f"payment link already exists for invoice {invoice_number} "
                    f"(idempotent, reference_id={reference_id}) -- not creating a duplicate"
                ),
                timestamp=now,
            )
        return _tool_result(
            success=False,
            action=ActionType.PAYMENT_LINK.value,
            external_id=None,
            message=f"Razorpay API error: {exc}",
            timestamp=now,
        )

    return _tool_result(
        success=True,
        action=ActionType.PAYMENT_LINK.value,
        external_id=link["id"],
        message=f"payment link created: {link['short_url']}",
        timestamp=now,
    )
