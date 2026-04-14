"""
Override session-scoped DB fixtures that are not needed for schema-only tests.
The root conftest.py declares run_migrations and transactional_session as
autouse=True, which would attempt to connect to a DB. We shadow them here
so these pure-Pydantic tests can run without any database.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def run_migrations():  # type: ignore[override]
    """No-op override: schema tests need no DB migrations."""
    yield


@pytest.fixture(autouse=True)
def transactional_session():  # type: ignore[override]
    """No-op override: schema tests need no transactional session."""
    yield
