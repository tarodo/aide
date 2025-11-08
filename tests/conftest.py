from typing import AsyncGenerator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.core.settings import settings
from backend.db.uow import UnitOfWork
from backend.main import app

# This is to make sure all models are imported before creating tables
from backend import models  # noqa


@pytest.fixture(scope="session", autouse=True)
def run_migrations():
    """
    Run alembic migrations on the test database before tests run,
    and downgrade to base after tests are done.
    """
    alembic_cfg = Config("backend/alembic.ini")
    sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_db_url)

    command.upgrade(alembic_cfg, "head")
    yield
    command.downgrade(alembic_cfg, "base")


@pytest_asyncio.fixture(autouse=True)
async def transactional_session() -> AsyncGenerator[None, None]:
    """
    This fixture wraps each test in a transaction and rolls it back.
    It also overrides the app's UoW to use this single transaction-bound session.
    Creates a fresh engine and connection for each test to avoid event loop issues.
    """
    # Create a fresh engine for this test's event loop
    test_engine = create_async_engine(settings.DATABASE_URL)
    connection = await test_engine.connect()
    trans = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    def uow_override():
        uow = UnitOfWork()
        uow.session_factory = lambda: session
        return uow

    app.dependency_overrides[UnitOfWork] = uow_override

    yield

    # Teardown - rollback transaction, then close session and connection
    await trans.rollback()
    await session.close()
    await connection.close()
    await test_engine.dispose()
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """
    Get a TestClient instance. The app it uses is already patched
    by the transactional_session fixture.
    """
    with TestClient(app) as c:
        yield c
