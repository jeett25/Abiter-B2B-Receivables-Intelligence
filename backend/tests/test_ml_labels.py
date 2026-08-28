"""app/ml/labels.py tests: PTP table terminal-status/no-leakage filtering (pure)
and the T-reconstruction correctness proof (DB-backed, against real data)."""
import pandas as pd

from app.core.db import engine
from app.ml.features import load_raw_tables
from app.ml.labels import build_ptp_table, compute_promise_cutoffs
from app.models.enums import PromiseStatus


def test_build_ptp_table_excludes_non_terminal_promises_and_confidence_score():
    invoices = pd.DataFrame(
        [
            {
                "id": "inv-1",
                "customer_id": "cust-1",
                "merchant_id": "merch-1",
                "due_date": pd.Timestamp("2024-01-01"),
                "issue_date": pd.Timestamp("2023-12-01"),
                "status": "paid",
                "paid_at": pd.Timestamp("2024-01-20"),
                "amount": 10000.0,
                "invoice_number": "INV-1",
            },
            {
                "id": "inv-2",
                "customer_id": "cust-1",
                "merchant_id": "merch-1",
                "due_date": pd.Timestamp("2024-03-01"),
                "issue_date": pd.Timestamp("2024-02-01"),
                "status": "paid",
                "paid_at": pd.Timestamp("2024-03-25"),
                "amount": 12000.0,
                "invoice_number": "INV-2",
            },
        ]
    )
    promises = pd.DataFrame(
        [
            {
                "id": "promise-1",
                "invoice_id": "inv-1",
                "status": "kept",
                "promised_date": pd.Timestamp("2024-01-15"),
                "confidence_score": 0.9,
                "source": "email",
            },
            {
                "id": "promise-2",
                "invoice_id": "inv-2",
                "status": "open",  # non-terminal -- must be excluded
                "promised_date": pd.Timestamp("2024-03-10"),
                "confidence_score": 0.5,
                "source": "whatsapp",
            },
        ]
    )
    actions = pd.DataFrame(
        [
            {"invoice_id": "inv-1", "action_type": "email", "timestamp": pd.Timestamp("2024-01-10")},
            {"invoice_id": "inv-2", "action_type": "whatsapp", "timestamp": pd.Timestamp("2024-03-05")},
        ]
    )

    import app.ml.labels as labels_module

    original_load = labels_module.load_raw_tables
    try:
        labels_module.load_raw_tables = lambda engine=None: {
            "invoices": invoices,
            "customers": pd.DataFrame(
                [{"id": "cust-1", "merchant_id": "merch-1", "segment": "SMB", "industry": "retail",
                  "relationship_start_date": pd.Timestamp("2023-01-01")}]
            ),
            "merchants": pd.DataFrame([{"id": "merch-1", "segment": "enterprise", "industry": "saas"}]),
            "payments": pd.DataFrame(columns=["invoice_id", "amount", "payment_date"]),
            "promises": promises,
            "actions": actions,
        }
        table = labels_module.build_ptp_table()
    finally:
        labels_module.load_raw_tables = original_load

    assert list(table["promise_id"]) == ["promise-1"]  # promise-2 (open) excluded
    assert "confidence_score" not in table.columns


def test_t_reconstruction_matches_max_action_timestamp_per_promise(db_session):
    tables = load_raw_tables(engine)
    actions = tables["actions"]
    promises = tables["promises"]
    promises = promises[promises["status"].isin([PromiseStatus.KEPT.value, PromiseStatus.BROKEN.value])]

    cutoffs, fallback_count = compute_promise_cutoffs(promises, actions)
    assert fallback_count == 0

    # Independently recomputed, per-promise (keyed by index, which corresponds
    # 1:1 to a promise row) -- not just aggregate/value-count equality.
    last_action_per_invoice = actions.groupby("invoice_id")["timestamp"].max()
    expected = promises["invoice_id"].map(last_action_per_invoice)

    assert cutoffs.equals(expected)
    assert (cutoffs <= promises["promised_date"]).all()
