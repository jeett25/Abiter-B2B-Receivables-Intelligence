from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score
from xgboost import XGBClassifier

from app.ml.config import CALIBRATED_PROBABILITY_CEILING, CALIBRATED_PROBABILITY_FLOOR, SEED
from app.ml.evaluate import archetype_sanity_check, classification_metrics, reliability_table
from app.ml.features import load_raw_tables
from app.ml.labels import build_ptp_table
from app.ml.splits import customer_based_split, split_ptp_table

# Same rationale/threshold as train_recovery.py's MIN_ARCHETYPE_N -- PTP's test
# slice is known-thin (211 rows total across 7 archetypes), so this is
# expected to trigger the full-set fallback more often than the recovery
# model's check does.
MIN_ARCHETYPE_N = 30

CATEGORICAL_COLUMNS = ["merchant_segment", "merchant_industry", "customer_segment", "customer_industry", "source"]

FEATURE_COLUMNS = [
    "amount", "amount_log1p", "payment_term_days", "issue_month", "issue_day_of_week",
    *CATEGORICAL_COLUMNS,
    "customer_relationship_days_at_cutoff", "outstanding_amount", "outstanding_ratio",
    "has_prior_history", "prior_invoice_count", "prior_paid_count", "prior_written_off_count",
    "prior_payment_rate", "prior_avg_delay_days", "prior_avg_amount", "prior_total_amount",
    "prior_max_amount", "prior_promise_count", "prior_promise_kept_rate", "prior_escalation_touches_avg",
    "prior_days_since_last_invoice", "customer_invoice_frequency",
    "recent_90d_payment_rate", "recent_90d_late_rate", "recent_180d_payment_rate",
    "recent_180d_avg_delay_days", "recent_180d_ptp_keep_rate",
]

LABEL_COLUMN = "kept"


def load_ptp_table() -> pd.DataFrame:
    return build_ptp_table()


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURE_COLUMNS].copy()
    X["has_prior_history"] = X["has_prior_history"].astype(int)
    for col in CATEGORICAL_COLUMNS:
        X[col] = X[col].astype("category")
    return X


def train_xgb_classifier(
    fit_df: pd.DataFrame, validation_df: pd.DataFrame, seed: int = SEED, scale_pos_weight: float = 1.0
) -> XGBClassifier:
    """Unweighted by default -- PTP's pooled kept rate (59.4%) is milder
    imbalance than the recovery label's (76.5%), and the recovery model's
    controlled comparison (DECISIONS.md) already showed weighting hurts
    calibration-relevant metrics with no ranking benefit; that mechanism
    transfers here (PTP is calibrated too), so it's applied directly rather
    than re-running the full comparison."""
    X_fit, y_fit = prepare_features(fit_df), fit_df[LABEL_COLUMN]
    X_val, y_val = prepare_features(validation_df), validation_df[LABEL_COLUMN]

    model = XGBClassifier(
        objective="binary:logistic",
        max_depth=4,
        n_estimators=300,
        learning_rate=0.05,
        tree_method="hist",
        enable_categorical=True,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        early_stopping_rounds=20,
        random_state=seed,
    )
    model.fit(X_fit, y_fit, eval_set=[(X_val, y_val)], verbose=False)
    model._scale_pos_weight_used = scale_pos_weight
    return model


def evaluate_model(model: XGBClassifier, df: pd.DataFrame) -> dict:
    X, y = prepare_features(df), df[LABEL_COLUMN]
    proba = model.predict_proba(X)[:, 1]
    return classification_metrics(y, proba)


