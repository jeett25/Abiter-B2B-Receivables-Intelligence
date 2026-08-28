from __future__ import annotations

import json
import math
from datetime import timezone
from pathlib import Path

import joblib
import pandas as pd

from app.core.db import SessionLocal
from app.models import FeatureSnapshot

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

# Number of rows to snapshot per model when the demo/CLI path runs. Day 2's
# job is proving the write path works end-to-end (schema compatibility, JSONB
# structure, session pattern), not backfilling the full historical set --
# real population of this table is Day 4/5's live-pipeline concern, operating
# on the 900 live invoices, not this training data.
DEMO_SNAPSHOT_LIMIT = 20

PAYMENT_FEATURE_KEYS = [
    "amount", "amount_log1p", "payment_term_days", "outstanding_amount", "outstanding_ratio",
    "prior_avg_amount", "prior_total_amount", "prior_max_amount", "prior_payment_rate",
    "prior_paid_count", "prior_written_off_count", "prior_avg_delay_days",
    "recent_90d_payment_rate", "recent_90d_late_rate", "recent_180d_payment_rate", "recent_180d_avg_delay_days",
]
PROMISE_FEATURE_KEYS = ["prior_promise_count", "prior_promise_kept_rate", "recent_180d_ptp_keep_rate", "source"]
BEHAVIOR_FEATURE_KEYS = [
    "issue_month", "issue_day_of_week", "merchant_segment", "merchant_industry",
    "customer_segment", "customer_industry", "customer_relationship_days_at_cutoff",
    "has_prior_history", "prior_invoice_count", "prior_escalation_touches_avg",
    "prior_days_since_last_invoice", "customer_invoice_frequency",
]


def save_model(model, name: str) -> Path:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    path = ARTIFACTS_DIR / f"{name}.joblib"
    joblib.dump(model, path)
    return path


def load_model(name: str):
    return joblib.load(ARTIFACTS_DIR / f"{name}.joblib")


def save_metrics(metrics: dict, name: str) -> Path:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    path = ARTIFACTS_DIR / f"{name}_metrics.json"
    path.write_text(json.dumps(metrics, indent=2, default=str))
    return path


def _to_jsonable(value):
    """numpy scalars and NaN aren't valid JSONB payloads as-is -- convert to
    native Python, and NaN/NaT to None (JSON has no NaN)."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _bucket_features(row: pd.Series, keys: list[str]) -> dict:
    return {key: _to_jsonable(row[key]) for key in keys if key in row.index}


def write_feature_snapshots(
    table: pd.DataFrame, model_version: str, timestamp_col: str, limit: int | None = DEMO_SNAPSHOT_LIMIT
) -> int:
    """One FeatureSnapshot row per table row (payment/promise/behavior JSONB
    buckets), same SessionLocal()/try-finally pattern as generator.py.
    Pass limit=None to write every row (not the default -- see DEMO_SNAPSHOT_LIMIT)."""
    rows = table if limit is None else table.head(limit)

    session = SessionLocal()
    try:
        snapshots = []
        for _, row in rows.iterrows():
            ts = row[timestamp_col]
            if ts.tzinfo is None:
                ts = ts.tz_localize(timezone.utc)
            snapshots.append(
                FeatureSnapshot(
                    merchant_id=row["merchant_id"],
                    customer_id=row["customer_id"],
                    invoice_id=row["invoice_id"],
                    feature_timestamp=ts,
                    payment_features=_bucket_features(row, PAYMENT_FEATURE_KEYS),
                    promise_features=_bucket_features(row, PROMISE_FEATURE_KEYS),
                    behavior_features=_bucket_features(row, BEHAVIOR_FEATURE_KEYS),
                    model_version=model_version,
                )
            )
        session.add_all(snapshots)
        session.commit()
        return len(snapshots)
    finally:
        session.close()


if __name__ == "__main__":
    from app.ml.train_ptp import (
        calibrate_model as calibrate_ptp,
        load_ptp_table,
    )
    from app.ml.train_ptp import (
        train_xgb_classifier as train_ptp_model,
    )
    from app.ml.train_recovery import (
        calibrate_model as calibrate_recovery,
    )
    from app.ml.train_recovery import (
        load_labeled_recovery_table,
    )
    from app.ml.train_recovery import (
        train_xgb_classifier as train_recovery_model,
    )
    from app.ml.evaluate import classification_metrics
    from app.ml.splits import split_ptp_table, split_recovery_table
    from app.ml import train_recovery as recovery_module
    from app.ml import train_ptp as ptp_module

    RECOVERY_MODEL_VERSION = "recovery_xgb_isotonic_v1"
    PTP_MODEL_VERSION = "ptp_xgb_platt_v1"

    print("Training + persisting recovery model...")
    recovery_table = load_labeled_recovery_table()
    recovery_splits = split_recovery_table(recovery_table)
    recovery_model = train_recovery_model(recovery_splits["fit"], recovery_splits["validation"])
    recovery_calibrator = calibrate_recovery(recovery_model, recovery_splits["calibration"])

    recovery_proba = recovery_module.calibrated_predict_proba(recovery_model, recovery_calibrator, recovery_splits["test"])
    recovery_metrics = classification_metrics(recovery_splits["test"][recovery_module.LABEL_COLUMN], recovery_proba)

    model_path = save_model(recovery_model, "recovery_model")
    calibrator_path = save_model(recovery_calibrator, "recovery_calibrator")
    metrics_path = save_metrics(recovery_metrics, "recovery")
    print(f"  saved: {model_path}, {calibrator_path}, {metrics_path}")

    n_written = write_feature_snapshots(recovery_table, RECOVERY_MODEL_VERSION, timestamp_col="due_date")
    print(f"  wrote {n_written} FeatureSnapshot rows (model_version={RECOVERY_MODEL_VERSION})")

    print("\nTraining + persisting PTP model...")
    ptp_table = load_ptp_table()
    ptp_splits = split_ptp_table(ptp_table)
    ptp_model = train_ptp_model(ptp_splits["fit"], ptp_splits["validation"])
    ptp_calibrator = calibrate_ptp(ptp_model, ptp_splits["calibration"])

    ptp_proba = ptp_module.calibrated_predict_proba(ptp_model, ptp_calibrator, ptp_splits["test"])
    ptp_metrics = classification_metrics(ptp_splits["test"][ptp_module.LABEL_COLUMN], ptp_proba)

    model_path = save_model(ptp_model, "ptp_model")
    calibrator_path = save_model(ptp_calibrator, "ptp_calibrator")
    metrics_path = save_metrics(ptp_metrics, "ptp")
    print(f"  saved: {model_path}, {calibrator_path}, {metrics_path}")

    n_written = write_feature_snapshots(ptp_table, PTP_MODEL_VERSION, timestamp_col="T")
    print(f"  wrote {n_written} FeatureSnapshot rows (model_version={PTP_MODEL_VERSION})")

    print(f"\nSpot-check in pgAdmin: SELECT * FROM feature_snapshots WHERE model_version IN ('{RECOVERY_MODEL_VERSION}', '{PTP_MODEL_VERSION}') LIMIT 10;")
