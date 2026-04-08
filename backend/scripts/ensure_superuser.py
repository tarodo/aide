import asyncio

from backend.core.settings import settings
from backend.db.uow import UnitOfWork
from backend.services.user import UserService


async def _ensure():
    if not settings.FIRST_SUPERUSER_EMAIL or not settings.FIRST_SUPERUSER_PASSWORD:
        print("Skip superuser bootstrap: FIRST_SUPERUSER_EMAIL/PASSWORD are not set.")
        return

    service = UserService()
    uow = UnitOfWork()
    user = await service.ensure_initial_superuser(
        uow=uow,
        email=settings.FIRST_SUPERUSER_EMAIL,
        password=settings.FIRST_SUPERUSER_PASSWORD,
        full_name=settings.FIRST_SUPERUSER_FULL_NAME,
    )
    print(f"Superuser created: {user.email}")
    print(f"Superuser is superuser: {user.is_superuser}")
    print(f"Superuser is active: {user.is_active}")
    print(f"Superuser created at: {user.created_at}")
    print(f"Superuser updated at: {user.updated_at}")
    print(f"Superuser created by: {user.created_by}")
    print(f"Superuser updated by: {user.updated_by}")


if __name__ == "__main__":
    asyncio.run(_ensure())
