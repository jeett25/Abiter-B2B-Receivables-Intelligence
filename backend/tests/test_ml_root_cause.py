"""app/ml/train_root_cause.py + root_cause_label() tests."""
import pandas as pd
import pytest

from app.ml.labels import root_cause_label
from app.ml.train_root_cause import build_root_cause_table


def test_root_cause_label_maps_cash_flow_stress_to_one():
    assert root_cause_label(pd.Series({"true_root_cause": "cash_flow_stress"})) == 1


def test_root_cause_label_maps_oversight_to_zero():
    assert root_cause_label(pd.Series({"true_root_cause": "oversight"})) == 0


def test_root_cause_label_asserts_on_disputed_row():
    with pytest.raises(AssertionError):
        root_cause_label(pd.Series({"true_root_cause": "dispute"}))


def test_build_root_cause_table_excludes_disputed_rows():
    table = build_root_cause_table()
    assert (table["true_root_cause"] != "dispute").all()


def test_build_root_cause_table_label_matches_source_column():
    table = build_root_cause_table()
    expected = (table["true_root_cause"] == "cash_flow_stress").astype(int)
    assert (table["root_cause_label"] == expected).all()


def test_build_root_cause_table_has_both_classes_present():
    table = build_root_cause_table()
    assert set(table["root_cause_label"].unique()) == {0, 1}
