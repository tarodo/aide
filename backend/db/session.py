from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.core.settings import settings

async_engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=async_engine
)
