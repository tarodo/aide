import time
import uuid
from fastapi import FastAPI, Request
import structlog

from backend.core.log_conf import setup_logging

setup_logging()

logger = structlog.get_logger(__name__)

app = FastAPI()


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start_time = time.perf_counter()
    logger.info(
        "Request started",
        http_method=request.method,
        http_path=request.url.path,
        client_host=request.client.host if request.client else None,
    )

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        process_time = time.perf_counter() - start_time
        logger.info(
            "Request finished",
            status_code=response.status_code,
            process_time=round(process_time, 4),
        )
        return response
    except Exception as exc:
        process_time = time.perf_counter() - start_time
        logger.error(
            "Request failed",
            exc_info=exc,
            process_time=round(process_time, 4),
        )
        raise


@app.get("/")
async def root():
    logger.info("Root endpoint called")
    return {"message": "Hello World"}
