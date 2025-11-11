from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.repositories.data_type import DataTypeRepository
from backend.repositories.system_flavor import SystemFlavorRepository
from backend.repositories.system_kind import SystemKindRepository
from backend.repositories.user import UserRepository


class UnitOfWork:
    def __init__(self) -> None:
        self.session_factory = AsyncSessionLocal

    async def __aenter__(self) -> UnitOfWork:
        self.session: AsyncSession = self.session_factory()
        self.users = UserRepository(self.session)
        self.system_kinds = SystemKindRepository(self.session)
        self.system_flavors = SystemFlavorRepository(self.session)
        self.data_types = DataTypeRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
        await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
