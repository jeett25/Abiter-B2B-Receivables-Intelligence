from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.ml.config import SEED
from app.models import CaseEmbedding, Invoice
from app.retrieval.build_case_corpus import EMBEDDING_MODEL_NAME

MIN_CANDIDATES = 30
RRF_K = 60

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding

        _embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
    return _embedding_model


def embed_query(text: str) -> list[float]:
    return next(iter(_get_embedding_model().embed([text]))).tolist()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def build_query_text(
    *,
    amount: float,
    payment_term_days: int,
    segment: str,
    industry: str,
    prior_payment_rate: float | None,
    days_overdue: int | None = None,
) -> str:
    prior_history = (
        f"prior payment rate {prior_payment_rate:.0%}"
        if prior_payment_rate is not None
        else "no prior payment history"
    )
    overdue_clause = f" Currently {days_overdue} days overdue." if days_overdue is not None else ""
    return (
        f"{segment} segment, {industry} industry customer. "
        f"Invoice amount Rs.{amount:,.0f}, {payment_term_days}-day payment terms. "
        f"{prior_history}.{overdue_clause}"
    )


@dataclass(frozen=True)
class RetrievedCase:
    invoice_id: object
    case_text: str
    status: str
    delay_days: int | None
    amount: float
    segment: str
    industry: str
    action_types: list
    vector_rank: int
    bm25_rank: int
    amount_rank: int
    rrf_score: float


def _candidate_filter_levels(segment: str, industry: str, is_disputed: bool) -> list[list]:
    """Monotonic relaxation cascade, ordered from most to least specific,
    dropping exactly one constraint per level -- least important first
    (industry, then segment, then -- only relevant if is_disputed -- the
    dispute preference itself) -- and always ending at [] (no filter at
    all), so a real, non-empty corpus can never make this return nothing."""
    if is_disputed:
        return [
            [Invoice.true_root_cause == "dispute", CaseEmbedding.segment == segment, CaseEmbedding.industry == industry],
            [Invoice.true_root_cause == "dispute", CaseEmbedding.segment == segment],
            [Invoice.true_root_cause == "dispute"],
            [CaseEmbedding.segment == segment, CaseEmbedding.industry == industry],
            [CaseEmbedding.segment == segment],
            [],
        ]
    return [
        [CaseEmbedding.segment == segment, CaseEmbedding.industry == industry],
        [CaseEmbedding.segment == segment],
        [],
    ]


def _fetch_candidate_pool(
    session: Session,
    segment: str,
    industry: str,
    is_disputed: bool,
    exclude_invoice_id,
    min_candidates: int = MIN_CANDIDATES,
) -> list[CaseEmbedding]:
    base = select(CaseEmbedding)
    if is_disputed:
        base = base.join(Invoice, Invoice.id == CaseEmbedding.invoice_id)
    if exclude_invoice_id is not None:
        base = base.where(CaseEmbedding.invoice_id != exclude_invoice_id)

    last_rows: list[CaseEmbedding] = []
    for conditions in _candidate_filter_levels(segment, industry, is_disputed):
        stmt = base
        for condition in conditions:
            stmt = stmt.where(condition)
        rows = list(session.execute(stmt).scalars().all())
        last_rows = rows
        if len(rows) >= min_candidates:
            return rows
    return last_rows


def _ranks_from_values(ids: list, values: list[float], *, descending: bool) -> dict:
    order = sorted(range(len(ids)), key=lambda i: values[i], reverse=descending)
    return {ids[idx]: rank for rank, idx in enumerate(order, start=1)}


def _cosine_similarity(a, b) -> float:
    a_arr, b_arr = np.array(a, dtype=float), np.array(b, dtype=float)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))


def _rrf_fuse(*rank_dicts: dict, k: int = RRF_K) -> dict:
    ids = rank_dicts[0].keys()
    return {i: sum(1.0 / (k + ranks[i]) for ranks in rank_dicts) for i in ids}


