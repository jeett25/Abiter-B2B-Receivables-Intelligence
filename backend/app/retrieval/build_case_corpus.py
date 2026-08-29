from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from app.core.db import SessionLocal
from app.core.db import engine as default_engine
from app.ml.features import build_feature_table, load_raw_tables
from app.models import CaseEmbedding
from app.models.enums import InvoiceStatus

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _ordered_distinct_actions(actions: pd.DataFrame) -> dict:
    """invoice_id -> distinct action_type strings, in the order first taken."""
    result: dict = {}
    for invoice_id, group in actions.sort_values("timestamp").groupby("invoice_id"):
        seen: list[str] = []
        for action_type in group["action_type"]:
            if action_type not in seen:
                seen.append(action_type)
        result[invoice_id] = seen
    return result


def build_case_text(
    *,
    amount: float,
    payment_term_days: int,
    segment: str,
    industry: str,
    prior_payment_rate: float | None,
    action_types: list[str],
    status: str,
    delay_days: int | None,
) -> str:
    """Pure text synthesis -- no DB/model calls, independently testable."""
    prior_history = (
        f"prior payment rate {prior_payment_rate:.0%}"
        if prior_payment_rate is not None
        else "no prior payment history"
    )
    actions_desc = ", ".join(action_types) if action_types else "no follow-up action taken"

    if status == InvoiceStatus.PAID.value:
        outcome = f"paid {delay_days} days late" if delay_days and delay_days > 0 else "paid on time"
    else:
        outcome = "written off, never recovered"

    return (
        f"{segment} segment, {industry} industry customer. "
        f"Invoice amount Rs.{amount:,.0f}, {payment_term_days}-day payment terms. "
        f"{prior_history}. "
        f"Actions taken: {actions_desc}. "
        f"Outcome: {outcome}."
    )


def build_corpus_rows(engine: Engine | None = None) -> pd.DataFrame:
    """One row per historical invoice: invoice_id/customer_id/merchant_id,
    case_text, and the denormalized metadata columns CaseEmbedding stores."""
    table = build_feature_table(engine)
    actions = load_raw_tables(engine)["actions"]
    actions_by_invoice = _ordered_distinct_actions(actions)

    rows = []
    for _, row in table.iterrows():
        delay_days = None
        if row["status"] == InvoiceStatus.PAID.value and pd.notna(row["paid_at"]):
            delay_days = (row["paid_at"] - row["due_date"]).days

        action_types = actions_by_invoice.get(row["invoice_id"], [])
        case_text = build_case_text(
            amount=row["amount"],
            payment_term_days=row["payment_term_days"],
            segment=row["customer_segment"],
            industry=row["customer_industry"],
            prior_payment_rate=row["prior_payment_rate"] if pd.notna(row["prior_payment_rate"]) else None,
            action_types=action_types,
            status=row["status"],
            delay_days=delay_days,
        )
        rows.append(
            {
                "invoice_id": row["invoice_id"],
                "customer_id": row["customer_id"],
                "merchant_id": row["merchant_id"],
                "case_text": case_text,
                "status": row["status"],
                "delay_days": delay_days,
                "amount": row["amount"],
                "segment": row["customer_segment"],
                "industry": row["customer_industry"],
                "action_types": action_types,
            }
        )
    return pd.DataFrame(rows)


def embed_texts(texts: list[str]) -> list[list[float]]:
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
    return [vector.tolist() for vector in model.embed(texts)]


def populate_case_embeddings(engine: Engine | None = None) -> int:
    engine = engine or default_engine
    corpus = build_corpus_rows(engine)
    embeddings = embed_texts(corpus["case_text"].tolist())

    session = SessionLocal()
    try:
        session.query(CaseEmbedding).delete()
        rows = [
            CaseEmbedding(
                invoice_id=row["invoice_id"],
                customer_id=row["customer_id"],
                merchant_id=row["merchant_id"],
                case_text=row["case_text"],
                embedding=embedding,
                status=row["status"],
                # pd.DataFrame(rows) upcasts this column to float64 once any
                # row has None (written-off has no delay_days), turning every
                # None into NaN -- NaN has no valid Postgres Integer
                # representation, so it must become None again here.
                delay_days=None if pd.isna(row["delay_days"]) else int(row["delay_days"]),
                amount=row["amount"],
                segment=row["segment"],
                industry=row["industry"],
                action_types=row["action_types"],
            )
            for (_, row), embedding in zip(corpus.iterrows(), embeddings)
        ]
        session.add_all(rows)
        session.commit()
        return len(rows)
    finally:
        session.close()


if __name__ == "__main__":
    n = populate_case_embeddings()
    print(f"Populated {n} case_embeddings rows using model={EMBEDDING_MODEL_NAME}")
