"""app/ml/features.py tests: point-in-time cutoff logic and leakage guards
(pure, no DB) plus a couple of DB-backed invariants the feature table relies on."""
import math

import pandas as pd
from sqlalchemy import func, select

from app.core.db import engine
from app.ml.features import (
    build_feature_table,
    invoice_static_features,
    is_resolved_before,
    prior_issued_invoices,
    prior_resolved_invoices,
    rolling_features,
)
from app.models import Invoice
from app.models.enums import InvoiceStatus


def _row(**kwargs) -> pd.Series:
    return pd.Series(kwargs)


def test_is_resolved_before_excludes_write_off_inside_150_day_window():
    row = _row(due_date=pd.Timestamp("2024-01-01"), status="written_off", paid_at=pd.NaT)
    cutoff = pd.Timestamp("2024-01-01") + pd.Timedelta(days=100)
    assert is_resolved_before(row, cutoff) is False


def test_is_resolved_before_includes_write_off_past_150_day_window():
    row = _row(due_date=pd.Timestamp("2024-01-01"), status="written_off", paid_at=pd.NaT)
    cutoff = pd.Timestamp("2024-01-01") + pd.Timedelta(days=151)
    assert is_resolved_before(row, cutoff) is True


def test_is_resolved_before_paid_boundary_cases():
    row = _row(due_date=pd.Timestamp("2024-01-01"), status="paid", paid_at=pd.Timestamp("2024-01-10"))

    # cutoff strictly before paid_at -> not yet resolved
    assert is_resolved_before(row, pd.Timestamp("2024-01-05")) is False
    # cutoff exactly equal to paid_at -> not resolved (strict <, not <=)
    assert is_resolved_before(row, pd.Timestamp("2024-01-10")) is False
    # cutoff one day after paid_at -> resolved
    assert is_resolved_before(row, pd.Timestamp("2024-01-11")) is True
    # cutoff at the invoice's own due_date -> never resolved regardless of paid_at
    assert is_resolved_before(row, pd.Timestamp("2024-01-01")) is False


def test_rolling_features_never_leak_own_invoice_promise_or_action_data():
    """Invoice 2 has its own promise/action rows generated as part of its own
    resolution. Computing invoice 2's own rolling features at its own due_date
    must never count those -- only invoice 1's legitimately-prior history."""
    invoices = pd.DataFrame(
        [
            {
                "id": "inv-1",
                "customer_id": "cust-1",
                "due_date": pd.Timestamp("2024-02-01"),
                "issue_date": pd.Timestamp("2024-01-05"),
                "status": "paid",
                "paid_at": pd.Timestamp("2024-02-03"),
                "amount": 10000.0,
            },
            {
                "id": "inv-2",
                "customer_id": "cust-1",
                "due_date": pd.Timestamp("2024-06-01"),
                "issue_date": pd.Timestamp("2024-05-01"),
                "status": "paid",
                "paid_at": pd.Timestamp("2024-06-10"),
                "amount": 20000.0,
            },
        ]
    )
    promises = pd.DataFrame(
        [
            {"invoice_id": "inv-1", "status": "kept"},
            {"invoice_id": "inv-2", "status": "kept"},  # invoice 2's own promise
        ]
    )
    actions = pd.DataFrame(
        [
            {"invoice_id": "inv-1", "action_type": "escalate", "timestamp": pd.Timestamp("2024-01-20")},
            {"invoice_id": "inv-2", "action_type": "escalate", "timestamp": pd.Timestamp("2024-05-15")},  # invoice 2's own action
        ]
    )

    cutoff = pd.Timestamp("2024-06-01")  # invoice 2's own due_date
    prior_resolved = prior_resolved_invoices(invoices, "inv-2", cutoff)
    prior_issued = prior_issued_invoices(invoices, "inv-2", cutoff)

    assert list(prior_resolved["id"]) == ["inv-1"]

    feats = rolling_features(prior_resolved, prior_issued, promises, actions, cutoff, pd.Timestamp("2023-01-01"))
    assert feats["prior_invoice_count"] == 1
    assert feats["prior_promise_count"] == 1  # only invoice 1's promise, never invoice 2's own
    assert feats["prior_escalation_touches_avg"] == 1.0  # only invoice 1's escalation


def test_customers_first_invoice_gets_nan_not_zero_on_rate_features():
    invoices = pd.DataFrame(
        [
            {
                "id": "inv-1",
                "customer_id": "cust-1",
                "due_date": pd.Timestamp("2024-02-01"),
                "issue_date": pd.Timestamp("2024-01-05"),
                "status": "paid",
                "paid_at": pd.Timestamp("2024-02-03"),
                "amount": 10000.0,
            }
        ]
    )
    promises = pd.DataFrame(columns=["invoice_id", "status"])
    actions = pd.DataFrame(columns=["invoice_id", "action_type", "timestamp"])

    cutoff = pd.Timestamp("2024-02-01")
    prior_resolved = prior_resolved_invoices(invoices, "inv-1", cutoff)
    prior_issued = prior_issued_invoices(invoices, "inv-1", cutoff)

    feats = rolling_features(prior_resolved, prior_issued, promises, actions, cutoff, pd.Timestamp("2023-01-01"))

    assert feats["has_prior_history"] is False
    assert feats["prior_invoice_count"] == 0
    assert math.isnan(feats["prior_payment_rate"])
    assert math.isnan(feats["prior_avg_delay_days"])
    assert math.isnan(feats["prior_days_since_last_invoice"])
    assert feats["customer_invoice_frequency"] == 0.0  # valid zero, not NaN -- denominator doesn't need invoice history


