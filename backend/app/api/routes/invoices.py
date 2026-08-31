from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import InvoiceSummary
from app.models import AccountState, AttributionRecord, Customer, DecisionLog, Invoice
from app.models.enums import AccountCurrentState

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


def _base_query():
    """Scoped to the live pool via an EXISTS check against decision_logs --
    a real DB fact (only the 900 live invoices have ever been scored), not
    an import of synthetic.generator's date-range constants. See
    app/api/DECISIONS.md."""
    return (
        select(
            Invoice.id,
            Invoice.invoice_number,
            Customer.company_name,
            Invoice.amount,
            Invoice.due_date,
            AccountState.current_state,
            AccountState.recoverability_score,
            AccountState.next_action,
            AttributionRecord.treatment_group,
        )
        .join(Customer, Customer.id == Invoice.customer_id)
        .join(AccountState, AccountState.invoice_id == Invoice.id)
        .outerjoin(AttributionRecord, AttributionRecord.invoice_id == Invoice.id)
        .where(exists().where(DecisionLog.invoice_id == Invoice.id))
    )


def _to_summary(row) -> InvoiceSummary:
    return InvoiceSummary(
        invoice_id=row.id,
        invoice_number=row.invoice_number,
        customer_name=row.company_name,
        amount=float(row.amount),
        due_date=row.due_date,
        current_state=row.current_state.value,
        recoverability_score=row.recoverability_score,
        next_action=row.next_action.value if row.next_action else None,
        treatment_group=row.treatment_group.value if row.treatment_group else None,
    )


@router.get("", response_model=list[InvoiceSummary])
def list_invoices(
    db: Annotated[Session, Depends(get_db)],
    current_state: str | None = Query(default=None),
    segment: str | None = Query(default=None),
    limit: int = Query(default=50, le=500, gt=0),
    offset: int = Query(default=0, ge=0),
):
    query = _base_query()

    if current_state is not None:
        try:
            state_enum = AccountCurrentState(current_state)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown current_state: {current_state!r}")
        # Compared against the enum MEMBER, never the raw string -- SAEnum
        # stores each member's NAME, not its .value, for this column (see
        # CLAUDE.md's known-gotchas list); comparing a raw string directly
        # would silently never match.
        query = query.where(AccountState.current_state == state_enum)

    if segment is not None:
        query = query.where(Customer.segment == segment)

    query = query.order_by(Invoice.due_date).offset(offset).limit(limit)
    rows = db.execute(query).all()
    return [_to_summary(r) for r in rows]


@router.get("/{invoice_id}", response_model=InvoiceSummary)
def get_invoice(invoice_id: UUID, db: Annotated[Session, Depends(get_db)]):
    row = db.execute(_base_query().where(Invoice.id == invoice_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found or never scored")
    return _to_summary(row)
