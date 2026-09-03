"""app/retrieval/build_case_corpus.py tests.

Text-synthesis tests are pure (no DB, no fastembed). The population/embedding
tests are integration tests against the real dev DB and are skipped until
`python -m app.retrieval.build_case_corpus` has actually been run -- fastembed
requires a one-time model download, handled by the user, not this suite.
"""
import pandas as pd
import pytest
from sqlalchemy import text

from app.core.db import engine
from app.models.case_embedding import EMBEDDING_DIM, CaseEmbedding
from app.models.enums import InvoiceStatus
from app.retrieval.build_case_corpus import _ordered_distinct_actions, build_case_text


def test_build_case_text_paid_late_includes_delay_and_actions():
    result = build_case_text(
        amount=42000.0,
        payment_term_days=60,
        segment="SMB",
        industry="retail",
        prior_payment_rate=0.8,
        action_types=["email", "whatsapp", "escalate"],
        status=InvoiceStatus.PAID.value,
        delay_days=38,
    )
    assert "42,000" in result
    assert "60-day" in result
    assert "80%" in result
    assert "email, whatsapp, escalate" in result
    assert "paid 38 days late" in result


def test_build_case_text_paid_on_time_when_no_delay():
    result = build_case_text(
        amount=10000.0,
        payment_term_days=30,
        segment="enterprise",
        industry="saas",
        prior_payment_rate=1.0,
        action_types=[],
        status=InvoiceStatus.PAID.value,
        delay_days=0,
    )
    assert "paid on time" in result
    assert "no follow-up action taken" in result


def test_build_case_text_written_off_states_never_recovered():
    result = build_case_text(
        amount=15000.0,
        payment_term_days=90,
        segment="SMB",
        industry="manufacturing",
        prior_payment_rate=None,
        action_types=["email", "escalate"],
        status=InvoiceStatus.WRITTEN_OFF.value,
        delay_days=None,
    )
    assert "written off, never recovered" in result
    assert "no prior payment history" in result


def test_ordered_distinct_actions_preserves_first_occurrence_order():
    actions = pd.DataFrame(
        [
            {"invoice_id": "inv-1", "action_type": "email", "timestamp": pd.Timestamp("2024-01-01")},
            {"invoice_id": "inv-1", "action_type": "whatsapp", "timestamp": pd.Timestamp("2024-01-05")},
            {"invoice_id": "inv-1", "action_type": "email", "timestamp": pd.Timestamp("2024-01-10")},  # dup, ignored
            {"invoice_id": "inv-2", "action_type": "escalate", "timestamp": pd.Timestamp("2024-01-02")},
        ]
    )
    result = _ordered_distinct_actions(actions)
    assert result["inv-1"] == ["email", "whatsapp"]
    assert result["inv-2"] == ["escalate"]


def test_case_embeddings_table_exists_with_correct_vector_dimension():
    assert EMBEDDING_DIM == 384
    with engine.connect() as conn:
        dim = conn.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'case_embeddings'::regclass AND attname = 'embedding'"
            )
        ).scalar()
    assert dim == EMBEDDING_DIM


def test_populated_rows_have_full_dimension_embeddings_and_match_historical_count(db_session):
    if db_session.query(CaseEmbedding).count() == 0:
        pytest.skip("case_embeddings not populated yet -- run `python -m app.retrieval.build_case_corpus` first")

    # Fixed at 9,000 -- the size of the ORIGINAL Day-1 historical pool this
    # corpus was built against once, in Day 3. NOT recomputed from a live
    # HISTORICAL_STATUSES count: Day 5's attribution write-back moved
    # hundreds of LIVE invoices to PAID too, which would inflate that count
    # without those invoices ever being part of the corpus-building pass.
    # See docs/attribution-DECISIONS.md.
    EXPECTED_HISTORICAL_CORPUS_SIZE = 9_000

    count = db_session.query(CaseEmbedding).count()
    assert count == EXPECTED_HISTORICAL_CORPUS_SIZE

    sample = db_session.query(CaseEmbedding).first()
    assert len(sample.embedding) == EMBEDDING_DIM
    assert sample.case_text