def test_cutoff_before_relationship_start_date_gives_nan_not_a_blowup():
    """Regression guard for a real bug found via a persist.py spot-check:
    relationship_start_date is drawn independently of issue_date in the
    generator, so cutoff < relationship_start_date genuinely occurs (~14% of
    historical rows). customer_invoice_frequency used to divide by a 1e-6
    floor in that case, exploding to values like 3,000,000 instead of a
    sane invoices-per-month number -- both features must be NaN instead."""
    invoices = pd.DataFrame(
        [
            {
                "id": "inv-1", "customer_id": "cust-1",
                "due_date": pd.Timestamp("2024-01-01"), "issue_date": pd.Timestamp("2023-12-01"),
                "status": "paid", "paid_at": pd.Timestamp("2024-01-10"), "amount": 10000.0,
            },
            {
                "id": "inv-2", "customer_id": "cust-1",
                "due_date": pd.Timestamp("2024-02-01"), "issue_date": pd.Timestamp("2024-01-15"),
                "status": "paid", "paid_at": pd.Timestamp("2024-02-10"), "amount": 12000.0,
            },
        ]
    )
    customer_row = pd.Series(
        {"segment": "SMB", "industry": "retail", "relationship_start_date": pd.Timestamp("2024-06-01")}
    )
    merchant_row = pd.Series({"segment": "enterprise", "industry": "saas"})
    payments = pd.DataFrame(columns=["invoice_id", "amount", "payment_date"])
    promises = pd.DataFrame(columns=["invoice_id", "status"])
    actions = pd.DataFrame(columns=["invoice_id", "action_type", "timestamp"])

    cutoff = pd.Timestamp("2024-02-01")  # before relationship_start_date (2024-06-01)
    prior_resolved = prior_resolved_invoices(invoices, "inv-2", cutoff)
    prior_issued = prior_issued_invoices(invoices, "inv-2", cutoff)
    assert len(prior_issued) == 1  # inv-1 -- confirms the denominator-vs-numerator setup that caused the blowup

    static = invoice_static_features(invoices.iloc[1], customer_row, merchant_row, cutoff, payments)
    rolling = rolling_features(prior_resolved, prior_issued, promises, actions, cutoff, customer_row["relationship_start_date"])

    assert math.isnan(static["customer_relationship_days_at_cutoff"])
    assert math.isnan(rolling["customer_invoice_frequency"])


def test_no_historical_invoice_left_in_disputed_or_promised_status(db_session):
    """The ml layer only ever handles PAID/WRITTEN_OFF as 'historical, resolved'.
    This is a generator-invariant regression guard: if DISPUTED/PROMISED ever
    starts being used, build_feature_table's HISTORICAL_STATUSES filter would
    silently drop those invoices instead of erroring."""
    count = db_session.execute(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.status.in_([InvoiceStatus.DISPUTED, InvoiceStatus.PROMISED]))
    ).scalar_one()
    assert count == 0


def test_build_feature_table_row_count_matches_historical_invoice_count(db_session):
    historical_count = db_session.execute(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.status.in_([InvoiceStatus.PAID, InvoiceStatus.WRITTEN_OFF]))
    ).scalar_one()

    table = build_feature_table(engine)
    assert len(table) == historical_count


def _feature_vector_for(invoices, promises, actions, payments, target_id, cutoff, customer_row, merchant_row) -> dict:
    prior_resolved = prior_resolved_invoices(invoices, target_id, cutoff)
    prior_issued = prior_issued_invoices(invoices, target_id, cutoff)
    target_row = invoices.loc[invoices["id"] == target_id].iloc[0]
    static = invoice_static_features(target_row, customer_row, merchant_row, cutoff, payments)
    rolling = rolling_features(prior_resolved, prior_issued, promises, actions, cutoff, customer_row["relationship_start_date"])
    return {**static, **rolling}


def _dicts_equal_nan_safe(a: dict, b: dict) -> bool:
    if a.keys() != b.keys():
        return False
    for key in a:
        va, vb = a[key], b[key]
        if isinstance(va, float) and isinstance(vb, float) and math.isnan(va) and math.isnan(vb):
            continue
        if va != vb:
            return False
    return True


