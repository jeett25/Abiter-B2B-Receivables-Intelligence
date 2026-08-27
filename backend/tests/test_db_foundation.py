"""Database foundation tests: schema, extensions, and connectivity are all in place."""
from sqlalchemy import bindparam, inspect, text

from app.core.db import engine

EXPECTED_TABLES = {
    "merchants",
    "customers",
    "invoices",
    "payments",
    "payment_promises",
    "interactions",
    "recovery_actions",
    "decision_logs",
    "account_state",
    "attribution_records",
    "feature_snapshots",
}

EXPECTED_ENUMS = {
    "invoice_status",
    "payment_status",
    "promise_status",
    "action_type",
    "policy_result",
    "account_current_state",
    "treatment_group",
}


def test_connection_works(db_session):
    result = db_session.execute(text("SELECT 1")).scalar_one()
    assert result == 1


def test_all_11_tables_exist():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables: {missing}"


def test_pgvector_extension_enabled(db_session):
    result = db_session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar_one_or_none()
    assert result == 1


def test_expected_enum_types_exist(db_session):
    stmt = text("SELECT typname FROM pg_type WHERE typname IN :names").bindparams(
        bindparam("names", expanding=True)
    )
    found = set(db_session.execute(stmt, {"names": list(EXPECTED_ENUMS)}).scalars().all())
    missing = EXPECTED_ENUMS - found
    assert not missing, f"Missing enum types: {missing}"


def test_invoices_has_expected_foreign_keys():
    inspector = inspect(engine)
    fks = inspector.get_foreign_keys("invoices")
    referred_tables = {fk["referred_table"] for fk in fks}
    assert {"merchants", "customers"} <= referred_tables


def test_account_state_primary_key_is_invoice_id():
    inspector = inspect(engine)
    pk = inspector.get_pk_constraint("account_state")
    assert pk["constrained_columns"] == ["invoice_id"]
