from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier

from app.ml.config import CALIBRATED_PROBABILITY_CEILING, CALIBRATED_PROBABILITY_FLOOR, SEED
from app.ml.evaluate import archetype_sanity_check, classification_metrics, reliability_table
from app.ml.features import build_feature_table, load_raw_tables
from app.ml.labels import recovery_label
from app.ml.splits import customer_based_split, split_recovery_table

# Minimum per-archetype row count in a slice for the sanity-check table to
# trust it as "test-only" -- below this, the per-archetype mean is too noisy
# to read, and the master plan explicitly permits falling back to the full
# historical set instead (flagged in the printed output when it happens).
MIN_ARCHETYPE_N = 30

CATEGORICAL_COLUMNS = ["merchant_segment", "merchant_industry", "customer_segment", "customer_industry"]

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

LABEL_COLUMN = "recovery_label"


def load_labeled_recovery_table() -> pd.DataFrame:
    table = build_feature_table()
    table[LABEL_COLUMN] = table.apply(recovery_label, axis=1)
    return table


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURE_COLUMNS].copy()
    X["has_prior_history"] = X["has_prior_history"].astype(int)
    for col in CATEGORICAL_COLUMNS:
        X[col] = X[col].astype("category")
    return X


def train_xgb_classifier(
    fit_df: pd.DataFrame, validation_df: pd.DataFrame, seed: int = SEED, scale_pos_weight: float = 1.0
) -> XGBClassifier:
    """scale_pos_weight defaults to 1.0 (unweighted). Tested against an
    auto-computed weight (~0.31 for A, ~0.32 for B, i.e. neg/pos from fit_df's
    own class counts) on both experiments: ROC-AUC/PR-AUC were essentially
    unchanged (loss reshaping doesn't change ranking ability), while
    LogLoss/Brier were 20-25% worse under weighting in both experiments, and
    Experiment B's early stopping stopped engaging properly under weighting
    (300/300 rounds used vs. 51/300 unweighted). See DECISIONS.md for the full
    comparison table and reasoning. Don't reintroduce weighting without a new
    comparison showing it actually helps -- pass an explicit value to override
    for that kind of experiment."""
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
    model._scale_pos_weight_used = scale_pos_weight  # stashed for reporting only
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


def calibrate_model(model: XGBClassifier, calibration_df: pd.DataFrame) -> IsotonicRegression:
    """Fit only on Experiment A's calibration slice -- never fit or test.
    Using IsotonicRegression directly rather than sklearn's
    CalibratedClassifierCV(cv="prefit") -- that path is deprecated as of
    sklearn 1.6+ in favor of a FrozenEstimator wrapper; going direct avoids the
    version churn and keeps the calibration step fully transparent."""
    X_cal = prepare_features(calibration_df)
    raw_proba = model.predict_proba(X_cal)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_proba, calibration_df[LABEL_COLUMN])
    return calibrator


def calibrated_predict_proba(model: XGBClassifier, calibrator: IsotonicRegression, df: pd.DataFrame):
    """Isotonic's PAV fit can produce boundary blocks that are literally
    all-one-class in the calibration slice, so calibrator.predict() can return
    exact 0.0/1.0 -- confirmed live (203 test rows calibrated to exactly 1.0,
    including some that were actually y=0, driving log loss up ~38% with no
    real degradation in calibration quality; Brier barely moved since it's
    bounded and doesn't have this blowup mode). Clipped to
    [CALIBRATED_PROBABILITY_FLOOR, CALIBRATED_PROBABILITY_CEILING]: a
    deliberate operational floor/ceiling, not a machine epsilon -- no
    probability from finite calibration data should be reported as literally
    certain or impossible, and this recovery probability is meant to feed
    Day 3's EV(a) = P(recovery)*Amount - Cost - Friction, where a literal 0/1
    would be a correctness problem beyond just this metric. See DECISIONS.md."""
    X = prepare_features(df)
    raw_proba = model.predict_proba(X)[:, 1]
    calibrated_proba = calibrator.predict(raw_proba)
    return np.clip(calibrated_proba, CALIBRATED_PROBABILITY_FLOOR, CALIBRATED_PROBABILITY_CEILING)


