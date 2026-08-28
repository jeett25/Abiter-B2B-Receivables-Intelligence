"""app/ml/splits.py tests: boundary derivation, train/test and fit/validation
non-overlap (both by row id and chronologically), and Experiment B customer
disjointness. Pure -- no DB, splits.py operates on plain DataFrames."""
import random

import pandas as pd

from app.ml.splits import customer_based_split, time_based_split, time_boundary


def _synthetic_table(n: int = 300, seed: int = 1, start: str = "2024-01-01", span_days: int = 329) -> pd.DataFrame:
    rng = random.Random(seed)
    base = pd.Timestamp(start)
    rows = [
        {
            "id": f"row-{i}",
            "customer_id": f"cust-{i % 30}",
            "date": base + pd.Timedelta(days=rng.randint(0, span_days)),
            "label": rng.randint(0, 1),
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def test_time_boundary_is_derived_from_data_range_not_hardcoded():
    dates_a = pd.Series(pd.date_range("2024-01-01", periods=110, freq="D"))
    boundary_a = time_boundary(dates_a)
    assert boundary_a == dates_a.min() + pd.Timedelta(days=round(109 * 9 / 11))

    dates_b = pd.Series(pd.date_range("2024-06-01", periods=220, freq="D"))
    boundary_b = time_boundary(dates_b)
    assert boundary_b == dates_b.min() + pd.Timedelta(days=round(219 * 9 / 11))

    # different input ranges -> different computed boundaries, proving this is
    # actually derived from the data, not a fixed date
    assert boundary_a != boundary_b


def test_experiment_a_rows_respect_the_train_test_boundary():
    df = _synthetic_table()
    splits = time_based_split(df, date_col="date", label_col="label")
    boundary = splits["boundary"]

    assert (splits["fit"]["date"] < boundary).all()
    assert (splits["validation"]["date"] < boundary).all()
    assert (splits["calibration"]["date"] < boundary).all()
    assert (splits["test"]["date"] >= boundary).all()


def test_experiment_a_validation_is_chronologically_after_fit():
    """Validation must be the most recent train-window rows, not a random
    subset -- a bug that shuffled fit/validation instead of splitting by time
    would pass the boundary-only check above but fail this one."""
    df = _synthetic_table()
    splits = time_based_split(df, date_col="date", label_col="label")
    assert splits["fit"]["date"].max() <= splits["validation"]["date"].min()


def test_experiment_a_no_row_shared_between_train_side_and_test():
    df = _synthetic_table()
    splits = time_based_split(df, date_col="date", label_col="label")

    train_side_ids = set(splits["fit"]["id"]) | set(splits["validation"]["id"]) | set(splits["calibration"]["id"])
    test_ids = set(splits["test"]["id"])
    assert train_side_ids.isdisjoint(test_ids)

    # fit already excludes the calibration subsample -- not a hidden overlap
    assert set(splits["fit"]["id"]).isdisjoint(set(splits["calibration"]["id"]))


def test_calibration_slice_preserves_the_label_column():
    """Regression guard: groupby(label_col).apply(lambda g: g.sample(...)) with
    group_keys=False silently drops label_col from the result under pandas'
    newer include_groups default -- caught this exact bug live when
    calibrate_model() couldn't find recovery_label in the calibration slice."""
    df = _synthetic_table()
    splits = time_based_split(df, date_col="date", label_col="label")
    assert "label" in splits["calibration"].columns
    assert not splits["calibration"]["label"].isna().any()


def test_experiment_b_customer_sets_are_pairwise_disjoint():
    df = _synthetic_table()
    splits = customer_based_split(df)

    assert splits["fit_customers"].isdisjoint(splits["val_customers"])
    assert splits["fit_customers"].isdisjoint(splits["test_customers"])
    assert splits["val_customers"].isdisjoint(splits["test_customers"])
