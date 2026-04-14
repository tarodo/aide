"""Conftest for pure service unit tests.

Overrides the DB-dependent autouse fixtures from the top-level conftest so
that pure (no-DB) tests in this directory can run locally without Docker.
"""

import pytest
import pytest_asyncio


@pytest.fixture(scope="session", autouse=True)
def run_migrations():
    """No-op override: pure service tests need no DB migrations."""
    yield


@pytest_asyncio.fixture(autouse=True)
async def transactional_session():
    """No-op override: pure service tests need no transactional session."""
    yield None
