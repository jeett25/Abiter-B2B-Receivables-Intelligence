from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import engine as default_engine
from app.ml.config import RECENCY_WINDOWS_DAYS, WRITTEN_OFF_CONSERVATIVE_DAYS
from app.models import Customer, Invoice, Merchant, Payment, PaymentPromise, RecoveryAction
from app.models.enums import ActionType, InvoiceStatus, PromiseStatus

HISTORICAL_STATUSES = {InvoiceStatus.PAID.value, InvoiceStatus.WRITTEN_OFF.value}

# app/attribution/simulate_outcomes.py's ledger write-back only ever flips a
# formerly-live invoice to PAID when its simulated outcome was recovered=True
# -- never-recovered ones stay OPEN forever. Once Day 5's attribution
# experiment has run, naively filtering training population by status alone
# (HISTORICAL_STATUSES) silently pulls in this outcome-filtered subset as if
# it were organic history, collapsing the most recent time slice to 100%
# positive (survivorship bias, not a real signal). This mirrors
# attribution/DECISIONS.md's already-documented "deterministic given the same
# seed" caveat -- population identity matters -- just for a different mutation.
ATTRIBUTION_SIMULATED_PAYMENT_METHOD = "attribution_simulation"


def organic_historical_mask(invoices: pd.DataFrame, payments: pd.DataFrame) -> pd.Series:
    """HISTORICAL_STATUSES membership, minus any invoice resolved via Day 5's
    attribution write-back rather than organic generation/collection. Use this
    (not a bare status filter) for any TRAINING population -- the row being
    predicted must never be drawn from a population pre-filtered by its own
    outcome. Safe to keep using is_resolved_before()/prior_resolved_invoices()
    unfiltered elsewhere: attribution-simulated resolutions are real facts
    once they've happened, valid as *prior-history context* for a different
    invoice -- only invalid as the labeled training row itself."""
    simulated_ids = set(
        payments.loc[payments["method"] == ATTRIBUTION_SIMULATED_PAYMENT_METHOD, "invoice_id"]
    )
    return invoices["status"].isin(HISTORICAL_STATUSES) & ~invoices["id"].isin(simulated_ids)

RECENT_90D_DAYS, RECENT_180D_DAYS = RECENCY_WINDOWS_DAYS


def _to_naive_timestamp(series: pd.Series) -> pd.Series:
    s = pd.to_datetime(series)
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_localize(None)
    return s


def _enum_values(series: pd.Series) -> pd.Series:
    return series.apply(lambda v: v.value if hasattr(v, "value") else v)


def load_raw_tables(engine: Engine | None = None) -> dict[str, pd.DataFrame]:
    engine = engine or default_engine

    invoices = pd.read_sql(select(Invoice.__table__), engine)
    customers = pd.read_sql(select(Customer.__table__), engine)
    merchants = pd.read_sql(select(Merchant.__table__), engine)
    payments = pd.read_sql(select(Payment.__table__), engine)
    promises = pd.read_sql(select(PaymentPromise.__table__), engine)
    actions = pd.read_sql(select(RecoveryAction.__table__), engine)

    invoices["issue_date"] = _to_naive_timestamp(invoices["issue_date"])
    invoices["due_date"] = _to_naive_timestamp(invoices["due_date"])
    invoices["paid_at"] = _to_naive_timestamp(invoices["paid_at"])
    invoices["amount"] = invoices["amount"].astype(float)
    invoices["status"] = _enum_values(invoices["status"])

    customers["relationship_start_date"] = _to_naive_timestamp(customers["relationship_start_date"])

    payments["payment_date"] = _to_naive_timestamp(payments["payment_date"])
    payments["amount"] = payments["amount"].astype(float)

    promises["status"] = _enum_values(promises["status"])

    actions["timestamp"] = _to_naive_timestamp(actions["timestamp"])
    actions["action_type"] = _enum_values(actions["action_type"])

    return {
        "invoices": invoices,
        "customers": customers,
        "merchants": merchants,
        "payments": payments,
        "promises": promises,
        "actions": actions,
    }


def is_resolved_before(invoice_row: pd.Series, t: pd.Timestamp) -> bool:
    """Whether invoice_row's outcome was already knowable as of cutoff t.

    PAID: known once paid_at < t. WRITTEN_OFF: the generator never persists a
    resolution timestamp for write-offs, so we use the conservative (earliest
    possible) bound of the generator's WRITTEN_OFF_DAYS_RANGE -- due_date +
    WRITTEN_OFF_CONSERVATIVE_DAYS < t -- so this never treats an outcome as
    known before it actually could be.
    """
    if invoice_row["due_date"] >= t:
        return False
    status = invoice_row["status"]
    if status == InvoiceStatus.PAID.value:
        paid_at = invoice_row["paid_at"]
        return pd.notna(paid_at) and paid_at < t
    if status == InvoiceStatus.WRITTEN_OFF.value:
        return invoice_row["due_date"] + pd.Timedelta(days=WRITTEN_OFF_CONSERVATIVE_DAYS) < t
    return False


