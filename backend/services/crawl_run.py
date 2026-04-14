import uuid

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.crawl_run import CrawlRun
from backend.repositories.crawl_run import CrawlRunRepository
from backend.schemas.crawl_run import (
    CrawlRunCreate,
    CrawlRunRead,
    CrawlRunUpdate,
)
from backend.services.base import GenericService


class CrawlRunService(
    GenericService[CrawlRun, CrawlRunCreate, CrawlRunUpdate, CrawlRunRead]
):
    def __init__(self):
        super().__init__(
            model=CrawlRun,
            repository=CrawlRunRepository,
            read_schema=CrawlRunRead,
            not_found_error_code=errors.CRAWL_RUN_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: CrawlRunCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if not await uow.systems.get(obj_in.system_id):
            raise AppException(errors.SYSTEM_NOT_FOUND)
