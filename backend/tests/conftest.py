import pytest

from app.core.db import SessionLocal


@pytest.fixture(scope="session")
def db_session():
    """Real session against the configured DATABASE_URL -- these are
    integration tests against the actual dev database (already populated by
    synthetic.generator), not isolated unit tests with a mocked DB."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