def _report_experiment(name: str, model: XGBClassifier, fit_df: pd.DataFrame, test_df: pd.DataFrame) -> None:
    fit_metrics = evaluate_model(model, fit_df)
    test_metrics = evaluate_model(model, test_df)

    print(f"\n{name}")
    print(f"  scale_pos_weight used: {model._scale_pos_weight_used:.3f}")
    print(f"  boosting rounds used: {model.best_iteration + 1} / {model.n_estimators} (early_stopping_rounds=20)")
    print(f"  {'':<10} {'n':>6}  {'pos_rate':>9}  {'roc_auc':>8}  {'pr_auc':>8}  {'log_loss':>9}")
    for label, metrics in [("fit", fit_metrics), ("test", test_metrics)]:
        print(
            f"  {label:<10} {metrics['n']:>6}  {metrics['positive_rate']:>9.1%}  "
            f"{metrics['roc_auc']:>8.4f}  {metrics['pr_auc']:>8.4f}  {metrics['log_loss']:>9.4f}"
        )
    gap = fit_metrics["roc_auc"] - test_metrics["roc_auc"]
    print(f"  fit-vs-test ROC-AUC gap: {gap:+.4f} (large gap = overfitting signature)")

    importances = sorted(zip(FEATURE_COLUMNS, model.feature_importances_), key=lambda kv: -kv[1])
    print("  top 10 feature importances (gain-based):")
    for feature, importance in importances[:10]:
        print(f"    {feature:<32} {importance:.4f}")


def calibrate_model(model: XGBClassifier, calibration_df: pd.DataFrame) -> LogisticRegression:
    """Platt/sigmoid: a 1D logistic regression of the true label on the raw
    score -- fit only on Experiment A's calibration slice, never fit or test.
    Chosen (per the master plan) over isotonic for the smaller promise-level
    population -- safer against overfitting the calibration map."""
    X_cal = prepare_features(calibration_df)
    raw_proba = model.predict_proba(X_cal)[:, 1]
    calibrator = LogisticRegression()
    calibrator.fit(raw_proba.reshape(-1, 1), calibration_df[LABEL_COLUMN])
    return calibrator


def calibrated_predict_proba(model: XGBClassifier, calibrator: LogisticRegression, df: pd.DataFrame):
    """Clipped to [CALIBRATED_PROBABILITY_FLOOR, CALIBRATED_PROBABILITY_CEILING]
    -- same operational floor/ceiling as the recovery model (DECISIONS.md).
    Platt/sigmoid is smooth and much less prone to exact 0/1 than isotonic's
    step function, but the clip is cheap insurance and the same
    downstream-economics argument applies regardless of calibration method.

    .astype(np.float64) before the clip -- same fix as
    train_recovery.py's calibrated_predict_proba, applied here for
    consistency even though LogisticRegression.predict_proba() is less
    likely to leak XGBoost's float32 predict_proba() output through than
    IsotonicRegression.predict() was observed to. See that function's
    docstring and app/ml/DECISIONS.md for the full root-cause trace."""
    X = prepare_features(df)
    raw_proba = model.predict_proba(X)[:, 1]
    calibrated_proba = calibrator.predict_proba(raw_proba.reshape(-1, 1))[:, 1].astype(np.float64)
    return np.clip(calibrated_proba, CALIBRATED_PROBABILITY_FLOOR, CALIBRATED_PROBABILITY_CEILING)


def evaluate_calibrated(model: XGBClassifier, calibrator: LogisticRegression, df: pd.DataFrame) -> dict:
    calibrated_proba = calibrated_predict_proba(model, calibrator, df)
    return classification_metrics(df[LABEL_COLUMN], calibrated_proba)


def broken_class_metrics(model: XGBClassifier, calibrator: LogisticRegression, df: pd.DataFrame, threshold: float = 0.5) -> dict:
    """Precision/recall/F1 on the BROKEN class specifically -- the
    operationally meaningful failure mode ('promise-break detection'), not the
    majority KEPT class. threshold=0.5 on calibrated P(kept) is a standard
    first-pass default, not tuned."""
    calibrated_proba = calibrated_predict_proba(model, calibrator, df)
    y_true_broken = (df[LABEL_COLUMN] == 0).astype(int)
    y_pred_broken = (calibrated_proba < threshold).astype(int)
    return {
        "threshold": threshold,
        "precision": float(precision_score(y_true_broken, y_pred_broken, zero_division=0)),
        "recall": float(recall_score(y_true_broken, y_pred_broken, zero_division=0)),
        "f1": float(f1_score(y_true_broken, y_pred_broken, zero_division=0)),
    }


