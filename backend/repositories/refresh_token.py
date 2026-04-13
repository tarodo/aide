import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.sql import func

from backend.models.refresh_token import RefreshToken
from backend.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        """Lookup by SHA-256 hash of the raw token."""
        stmt = select(self.model).where(self.model.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Revoke all active tokens for a user. Returns count."""
        stmt = (
            update(self.model)
            .where(
                self.model.user_id == user_id,
                self.model.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def delete_expired(self, before: datetime) -> int:
        """Hard-delete tokens that expired before the given timestamp."""
        stmt = delete(self.model).where(self.model.expires_at < before)
        result = await self.session.execute(stmt)
        return result.rowcount
