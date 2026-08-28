from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score


def classification_metrics(y_true, y_pred_proba) -> dict:
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)
    return {
        "n": len(y_true),
        "positive_rate": float(y_true.mean()),
        "roc_auc": float(roc_auc_score(y_true, y_pred_proba)),
        "pr_auc": float(average_precision_score(y_true, y_pred_proba)),
        "log_loss": float(log_loss(y_true, y_pred_proba, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, y_pred_proba)),
    }


def reliability_table(y_true, y_pred_proba, n_bins: int = 10) -> pd.DataFrame:
    """10 equal-width probability bins: count, mean predicted probability,
    observed positive rate -- the standard calibration-quality diagnostic."""
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)
    bins = np.linspace(0, 1, n_bins + 1)
    bin_idx = np.clip(np.digitize(y_pred_proba, bins) - 1, 0, n_bins - 1)

    rows = []
    for b in range(n_bins):
        mask = bin_idx == b
        n = int(mask.sum())
        rows.append(
            {
                "bin": f"[{bins[b]:.1f}, {bins[b + 1]:.1f})",
                "n": n,
                "mean_predicted": float(y_pred_proba[mask].mean()) if n else float("nan"),
                "observed_rate": float(y_true[mask].mean()) if n else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def archetype_sanity_check(df: pd.DataFrame, predicted_proba, true_prob_col: str, label_col: str) -> pd.DataFrame:
    """Three-way table: archetype | true_organic_probability | mean_predicted_probability
    | observed_rate. df must already have 'archetype' and true_prob_col joined in
    (read-only ground truth, never a feature) -- this function doesn't touch the DB.
    The third column matters: observed can legitimately exceed the organic constant
    since simulated interventions push realized outcomes above the no-chasing
    baseline, so a predicted-vs-true delta alone can't distinguish 'model is biased'
    from 'this archetype's realized outcomes were themselves shifted by actions'."""
    working = df.copy()
    working["_predicted"] = np.asarray(predicted_proba)

    rows = [
        {
            "archetype": archetype,
            "n": len(group),
            "true_organic_probability": float(group[true_prob_col].mean()),
            "mean_predicted_probability": float(group["_predicted"].mean()),
            "observed_rate": float(group[label_col].mean()),
        }
        for archetype, group in working.groupby("archetype")
    ]
    return pd.DataFrame(rows).sort_values("archetype").reset_index(drop=True)
