from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier

from app.ml.config import CALIBRATED_PROBABILITY_CEILING, CALIBRATED_PROBABILITY_FLOOR, SEED
from app.ml.evaluate import archetype_sanity_check, classification_metrics, reliability_table
from app.ml.features import build_feature_table, load_raw_tables
from app.ml.labels import root_cause_label
from app.ml.splits import split_root_cause_table
from app.ml.train_recovery import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, prepare_features

MIN_ARCHETYPE_N = 30

LABEL_COLUMN = "root_cause_label"

# Per-archetype "true" P(cash_flow_stress) is a real generator parameter
# (synthetic/archetypes.py's root_cause_weights), unlike true_recovery_probability
# it isn't literally a per-customer field in the DB -- built here by mapping
# archetype -> its known weight, same read-only-diagnostic role as Day 2's
# true_recovery_probability join (never a feature, verification only).
ARCHETYPE_TRUE_CASH_FLOW_STRESS_PROBABILITY = {
    "reliable_payer": 0.15,
    "slightly_late": 0.25,
    "chronic_late": 0.65,
    "promise_keeper": 0.50,
    "promise_breaker": 0.70,
    "strategic_enterprise": 0.40,
    "cash_constrained": 0.90,
    "already_paid_false_alarm": 0.10,
}


def build_root_cause_table() -> pd.DataFrame:
    """Same historical rows/features as build_feature_table() (due_date
    cutoff, point-in-time safe, unchanged) -- true_root_cause joined back in
    ONLY to filter out disputed rows and compute the label, exactly the same
    read-only-ground-truth pattern the archetype sanity check already uses.
    Disputed rows are dropped entirely: this table (and the model trained on
    it) answers 'cash-flow stress vs. oversight, given the invoice is not
    disputed' -- not a three-way production classification. Dispute itself
    stays the deterministic detect_dispute() passthrough in policy.py."""
    table = build_feature_table()
    root_cause = load_raw_tables()["invoices"][["id", "true_root_cause"]].rename(columns={"id": "invoice_id"})
    table = table.merge(root_cause, on="invoice_id", how="left")
    table = table[table["true_root_cause"] != "dispute"].reset_index(drop=True)
    table[LABEL_COLUMN] = table.apply(root_cause_label, axis=1)
    return table


def train_xgb_classifier(fit_df: pd.DataFrame, validation_df: pd.DataFrame, seed: int = SEED) -> XGBClassifier:
    """Same architecture as the recovery model (see train_recovery.py's
    scale_pos_weight comparison note -- unweighted, for the same reason)."""
    X_fit, y_fit = prepare_features(fit_df), fit_df[LABEL_COLUMN]
    X_val, y_val = prepare_features(validation_df), validation_df[LABEL_COLUMN]

    model = XGBClassifier(
        objective="binary:logistic",
        max_depth=4,
        n_estimators=300,
        learning_rate=0.05,
        tree_method="hist",
        enable_categorical=True,
        eval_metric="logloss",
        early_stopping_rounds=20,
        random_state=seed,
    )
    model.fit(X_fit, y_fit, eval_set=[(X_val, y_val)], verbose=False)
    return model


def evaluate_model(model: XGBClassifier, df: pd.DataFrame) -> dict:
    X, y = prepare_features(df), df[LABEL_COLUMN]
    proba = model.predict_proba(X)[:, 1]
    return classification_metrics(y, proba)


def calibrate_model(model: XGBClassifier, calibration_df: pd.DataFrame) -> IsotonicRegression:
    X_cal = prepare_features(calibration_df)
    raw_proba = model.predict_proba(X_cal)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_proba, calibration_df[LABEL_COLUMN])
    return calibrator


def calibrated_predict_proba(model: XGBClassifier, calibrator: IsotonicRegression, df: pd.DataFrame):
    """Same float32->float64-before-clip fix as train_recovery.py's version
    (see that module's docstring for why) -- applied here from the start
    rather than waiting to rediscover the same bug."""
    X = prepare_features(df)
    raw_proba = model.predict_proba(X)[:, 1]
    calibrated_proba = calibrator.predict(raw_proba).astype(np.float64)
    return np.clip(calibrated_proba, CALIBRATED_PROBABILITY_FLOOR, CALIBRATED_PROBABILITY_CEILING)


