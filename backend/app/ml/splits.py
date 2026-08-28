from __future__ import annotations

import random

import pandas as pd

from app.ml.config import (
    CALIBRATION_FRACTION_OF_FIT,
    CUSTOMER_SPLIT_TRAIN_FRACTION,
    CUSTOMER_SPLIT_VAL_FRACTION_OF_TRAIN,
    SEED,
    TIME_SPLIT_TEST_MONTHS,
    TIME_SPLIT_TRAIN_MONTHS,
)


def time_boundary(
    dates: pd.Series, train_months: int = TIME_SPLIT_TRAIN_MONTHS, test_months: int = TIME_SPLIT_TEST_MONTHS
) -> pd.Timestamp:
    """Train/test cutoff derived purely from the observed min/max of dates,
    proportionally -- no imported window constants, no assumption about the
    exact total span."""
    min_date, max_date = dates.min(), dates.max()
    total_days = (max_date - min_date).days
    boundary_days = round(total_days * train_months / (train_months + test_months))
    return min_date + pd.Timedelta(days=boundary_days)


def time_based_split(df: pd.DataFrame, date_col: str, label_col: str, seed: int = SEED) -> dict:
    """Experiment A: time-based, no customer-exclusivity constraint. Returns:
      fit          -- months 1-8 of the train window, WITH the calibration
                       subsample already removed (never passed to .fit() twice)
      validation   -- the most recent ~1 month of the train window (chronologically
                       strictly after fit, not a random subset of the train pool)
      calibration  -- stratified-by-label_col subsample drawn from the months-1-8
                       pool, disjoint from fit by construction (dropped by index)
      test         -- rows on/after the train/test boundary, touched once
    Also returns 'boundary' and 'fit_val_boundary' for diagnostics/tests.
    """
    boundary = time_boundary(df[date_col])
    train = df[df[date_col] < boundary]
    test = df[df[date_col] >= boundary]

    train_window_days = (boundary - df[date_col].min()).days
    fit_val_boundary = boundary - pd.Timedelta(days=round(train_window_days / TIME_SPLIT_TRAIN_MONTHS))

    fit_and_calibration_pool = train[train[date_col] < fit_val_boundary]
    validation = train[train[date_col] >= fit_val_boundary]

    # GroupBy.sample() directly, not groupby().apply(lambda g: g.sample(...)) --
    # the latter, with group_keys=False, silently drops the grouping column
    # (label_col) from what's passed to the lambda as of pandas' newer
    # default include_groups behavior, which would strip label_col from the
    # returned calibration slice entirely.
    calibration = fit_and_calibration_pool.groupby(label_col, group_keys=False).sample(
        frac=CALIBRATION_FRACTION_OF_FIT, random_state=seed
    )
    fit = fit_and_calibration_pool.drop(calibration.index)

    return {
        "fit": fit,
        "validation": validation,
        "calibration": calibration,
        "test": test,
        "boundary": boundary,
        "fit_val_boundary": fit_val_boundary,
    }


def split_recovery_table(df: pd.DataFrame, seed: int = SEED) -> dict:
    """Experiment A for the recovery table -- buckets by issue_date, NOT
    due_date. due_date is the per-row feature-assessment cutoff (subtask 1);
    issue_date is what this split buckets on, per the master plan's explicit
    choice. Hardcoded here rather than left to the caller so this can't
    silently be swapped for due_date later."""
    date_col = "issue_date"
    assert date_col in df.columns, f"recovery table missing {date_col!r}"
    return time_based_split(df, date_col=date_col, label_col="recovery_label", seed=seed)


def split_ptp_table(df: pd.DataFrame, seed: int = SEED) -> dict:
    """Experiment A for the PTP table -- buckets by T (the promise-cutoff
    column build_ptp_table() returns), not due_date or promised_date."""
    date_col = "T"
    assert date_col in df.columns, f"PTP table missing {date_col!r}"
    return time_based_split(df, date_col=date_col, label_col="kept", seed=seed)


def customer_based_split(df: pd.DataFrame, customer_col: str = "customer_id", seed: int = SEED) -> dict:
    """Experiment B: customer-level split, no time constraint, train/test only
    (no calibration slice -- per the master plan's scope cut)."""
    customers = sorted(df[customer_col].unique(), key=str)
    rng = random.Random(seed)
    rng.shuffle(customers)

    n_train = round(len(customers) * CUSTOMER_SPLIT_TRAIN_FRACTION)
    train_customers = customers[:n_train]
    test_customers = set(customers[n_train:])

    n_val = round(len(train_customers) * CUSTOMER_SPLIT_VAL_FRACTION_OF_TRAIN)
    val_customers = set(train_customers[:n_val])
    fit_customers = set(train_customers[n_val:])

    return {
        "fit": df[df[customer_col].isin(fit_customers)],
        "validation": df[df[customer_col].isin(val_customers)],
        "test": df[df[customer_col].isin(test_customers)],
        "fit_customers": fit_customers,
        "val_customers": val_customers,
        "test_customers": test_customers,
    }


def _print_time_split_summary(name: str, splits: dict, date_col: str, customer_col: str = "customer_id") -> None:
    print(f"\n{name} -- Experiment A (time-based)")
    print(f"  train/test boundary: {splits['boundary'].date()}")
    print(f"  fit/validation boundary: {splits['fit_val_boundary'].date()}")
    for key in ["fit", "validation", "calibration", "test"]:
        part = splits[key]
        n_customers = part[customer_col].nunique()
        date_range = f"{part[date_col].min().date()}..{part[date_col].max().date()}" if len(part) else "empty"
        print(f"  {key:<12} n={len(part):>5}  customers={n_customers:>4}  {date_col}=[{date_range}]")

    train_side_customers = (
        set(splits["fit"][customer_col]) | set(splits["validation"][customer_col]) | set(splits["calibration"][customer_col])
    )
    test_customers = set(splits["test"][customer_col])
    print(f"  customers with 0 test rows (all rows on train side): {len(train_side_customers - test_customers)}")
    print(f"  customers with 0 train-side rows (all rows in test): {len(test_customers - train_side_customers)}")


def _print_customer_split_summary(name: str, splits: dict, date_col: str) -> None:
    print(f"\n{name} -- Experiment B (customer-based)")
    for key, cust_key in [("fit", "fit_customers"), ("validation", "val_customers"), ("test", "test_customers")]:
        part = splits[key]
        date_range = f"{part[date_col].min().date()}..{part[date_col].max().date()}" if len(part) else "empty"
        print(f"  {key:<12} n={len(part):>5}  customers={len(splits[cust_key]):>4}  {date_col}=[{date_range}]")


if __name__ == "__main__":
    from app.ml.features import build_feature_table
    from app.ml.labels import build_ptp_table, recovery_label

    recovery_table = build_feature_table()
    recovery_table["recovery_label"] = recovery_table.apply(recovery_label, axis=1)

    _print_time_split_summary("Recovery", split_recovery_table(recovery_table), date_col="issue_date")
    _print_customer_split_summary("Recovery", customer_based_split(recovery_table), date_col="issue_date")

    ptp_table = build_ptp_table()
    _print_time_split_summary("PTP", split_ptp_table(ptp_table), date_col="T")
    _print_customer_split_summary("PTP", customer_based_split(ptp_table), date_col="T")
