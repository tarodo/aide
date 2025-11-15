from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.cast_rule import CastRuleRepository
from backend.repositories.dataset_schema import DatasetSchemaRepository
from backend.repositories.credential_ref import CredentialRefRepository
from backend.repositories.dataset import DatasetRepository
from backend.db.session import AsyncSessionLocal
from backend.repositories.data_type import DataTypeRepository
from backend.repositories.field import FieldRepository
from backend.repositories.system import SystemRepository
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
        self.credential_refs = CredentialRefRepository(self.session)
        self.systems = SystemRepository(self.session)
        self.datasets = DatasetRepository(self.session)
        self.cast_rules = CastRuleRepository(self.session)
        self.fields = FieldRepository(self.session)
        self.dataset_schemas = DatasetSchemaRepository(self.session)
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
