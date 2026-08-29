"""app/retrieval/hybrid_search.py tests.

Ranking/cascade/text-builder tests are pure (no DB). The retrieval tests are
integration tests against the real dev DB's populated case_embeddings table.
"""
from app.models import CaseEmbedding
from app.retrieval.hybrid_search import (
    RRF_K,
    _candidate_filter_levels,
    _fetch_candidate_pool,
    _ranks_from_values,
    _rrf_fuse,
    _tokenize,
    build_query_text,
    evaluate_archetype_cohesion,
    hybrid_retrieve,
)


def test_build_query_text_omits_actions_and_outcome():
    result = build_query_text(
        amount=42000.0,
        payment_term_days=60,
        segment="SMB",
        industry="Retail",
        prior_payment_rate=0.8,
        days_overdue=15,
    )
    assert "42,000" in result
    assert "80%" in result
    assert "15 days overdue" in result
    assert "Actions taken" not in result
    assert "Outcome" not in result


def test_build_query_text_no_prior_history():
    result = build_query_text(
        amount=10000.0, payment_term_days=30, segment="enterprise", industry="saas", prior_payment_rate=None
    )
    assert "no prior payment history" in result


def test_tokenize_lowercases_and_strips_punctuation():
    assert _tokenize("SMB segment, Retail industry customer.") == ["smb", "segment", "retail", "industry", "customer"]


def test_ranks_from_values_descending():
    ranks = _ranks_from_values(["a", "b", "c"], [0.1, 0.9, 0.5], descending=True)
    assert ranks == {"b": 1, "c": 2, "a": 3}


def test_ranks_from_values_ascending():
    ranks = _ranks_from_values(["a", "b", "c"], [0.1, 0.9, 0.5], descending=False)
    assert ranks == {"a": 1, "c": 2, "b": 3}


def test_rrf_fuse_rewards_best_overall_combination_of_ranks():
    # a: (1,1,2) strictly dominates b: (2,3,1) and c: (3,2,3) -- hand-verified:
    # a=1/61+1/61+1/62=0.048916, b=1/62+1/63+1/61=0.048395, c=1/63+1/62+1/63=0.047875
    r1 = {"a": 1, "b": 2, "c": 3}
    r2 = {"a": 1, "b": 3, "c": 2}
    r3 = {"a": 2, "b": 1, "c": 3}
    fused = _rrf_fuse(r1, r2, r3, k=RRF_K)
    assert max(fused, key=fused.get) == "a"
    assert fused["a"] > fused["b"] > fused["c"]


def test_candidate_filter_levels_non_disputed_cascade_ends_unfiltered():
    levels = _candidate_filter_levels("SMB", "Retail", is_disputed=False)
    assert len(levels) == 3
    assert levels[-1] == []
    assert [len(level) for level in levels] == [2, 1, 0]


def test_candidate_filter_levels_disputed_cascade_drops_industry_then_segment_then_dispute():
    levels = _candidate_filter_levels("SMB", "Retail", is_disputed=True)
    assert len(levels) == 6
    assert levels[-1] == []
    assert [len(level) for level in levels] == [3, 2, 1, 2, 1, 0]


def test_fetch_candidate_pool_never_empty_for_a_real_segment_industry(db_session):
    sample = db_session.query(CaseEmbedding).first()
    rows = _fetch_candidate_pool(db_session, sample.segment, sample.industry, is_disputed=False, exclude_invoice_id=None)
    assert len(rows) > 0


def test_fetch_candidate_pool_respects_exclude_invoice_id(db_session):
    sample = db_session.query(CaseEmbedding).first()
    rows = _fetch_candidate_pool(
        db_session, sample.segment, sample.industry, is_disputed=False, exclude_invoice_id=sample.invoice_id
    )
    assert sample.invoice_id not in [r.invoice_id for r in rows]


def test_fetch_candidate_pool_disputed_never_empty(db_session):
    sample = db_session.query(CaseEmbedding).first()
    rows = _fetch_candidate_pool(db_session, sample.segment, sample.industry, is_disputed=True, exclude_invoice_id=None)
    assert len(rows) > 0


def test_self_retrieval_returns_exact_match_at_rank_one(db_session):
    # All three sub-rankings independently favor an identical-text,
    # identical-amount self-match (cosine similarity ~1.0, maximal BM25
    # self-score, zero amount-log-difference), so this should deterministically
    # land at rank 1 -- a weaker "somewhere in top-5" check would miss a real
    # fusion bug (e.g. a rank tie-break or sign error) that this catches.
    sample = db_session.query(CaseEmbedding).first()
    results = hybrid_retrieve(
        query_text=sample.case_text,
        query_amount=float(sample.amount),
        segment=sample.segment,
        industry=sample.industry,
        top_k=5,
        session=db_session,
    )
    assert results[0].invoice_id == sample.invoice_id
    assert results[0].vector_rank == 1
    assert results[0].amount_rank == 1


def test_hybrid_retrieve_excludes_query_invoice_when_asked(db_session):
    sample = db_session.query(CaseEmbedding).first()
    results = hybrid_retrieve(
        query_text=sample.case_text,
        query_amount=float(sample.amount),
        segment=sample.segment,
        industry=sample.industry,
        top_k=5,
        exclude_invoice_id=sample.invoice_id,
        session=db_session,
    )
    assert sample.invoice_id not in [r.invoice_id for r in results]


def test_archetype_cohesion_beats_random_baseline():
    # Slow: builds the full Day-2 feature table (same cost as
    # build_case_corpus.py's population step) plus `sample_size` retrieval
    # calls. Kept small enough here to stay reasonable; the __main__ block
    # runs a larger sample for a more robust standalone report.
    result = evaluate_archetype_cohesion(sample_size=60, top_k=5)
    assert result["n_retrieved"] > 0
    assert result["observed_cohesion_rate"] > result["baseline_rate"] * 1.3
