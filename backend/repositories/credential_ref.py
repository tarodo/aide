from sqlalchemy import select

from backend.models.credential_ref import CredentialRef
from backend.repositories.base import SoftDeleteRepository


class CredentialRefRepository(SoftDeleteRepository[CredentialRef]):
    model = CredentialRef

    async def get_by_provider_and_path(
        self, provider: str, path: str
    ) -> CredentialRef | None:
        """Get a non-deleted credential ref by provider and path."""
        stmt = select(self.model).where(
            self.model.provider == provider,
            self.model.path == path,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