def prior_resolved_invoices(customer_invoices: pd.DataFrame, exclude_id, cutoff: pd.Timestamp) -> pd.DataFrame:
    candidates = customer_invoices[customer_invoices["id"] != exclude_id]
    if candidates.empty:
        return candidates
    mask = candidates.apply(lambda row: is_resolved_before(row, cutoff), axis=1)
    return candidates[mask]


def prior_issued_invoices(customer_invoices: pd.DataFrame, exclude_id, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Same-customer invoices merely *issued* before cutoff, regardless of
    resolution status. Used only for cadence features (prior_days_since_last_invoice,
    customer_invoice_frequency) -- an invoice's existence and issue_date are known
    the moment issue_date < cutoff, with no outcome required, so restricting this
    to resolved-only would understate cadence for slow-resolving customers."""
    candidates = customer_invoices[customer_invoices["id"] != exclude_id]
    return candidates[candidates["issue_date"] < cutoff]


def rolling_features(
    prior_resolved: pd.DataFrame,
    prior_issued: pd.DataFrame,
    promises: pd.DataFrame,
    actions: pd.DataFrame,
    cutoff: pd.Timestamp,
    relationship_start_date: pd.Timestamp,
) -> dict:
    n = len(prior_resolved)
    feats: dict = {
        "has_prior_history": n > 0,
        "prior_invoice_count": n,
    }

    if n == 0:
        feats.update(
            {
                "prior_paid_count": 0,
                "prior_written_off_count": 0,
                "prior_payment_rate": np.nan,
                "prior_avg_delay_days": np.nan,
                "prior_avg_amount": np.nan,
                "prior_total_amount": 0.0,
                "prior_max_amount": np.nan,
                "prior_promise_count": 0,
                "prior_promise_kept_rate": np.nan,
                "prior_escalation_touches_avg": np.nan,
            }
        )
    else:
        paid = prior_resolved[prior_resolved["status"] == InvoiceStatus.PAID.value]
        written_off = prior_resolved[prior_resolved["status"] == InvoiceStatus.WRITTEN_OFF.value]
        paid_count = len(paid)

        feats["prior_paid_count"] = paid_count
        feats["prior_written_off_count"] = len(written_off)
        feats["prior_payment_rate"] = paid_count / n
        feats["prior_avg_delay_days"] = (
            float((paid["paid_at"] - paid["due_date"]).dt.days.mean()) if paid_count > 0 else np.nan
        )
        feats["prior_avg_amount"] = float(prior_resolved["amount"].mean())
        feats["prior_total_amount"] = float(prior_resolved["amount"].sum())
        feats["prior_max_amount"] = float(prior_resolved["amount"].max())

        invoice_ids = set(prior_resolved["id"])
        prior_promises = promises[promises["invoice_id"].isin(invoice_ids)]
        promise_count = len(prior_promises)
        feats["prior_promise_count"] = promise_count
        feats["prior_promise_kept_rate"] = (
            float((prior_promises["status"] == PromiseStatus.KEPT.value).sum() / promise_count)
            if promise_count > 0
            else np.nan
        )

        prior_actions = actions[actions["invoice_id"].isin(invoice_ids)]
        escalations = prior_actions[prior_actions["action_type"] == ActionType.ESCALATE.value]
        escalations_per_invoice = escalations.groupby("invoice_id").size().reindex(invoice_ids, fill_value=0)
        feats["prior_escalation_touches_avg"] = float(escalations_per_invoice.mean())

    if len(prior_issued) > 0:
        feats["prior_days_since_last_invoice"] = float((cutoff - prior_issued["issue_date"].max()).days)
    else:
        feats["prior_days_since_last_invoice"] = np.nan

    # relationship_start_date is drawn independently of issue_date in the
    # generator, so a cutoff before the recorded relationship start does occur
    # (~14% of historical rows) -- "invoices per month since a relationship
    # that hasn't started yet" is undefined, not a small/near-zero duration,
    # so this is NaN rather than a division blowup against a 1e-6 floor.
    months_active = (cutoff - relationship_start_date).days / 30.0
    feats["customer_invoice_frequency"] = len(prior_issued) / months_active if months_active > 0 else np.nan

    window_90 = prior_resolved[prior_resolved["due_date"] >= cutoff - pd.Timedelta(days=RECENT_90D_DAYS)]
    if len(window_90) > 0:
        paid_90 = window_90[window_90["status"] == InvoiceStatus.PAID.value]
        late_90 = (window_90["status"] == InvoiceStatus.WRITTEN_OFF.value) | (
            (window_90["status"] == InvoiceStatus.PAID.value) & (window_90["paid_at"] > window_90["due_date"])
        )
        feats["recent_90d_payment_rate"] = len(paid_90) / len(window_90)
        feats["recent_90d_late_rate"] = float(late_90.sum() / len(window_90))
    else:
        feats["recent_90d_payment_rate"] = np.nan
        feats["recent_90d_late_rate"] = np.nan

    window_180 = prior_resolved[prior_resolved["due_date"] >= cutoff - pd.Timedelta(days=RECENT_180D_DAYS)]
    if len(window_180) > 0:
        paid_180 = window_180[window_180["status"] == InvoiceStatus.PAID.value]
        feats["recent_180d_payment_rate"] = len(paid_180) / len(window_180)
        feats["recent_180d_avg_delay_days"] = (
            float((paid_180["paid_at"] - paid_180["due_date"]).dt.days.mean()) if len(paid_180) > 0 else np.nan
        )
        window_180_ids = set(window_180["id"])
        window_180_promises = promises[promises["invoice_id"].isin(window_180_ids)]
        feats["recent_180d_ptp_keep_rate"] = (
            float((window_180_promises["status"] == PromiseStatus.KEPT.value).sum() / len(window_180_promises))
            if len(window_180_promises) > 0
            else np.nan
        )
    else:
        feats["recent_180d_payment_rate"] = np.nan
        feats["recent_180d_avg_delay_days"] = np.nan
        feats["recent_180d_ptp_keep_rate"] = np.nan

    return feats


def invoice_static_features(
    invoice_row: pd.Series,
    customer_row: pd.Series,
    merchant_row: pd.Series,
    cutoff: pd.Timestamp,
    payments: pd.DataFrame,
) -> dict:
    """Cutoff-aware: cutoff = due_date for the recovery model, cutoff = T for
    PTP -- outstanding_amount/outstanding_ratio and customer_relationship_days_at_cutoff
    must reflect state as of that specific cutoff, not always due_date."""
    amount = float(invoice_row["amount"])
    invoice_payments = payments[
        (payments["invoice_id"] == invoice_row["id"]) & (payments["payment_date"] <= cutoff)
    ]
    outstanding_amount = amount - float(invoice_payments["amount"].sum())

    # relationship_start_date is drawn independently of issue_date in the
    # generator, so cutoff < relationship_start_date does occur (~14% of
    # historical rows) -- "days since a relationship that hasn't started yet"
    # is undefined, not a meaningful negative duration, so this is NaN rather
    # than a raw negative number a tree split could misread as signal.
    relationship_days = (cutoff - customer_row["relationship_start_date"]).days
    if relationship_days < 0:
        relationship_days = np.nan

    return {
        "amount": amount,
        "amount_log1p": float(np.log1p(amount)),
        "payment_term_days": (invoice_row["due_date"] - invoice_row["issue_date"]).days,
        "issue_month": invoice_row["issue_date"].month,
        "issue_day_of_week": invoice_row["issue_date"].weekday(),
        "merchant_segment": merchant_row["segment"],
        "merchant_industry": merchant_row["industry"],
        "customer_segment": customer_row["segment"],
        "customer_industry": customer_row["industry"],
        "customer_relationship_days_at_cutoff": relationship_days,
        "outstanding_amount": outstanding_amount,
        "outstanding_ratio": outstanding_amount / amount if amount else np.nan,
    }


def build_feature_table(engine: Engine | None = None) -> pd.DataFrame:
    """One row per historical (PAID/WRITTEN_OFF) invoice, cutoff = due_date.
    Never includes archetype/true_recovery_probability/true_promise_keep_probability/
    true_root_cause -- ground truth stays out of the feature table, joined back
    separately by the archetype sanity check only."""
    tables = load_raw_tables(engine)
    invoices = tables["invoices"]
    customers = tables["customers"].set_index("id")
    merchants = tables["merchants"].set_index("id")
    payments = tables["payments"]
    promises = tables["promises"]
    actions = tables["actions"]

    historical = invoices[organic_historical_mask(invoices, payments)]

    rows = []
    for customer_id, group in historical.groupby("customer_id"):
        customer_row = customers.loc[customer_id]
        merchant_row = merchants.loc[customer_row["merchant_id"]]
        relationship_start = customer_row["relationship_start_date"]

        for _, invoice_row in group.iterrows():
            cutoff = invoice_row["due_date"]

            prior_resolved = prior_resolved_invoices(group, invoice_row["id"], cutoff)
            prior_issued = prior_issued_invoices(group, invoice_row["id"], cutoff)

            row = {
                "invoice_id": invoice_row["id"],
                "customer_id": customer_id,
                "merchant_id": customer_row["merchant_id"],
                "invoice_number": invoice_row["invoice_number"],
                "due_date": invoice_row["due_date"],
                "issue_date": invoice_row["issue_date"],
                "status": invoice_row["status"],
                "paid_at": invoice_row["paid_at"],
            }
            row.update(invoice_static_features(invoice_row, customer_row, merchant_row, cutoff, payments))
            row.update(rolling_features(prior_resolved, prior_issued, promises, actions, cutoff, relationship_start))
            rows.append(row)

    return pd.DataFrame(rows)


def build_live_ptp_feature_row(
    invoice_id,
    promised_date,
    source: str,
    cutoff: pd.Timestamp,
    engine: Engine | None = None,
    tables: dict | None = None,
) -> dict:
    """One PTP feature row for a single live promise (Day 4, Subtask 7) --
    mirrors app.ml.labels.build_ptp_table()'s per-row construction
    (invoice_static_features + rolling_features at cutoff=T), for one
    just-created live promise instead of the full historical,
    terminal-status population. Uses the same widened live customer-grouping
    build_live_feature_table() below already established and adversarially
    tested (full invoice history, not HISTORICAL_STATUSES only -- a live
    invoice's customer can have other live siblings that legitimately count
    toward cadence/prior-history features)."""
    tables = tables or load_raw_tables(engine)
    invoices = tables["invoices"]
    customers = tables["customers"].set_index("id")
    merchants = tables["merchants"].set_index("id")
    payments = tables["payments"]
    promises = tables["promises"]
    actions = tables["actions"]

    invoice_row = invoices[invoices["id"] == invoice_id].iloc[0]
    customer_id = invoice_row["customer_id"]
    customer_row = customers.loc[customer_id]
    merchant_row = merchants.loc[customer_row["merchant_id"]]
    group = invoices[invoices["customer_id"] == customer_id]

    prior_resolved = prior_resolved_invoices(group, invoice_id, cutoff)
    prior_issued = prior_issued_invoices(group, invoice_id, cutoff)

    row = {
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "merchant_id": customer_row["merchant_id"],
        "T": cutoff,
        "promised_date": promised_date,
        "source": source,
    }
    row.update(invoice_static_features(invoice_row, customer_row, merchant_row, cutoff, payments))
    row.update(
        rolling_features(prior_resolved, prior_issued, promises, actions, cutoff, customer_row["relationship_start_date"])
    )
    return row


def build_live_feature_table(engine: Engine | None = None) -> pd.DataFrame:
    tables = load_raw_tables(engine)
    invoices = tables["invoices"]
    customers = tables["customers"].set_index("id")
    merchants = tables["merchants"].set_index("id")
    payments = tables["payments"]
    promises = tables["promises"]
    actions = tables["actions"]

    rows = []
    for customer_id, group in invoices.groupby("customer_id"):
        live = group[group["status"] == InvoiceStatus.OPEN.value]
        if live.empty:
            continue

        customer_row = customers.loc[customer_id]
        merchant_row = merchants.loc[customer_row["merchant_id"]]
        relationship_start = customer_row["relationship_start_date"]

        for _, invoice_row in live.iterrows():
            cutoff = invoice_row["due_date"]

            prior_resolved = prior_resolved_invoices(group, invoice_row["id"], cutoff)
            prior_issued = prior_issued_invoices(group, invoice_row["id"], cutoff)

            row = {
                "invoice_id": invoice_row["id"],
                "customer_id": customer_id,
                "merchant_id": customer_row["merchant_id"],
                "invoice_number": invoice_row["invoice_number"],
                "due_date": invoice_row["due_date"],
                "issue_date": invoice_row["issue_date"],
                "status": invoice_row["status"],
            }
            row.update(invoice_static_features(invoice_row, customer_row, merchant_row, cutoff, payments))
            row.update(rolling_features(prior_resolved, prior_issued, promises, actions, cutoff, relationship_start))
            rows.append(row)

    return pd.DataFrame(rows)
