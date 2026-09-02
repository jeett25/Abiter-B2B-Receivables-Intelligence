"""One-off retroactive fix (2026-09-02): invoices already resolved by the
Day-5 attribution experiment's ledger write-back, before build_closing_decision_log()
existed, are missing the closing decision_logs entry that going-forward runs
now get automatically (see _apply_ledger_write_back in persist.py). Without
it, those invoices' header (account_state, correct) and "Why this
decision?"/Timeline (decision_logs, stale -- frozen before the payment) look
inconsistent.

Read-only-safe to rerun: skips any invoice that already has a closing entry
(reason contains CLOSING_ENTRY_MARKER), so running this twice never creates
duplicates. Does NOT touch account_state/invoices -- those are already
correct; this only fills the missing audit-trail entry.
"""
from __future__ import annotations

from sqlalchemy import select

from app.attribution.persist import CLOSING_ENTRY_MARKER, LEDGER_PAYMENT_METHOD, build_closing_decision_log
from app.core.db import SessionLocal
from app.models import DecisionLog, Payment


def backfill() -> dict:
    session = SessionLocal()
    try:
        write_back_payments = session.execute(
            select(Payment.invoice_id, Payment.payment_date).where(Payment.method == LEDGER_PAYMENT_METHOD)
        ).all()

        already_closed = set(
            session.execute(
                select(DecisionLog.invoice_id).where(DecisionLog.reason.contains(CLOSING_ENTRY_MARKER))
            )
            .scalars()
            .all()
        )

        n_written = 0
        for invoice_id, payment_date in write_back_payments:
            if invoice_id in already_closed:
                continue
            session.add(build_closing_decision_log(invoice_id, payment_date, session))
            already_closed.add(invoice_id)  # guard against duplicate Payment rows for the same invoice
            n_written += 1

        session.commit()
        return {"n_write_back_invoices": len(write_back_payments), "n_written": n_written}
    finally:
        session.close()


if __name__ == "__main__":
    result = backfill()
    print(
        f"{result['n_write_back_invoices']} invoices have an attribution write-back payment; "
        f"wrote {result['n_written']} new closing decision_logs entries "
        f"({result['n_write_back_invoices'] - result['n_written']} already had one -- safe rerun)."
    )
