from backend.models import User
from backend.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User