def evaluate_calibrated(model: XGBClassifier, calibrator: IsotonicRegression, df: pd.DataFrame) -> dict:
    calibrated_proba = calibrated_predict_proba(model, calibrator, df)
    return classification_metrics(df[LABEL_COLUMN], calibrated_proba)


def _report_calibration(name: str, model: XGBClassifier, calibrator: IsotonicRegression, test_df: pd.DataFrame) -> None:
    raw_metrics = evaluate_model(model, test_df)
    calibrated_metrics = evaluate_calibrated(model, calibrator, test_df)

    print(f"\n{name}")
    print(f"  {'':<12} {'roc_auc':>8}  {'pr_auc':>8}  {'brier':>8}  {'log_loss':>9}")
    for label, metrics in [("raw", raw_metrics), ("calibrated", calibrated_metrics)]:
        print(
            f"  {label:<12} {metrics['roc_auc']:>8.4f}  {metrics['pr_auc']:>8.4f}  "
            f"{metrics['brier']:>8.4f}  {metrics['log_loss']:>9.4f}"
        )
    print("  (ROC-AUC/PR-AUC should stay close, not bit-identical -- isotonic's step function")
    print("   introduces ties the raw scores didn't have, which can nudge rank-based metrics slightly)")

    calibrated_proba = calibrated_predict_proba(model, calibrator, test_df)
    table = reliability_table(test_df[LABEL_COLUMN], calibrated_proba)
    print(f"\n  reliability table (calibrated + clipped to [{CALIBRATED_PROBABILITY_FLOOR}, {CALIBRATED_PROBABILITY_CEILING}], test set):")
    print(table.to_string(index=False))


def _report_archetype_sanity_check(model: XGBClassifier, calibrator: IsotonicRegression, full_table: pd.DataFrame, test_df: pd.DataFrame) -> None:
    customers = (
        load_raw_tables()["customers"][["id", "archetype", "true_recovery_probability"]]
        .rename(columns={"id": "customer_id"})
    )

    test_counts = test_df.merge(customers, on="customer_id", how="left").groupby("archetype").size()
    use_full_set = len(test_counts) == 0 or test_counts.min() < MIN_ARCHETYPE_N

    source_df = full_table if use_full_set else test_df
    joined = source_df.merge(customers, on="customer_id", how="left")
    proba = calibrated_predict_proba(model, calibrator, source_df)

    print(f"\nArchetype sanity check ({'FULL historical set' if use_full_set else 'Experiment A test slice'}):")
    if use_full_set:
        min_n = int(test_counts.min()) if len(test_counts) else 0
        print(
            f"  NOTE: computed over the full historical set, not held-out test rows only -- "
            f"test-slice per-archetype counts were too thin (min n={min_n} < {MIN_ARCHETYPE_N}). "
            f"Diagnostic sanity check against known ground truth, not a held-out performance claim."
        )

    sanity_table = archetype_sanity_check(joined, proba, true_prob_col="true_recovery_probability", label_col=LABEL_COLUMN)
    print(sanity_table.to_string(index=False))


if __name__ == "__main__":
    table = load_labeled_recovery_table()

    splits_a = split_recovery_table(table)
    model_a = train_xgb_classifier(splits_a["fit"], splits_a["validation"])
    _report_experiment("Experiment A (time-based, raw)", model_a, splits_a["fit"], splits_a["test"])

    calibrator_a = calibrate_model(model_a, splits_a["calibration"])
    _report_calibration("Experiment A (calibrated)", model_a, calibrator_a, splits_a["test"])
    _report_archetype_sanity_check(model_a, calibrator_a, table, splits_a["test"])

    splits_b = customer_based_split(table)
    model_b = train_xgb_classifier(splits_b["fit"], splits_b["validation"])
    _report_experiment("Experiment B (customer-based, raw only -- no calibration per scope cut)", model_b, splits_b["fit"], splits_b["test"])