def hybrid_retrieve(
    query_text: str,
    query_amount: float,
    segment: str,
    industry: str,
    is_disputed: bool = False,
    top_k: int = 5,
    exclude_invoice_id=None,
    session: Session | None = None,
) -> list[RetrievedCase]:
    owns_session = session is None
    session = session or SessionLocal()
    try:
        candidates = _fetch_candidate_pool(session, segment, industry, is_disputed, exclude_invoice_id)
        if not candidates:
            return []

        ids = [c.invoice_id for c in candidates]
        query_vector = embed_query(query_text)

        vector_sims = [_cosine_similarity(c.embedding, query_vector) for c in candidates]
        vector_ranks = _ranks_from_values(ids, vector_sims, descending=True)

        tokenized_corpus = [_tokenize(c.case_text) for c in candidates]
        bm25_scores = list(BM25Okapi(tokenized_corpus).get_scores(_tokenize(query_text)))
        bm25_ranks = _ranks_from_values(ids, bm25_scores, descending=True)

        amount_diffs = [abs(math.log(float(c.amount)) - math.log(query_amount)) for c in candidates]
        amount_ranks = _ranks_from_values(ids, amount_diffs, descending=False)

        fused = _rrf_fuse(vector_ranks, bm25_ranks, amount_ranks)
        top_ids = sorted(fused, key=lambda i: fused[i], reverse=True)[:top_k]

        by_id = {c.invoice_id: c for c in candidates}
        return [
            RetrievedCase(
                invoice_id=i,
                case_text=by_id[i].case_text,
                status=by_id[i].status,
                delay_days=by_id[i].delay_days,
                amount=float(by_id[i].amount),
                segment=by_id[i].segment,
                industry=by_id[i].industry,
                action_types=by_id[i].action_types,
                vector_rank=vector_ranks[i],
                bm25_rank=bm25_ranks[i],
                amount_rank=amount_ranks[i],
                rrf_score=fused[i],
            )
            for i in top_ids
        ]
    finally:
        if owns_session:
            session.close()


def evaluate_archetype_cohesion(sample_size: int = 60, top_k: int = 5, seed: int = SEED) -> dict:
    from app.ml.features import build_feature_table, load_raw_tables

    table = build_feature_table()
    archetypes = load_raw_tables()["customers"][["id", "archetype"]].rename(columns={"id": "customer_id"})
    table = table.merge(archetypes, on="customer_id", how="left")

    invoice_archetype = dict(zip(table["invoice_id"], table["archetype"]))
    population_share = table["archetype"].value_counts(normalize=True).to_dict()

    sample = table.sample(n=min(sample_size, len(table)), random_state=seed)

    session = SessionLocal()
    matches, total, baseline_sum = 0, 0, 0.0
    try:
        for _, row in sample.iterrows():
            query_text = build_query_text(
                amount=row["amount"],
                payment_term_days=row["payment_term_days"],
                segment=row["customer_segment"],
                industry=row["customer_industry"],
                prior_payment_rate=row["prior_payment_rate"] if pd.notna(row["prior_payment_rate"]) else None,
            )
            results = hybrid_retrieve(
                query_text=query_text,
                query_amount=row["amount"],
                segment=row["customer_segment"],
                industry=row["customer_industry"],
                top_k=top_k,
                exclude_invoice_id=row["invoice_id"],
                session=session,
            )
            for result in results:
                total += 1
                if invoice_archetype.get(result.invoice_id) == row["archetype"]:
                    matches += 1
            baseline_sum += population_share.get(row["archetype"], 0.0)
    finally:
        session.close()

    return {
        "observed_cohesion_rate": matches / total if total else 0.0,
        "baseline_rate": baseline_sum / len(sample),
        "n_queries": len(sample),
        "n_retrieved": total,
    }


if __name__ == "__main__":
    result = evaluate_archetype_cohesion(sample_size=200)
    ratio = result["observed_cohesion_rate"] / result["baseline_rate"] if result["baseline_rate"] else float("nan")
    print(f"Archetype-cohesion diagnostic (n={result['n_queries']} queries, {result['n_retrieved']} cases retrieved):")
    print(f"  observed same-archetype rate: {result['observed_cohesion_rate']:.1%}")
    print(f"  random baseline (population share): {result['baseline_rate']:.1%}")
    print(f"  ratio: {ratio:.2f}x")
        