def test_recovery_features_unaffected_by_future_events():
    """The most direct proof of the point-in-time boundary: compute a feature
    vector, insert a new invoice (with its own promise/action/payment) dated
    after the cutoff, recompute, and assert byte-identical -- not just an
    assertion that happens to hold on today's fixed dataset."""
    customer_row = pd.Series({"segment": "SMB", "industry": "retail", "relationship_start_date": pd.Timestamp("2023-01-01")})
    merchant_row = pd.Series({"segment": "enterprise", "industry": "saas"})

    invoices_before = pd.DataFrame(
        [
            {"id": "inv-1", "customer_id": "cust-1", "due_date": pd.Timestamp("2024-01-01"), "issue_date": pd.Timestamp("2023-12-01"),
             "status": "paid", "paid_at": pd.Timestamp("2024-01-10"), "amount": 10000.0},
            {"id": "inv-2", "customer_id": "cust-1", "due_date": pd.Timestamp("2024-03-01"), "issue_date": pd.Timestamp("2024-02-01"),
             "status": "paid", "paid_at": pd.Timestamp("2024-03-20"), "amount": 15000.0},
        ]
    )
    promises_before = pd.DataFrame(columns=["invoice_id", "status"])
    actions_before = pd.DataFrame(columns=["invoice_id", "action_type", "timestamp"])
    payments_before = pd.DataFrame(columns=["invoice_id", "amount", "payment_date"])

    cutoff = pd.Timestamp("2024-03-01")  # inv-2's own due_date
    before = _feature_vector_for(invoices_before, promises_before, actions_before, payments_before, "inv-2", cutoff, customer_row, merchant_row)

    # Insert a brand-new invoice (+ its own promise/action/payment), all dated after cutoff
    invoices_after = pd.concat(
        [
            invoices_before,
            pd.DataFrame(
                [{"id": "inv-3", "customer_id": "cust-1", "due_date": pd.Timestamp("2024-05-01"), "issue_date": pd.Timestamp("2024-04-01"),
                  "status": "paid", "paid_at": pd.Timestamp("2024-05-15"), "amount": 20000.0}]
            ),
        ],
        ignore_index=True,
    )
    promises_after = pd.DataFrame([{"invoice_id": "inv-3", "status": "kept"}])
    actions_after = pd.DataFrame([{"invoice_id": "inv-3", "action_type": "escalate", "timestamp": pd.Timestamp("2024-04-10")}])
    payments_after = pd.DataFrame([{"invoice_id": "inv-3", "amount": 20000.0, "payment_date": pd.Timestamp("2024-05-15")}])

    after = _feature_vector_for(invoices_after, promises_after, actions_after, payments_after, "inv-2", cutoff, customer_row, merchant_row)

    assert _dicts_equal_nan_safe(before, after)


def test_ptp_features_unaffected_by_future_events():
    """Same proof, re-anchored to T (the PTP cutoff) instead of due_date --
    confirms the promise-level path is equally leak-proof, not just the
    recovery path."""
    customer_row = pd.Series({"segment": "SMB", "industry": "retail", "relationship_start_date": pd.Timestamp("2023-01-01")})
    merchant_row = pd.Series({"segment": "enterprise", "industry": "saas"})

    invoices_before = pd.DataFrame(
        [
            {"id": "inv-1", "customer_id": "cust-1", "due_date": pd.Timestamp("2024-01-01"), "issue_date": pd.Timestamp("2023-12-01"),
             "status": "paid", "paid_at": pd.Timestamp("2024-01-10"), "amount": 10000.0},
            {"id": "inv-2", "customer_id": "cust-1", "due_date": pd.Timestamp("2024-03-01"), "issue_date": pd.Timestamp("2024-02-01"),
             "status": "paid", "paid_at": pd.Timestamp("2024-03-20"), "amount": 15000.0},
        ]
    )
    promises_before = pd.DataFrame([{"invoice_id": "inv-2", "status": "kept"}])
    actions_before = pd.DataFrame([{"invoice_id": "inv-2", "action_type": "email", "timestamp": pd.Timestamp("2024-03-05")}])
    payments_before = pd.DataFrame(columns=["invoice_id", "amount", "payment_date"])

    T = pd.Timestamp("2024-03-05")  # inv-2's own promise cutoff (last action for inv-2)
    before = _feature_vector_for(invoices_before, promises_before, actions_before, payments_before, "inv-2", T, customer_row, merchant_row)

    invoices_after = pd.concat(
        [
            invoices_before,
            pd.DataFrame(
                [{"id": "inv-3", "customer_id": "cust-1", "due_date": pd.Timestamp("2024-05-01"), "issue_date": pd.Timestamp("2024-04-01"),
                  "status": "written_off", "paid_at": pd.NaT, "amount": 5000.0}]
            ),
        ],
        ignore_index=True,
    )
    promises_after = pd.concat([promises_before, pd.DataFrame([{"invoice_id": "inv-3", "status": "broken"}])], ignore_index=True)
    actions_after = pd.concat(
        [actions_before, pd.DataFrame([{"invoice_id": "inv-3", "action_type": "voice", "timestamp": pd.Timestamp("2024-04-20")}])],
        ignore_index=True,
    )

    after = _feature_vector_for(invoices_after, promises_after, actions_after, payments_before, "inv-2", T, customer_row, merchant_row)

    assert _dicts_equal_nan_safe(before, after)
