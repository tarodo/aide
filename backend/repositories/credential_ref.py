from sqlalchemy import select

from backend.models.credential_ref import CredentialRef
from backend.repositories.base import BaseRepository


class CredentialRefRepository(BaseRepository[CredentialRef]):
    model = CredentialRef

    async def get_by_provider_and_path(
        self, provider: str, path: str
    ) -> CredentialRef | None:
        """Get a credential ref by provider and path."""
        stmt = select(self.model).where(
            self.model.provider == provider, self.model.path == path
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