def _report_calibration(name: str, model: XGBClassifier, calibrator: LogisticRegression, test_df: pd.DataFrame) -> None:
    raw_metrics = evaluate_model(model, test_df)
    calibrated_metrics = evaluate_calibrated(model, calibrator, test_df)

    print(f"\n{name}")
    print(f"  {'':<12} {'roc_auc':>8}  {'pr_auc':>8}  {'brier':>8}  {'log_loss':>9}")
    for label, metrics in [("raw", raw_metrics), ("calibrated", calibrated_metrics)]:
        print(
            f"  {label:<12} {metrics['roc_auc']:>8.4f}  {metrics['pr_auc']:>8.4f}  "
            f"{metrics['brier']:>8.4f}  {metrics['log_loss']:>9.4f}"
        )

    calibrated_proba = calibrated_predict_proba(model, calibrator, test_df)
    table = reliability_table(test_df[LABEL_COLUMN], calibrated_proba)
    print(f"\n  reliability table (calibrated + clipped to [{CALIBRATED_PROBABILITY_FLOOR}, {CALIBRATED_PROBABILITY_CEILING}], test set):")
    print(table.to_string(index=False))

    broken_metrics = broken_class_metrics(model, calibrator, test_df)
    print(f"\n  broken-class detection (threshold={broken_metrics['threshold']}):")
    print(f"    precision={broken_metrics['precision']:.4f}  recall={broken_metrics['recall']:.4f}  f1={broken_metrics['f1']:.4f}")


def _report_archetype_sanity_check(model: XGBClassifier, calibrator: LogisticRegression, full_table: pd.DataFrame, test_df: pd.DataFrame) -> None:
    """Restricted to the promise-eligible subpopulation -- full_table/test_df
    are already build_ptp_table() output, so no extra filtering needed; this
    is never compared against the full customer base."""
    customers = (
        load_raw_tables()["customers"][["id", "archetype", "true_promise_keep_probability"]]
        .rename(columns={"id": "customer_id"})
    )

    test_counts = test_df.merge(customers, on="customer_id", how="left").groupby("archetype").size()
    use_full_set = len(test_counts) == 0 or test_counts.min() < MIN_ARCHETYPE_N

    source_df = full_table if use_full_set else test_df
    joined = source_df.merge(customers, on="customer_id", how="left")
    proba = calibrated_predict_proba(model, calibrator, source_df)

    print(f"\nArchetype sanity check ({'FULL promise-eligible set' if use_full_set else 'Experiment A test slice'}, promise-eligible subpopulation only):")
    if use_full_set:
        min_n = int(test_counts.min()) if len(test_counts) else 0
        print(
            f"  NOTE: computed over the full promise-eligible set, not held-out test rows only -- "
            f"test-slice per-archetype counts were too thin (min n={min_n} < {MIN_ARCHETYPE_N}). "
            f"Diagnostic sanity check against known ground truth, not a held-out performance claim."
        )

    sanity_table = archetype_sanity_check(joined, proba, true_prob_col="true_promise_keep_probability", label_col=LABEL_COLUMN)
    print(sanity_table.to_string(index=False))


if __name__ == "__main__":
    table = load_ptp_table()

    splits_a = split_ptp_table(table)
    model_a = train_xgb_classifier(splits_a["fit"], splits_a["validation"])
    _report_experiment("Experiment A (time-based, raw)", model_a, splits_a["fit"], splits_a["test"])

    calibrator_a = calibrate_model(model_a, splits_a["calibration"])
    _report_calibration("Experiment A (calibrated)", model_a, calibrator_a, splits_a["test"])
    _report_archetype_sanity_check(model_a, calibrator_a, table, splits_a["test"])

    splits_b = customer_based_split(table)
    model_b = train_xgb_classifier(splits_b["fit"], splits_b["validation"])
    _report_experiment("Experiment B (customer-based, raw only -- no calibration per scope cut)", model_b, splits_b["fit"], splits_b["test"])
