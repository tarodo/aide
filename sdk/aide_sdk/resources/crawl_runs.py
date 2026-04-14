from uuid import UUID

from aide_schemas.crawl_run import CrawlRunCreate, CrawlRunRead, CrawlRunUpdate
from aide_sdk.resources.base import BaseResource


class CrawlRunsResource(BaseResource[CrawlRunCreate, CrawlRunRead, CrawlRunUpdate]):
    _path = "/api/v1/crawl-runs"
    _read_schema = CrawlRunRead

    async def delete(self, obj_id: UUID) -> CrawlRunRead:
        raise NotImplementedError("CrawlRun deletion is not supported (audit log)")
