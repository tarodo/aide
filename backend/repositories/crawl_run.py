from backend.models.crawl_run import CrawlRun
from backend.repositories.base import BaseRepository


class CrawlRunRepository(BaseRepository[CrawlRun]):
    model = CrawlRun
