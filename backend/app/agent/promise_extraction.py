from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from groq import Groq

from app.agent.resilience import call_with_retry
from app.core.config import settings

GROQ_MODEL = "openai/gpt-oss-120b"

_groq_client: Groq | None = None


def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.llm_api_key)
    return _groq_client


@dataclass(frozen=True)
class ExtractedPromise:
    promised_amount: Decimal
    promised_date: date


def _build_system_prompt(reference_date: date) -> str:
    return (
        "You extract payment promises from a customer's message about an overdue invoice. "
        f"Today's date is {reference_date.isoformat()} ({reference_date.strftime('%A')}). "
        "Resolve relative dates (e.g. 'Friday', 'next week', 'tomorrow') against today's date. "
        "Respond with ONLY a JSON object matching exactly this shape: "
        '{"promise_found": boolean, "promised_amount": number or null, "promised_date": "YYYY-MM-DD" or null}. '
        "Set promise_found to false if the message does not contain a specific commitment to pay a "
        "specific amount by a specific date. Never guess or fabricate either value -- if the amount or "
        "date is vague or missing, promise_found must be false."
    )


def _call_groq_once(transcript: str, reference_date: date, client: Groq | None = None) -> dict:
    groq_client = client or _get_groq_client()
    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": _build_system_prompt(reference_date)},
                {"role": "user", "content": transcript},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        parsed = json.loads(response.choices[0].message.content)
    except Exception as exc:  # noqa: BLE001 -- deliberate boundary catch: API errors, timeouts, malformed JSON all land here
        return {"ok": False, "error": str(exc)}

    if not isinstance(parsed, dict) or "promise_found" not in parsed:
        return {"ok": False, "error": "malformed response shape"}
    if not parsed["promise_found"]:
        return {"ok": True, "promise_found": False}

    try:
        promised_amount = Decimal(str(parsed["promised_amount"]))
        promised_date = date.fromisoformat(parsed["promised_date"])
    except (TypeError, ValueError, KeyError, InvalidOperation):
        return {"ok": False, "error": "malformed promise fields"}

    if promised_amount <= 0:
        return {"ok": False, "error": "non-positive promised_amount"}

    return {"ok": True, "promise_found": True, "promised_amount": promised_amount, "promised_date": promised_date}


def extract_promise(transcript: str, reference_date: date, client: Groq | None = None) -> ExtractedPromise | None:
    """Returns None both when the LLM determines no promise was made AND
    when extraction fails twice (retried via call_with_retry) -- callers
    can't distinguish the two from the return value alone, which is
    intentional: both cases mean the same thing downstream (continue the
    normal pipeline, don't create a promise)."""
    result, _attempts = call_with_retry(
        lambda: _call_groq_once(transcript, reference_date, client),
        is_success=lambda r: r["ok"],
    )
    if not result["ok"] or not result["promise_found"]:
        return None
    return ExtractedPromise(promised_amount=result["promised_amount"], promised_date=result["promised_date"])