def _report_experiment(name: str, model: XGBClassifier, fit_df: pd.DataFrame, test_df: pd.DataFrame) -> None:
    fit_metrics = evaluate_model(model, fit_df)
    test_metrics = evaluate_model(model, test_df)

    print(f"\n{name}")
    print("  NOTE: this evaluates 'cash_flow_stress vs. oversight given the invoice is not")
    print("  disputed' -- disputed rows are excluded from this table entirely (see")
    print("  build_root_cause_table()). Do not read these numbers as a three-way")
    print("  production classification accuracy; dispute is handled separately and")
    print("  deterministically by detect_dispute() in app/decision/policy.py.")
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


def _report_calibration(name: str, model: XGBClassifier, calibrator: IsotonicRegression, test_df: pd.DataFrame) -> None:
    raw_metrics = evaluate_model(model, test_df)
    calibrated_proba = calibrated_predict_proba(model, calibrator, test_df)
    calibrated_metrics = classification_metrics(test_df[LABEL_COLUMN], calibrated_proba)

    print(f"\n{name}")
    print(f"  {'':<12} {'roc_auc':>8}  {'pr_auc':>8}  {'brier':>8}  {'log_loss':>9}")
    for label, metrics in [("raw", raw_metrics), ("calibrated", calibrated_metrics)]:
        print(
            f"  {label:<12} {metrics['roc_auc']:>8.4f}  {metrics['pr_auc']:>8.4f}  "
            f"{metrics['brier']:>8.4f}  {metrics['log_loss']:>9.4f}"
        )

    table = reliability_table(test_df[LABEL_COLUMN], calibrated_proba)
    print(f"\n  reliability table (calibrated + clipped to [{CALIBRATED_PROBABILITY_FLOOR}, {CALIBRATED_PROBABILITY_CEILING}], test set):")
    print(table.to_string(index=False))


def _report_archetype_sanity_check(model: XGBClassifier, calibrator: IsotonicRegression, full_table: pd.DataFrame, test_df: pd.DataFrame) -> None:
    customers = load_raw_tables()["customers"][["id", "archetype"]].rename(columns={"id": "customer_id"})

    test_counts = test_df.merge(customers, on="customer_id", how="left").groupby("archetype").size()
    use_full_set = len(test_counts) == 0 or test_counts.min() < MIN_ARCHETYPE_N

    source_df = full_table if use_full_set else test_df
    joined = source_df.merge(customers, on="customer_id", how="left")
    joined["true_cash_flow_stress_probability"] = joined["archetype"].map(ARCHETYPE_TRUE_CASH_FLOW_STRESS_PROBABILITY)
    proba = calibrated_predict_proba(model, calibrator, source_df)

    print(f"\nArchetype sanity check ({'FULL non-disputed set' if use_full_set else 'Experiment A test slice'}, verification-only):")
    if use_full_set:
        min_n = int(test_counts.min()) if len(test_counts) else 0
        print(
            f"  NOTE: computed over the full non-disputed set, not held-out test rows only -- "
            f"test-slice per-archetype counts were too thin (min n={min_n} < {MIN_ARCHETYPE_N})."
        )

    sanity_table = archetype_sanity_check(
        joined, proba, true_prob_col="true_cash_flow_stress_probability", label_col=LABEL_COLUMN
    )
    print(sanity_table.to_string(index=False))


if __name__ == "__main__":
    table = build_root_cause_table()
    print(f"Root-cause table: {len(table)} non-disputed historical rows "
          f"({table[LABEL_COLUMN].mean():.1%} cash_flow_stress)")

    splits_a = split_root_cause_table(table)
    model_a = train_xgb_classifier(splits_a["fit"], splits_a["validation"])
    _report_experiment("Experiment A (time-based, raw)", model_a, splits_a["fit"], splits_a["test"])

    calibrator_a = calibrate_model(model_a, splits_a["calibration"])
    _report_calibration("Experiment A (calibrated)", model_a, calibrator_a, splits_a["test"])
    _report_archetype_sanity_check(model_a, calibrator_a, table, splits_a["test"])
