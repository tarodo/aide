import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from backend.api.v1 import users as v1_users
from backend.db.uow import UnitOfWork
from backend.core.log_conf import setup_logging
from backend.core.settings import settings
from backend.services.exceptions import (
    UserAlreadyExistsError,
    UserNotFoundError,
)
from backend.services.user import UserService

setup_logging()

logger = structlog.get_logger(__name__)


async def _ensure_initial_superuser() -> None:
    if not settings.FIRST_SUPERUSER_EMAIL or not settings.FIRST_SUPERUSER_PASSWORD:
        logger.warning("FIRST_SUPERUSER_EMAIL or FIRST_SUPERUSER_PASSWORD not set")
        return

    user_service = UserService()
    uow = UnitOfWork()

    try:
        superuser = await user_service.ensure_initial_superuser(
            uow=uow,
            email=settings.FIRST_SUPERUSER_EMAIL,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            full_name=settings.FIRST_SUPERUSER_FULL_NAME,
        )
        logger.info("Initial superuser ready", email=superuser.email)
    except Exception:
        logger.exception(
            "Failed to ensure initial superuser",
            email=settings.FIRST_SUPERUSER_EMAIL,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _ensure_initial_superuser()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(UserNotFoundError)
async def user_not_found_exception_handler(request: Request, exc: UserNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": "User not found"},
    )


@app.exception_handler(UserAlreadyExistsError)
async def user_already_exists_exception_handler(
    request: Request, exc: UserAlreadyExistsError
):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "The user with this email already exists in the system."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get(settings.REQUEST_ID_HEADER, str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        user_agent=request.headers.get("user-agent"),
        referer=request.headers.get("referer"),
    )

    start_time = time.perf_counter()
    logger.info(
        "Request started",
        http_method=request.method,
        http_path=request.url.path,
        client_host=request.client.host if request.client else None,
    )

    try:
        response = await call_next(request)
        response.headers[settings.REQUEST_ID_HEADER] = request_id
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


api_v1_prefix = "/api/v1"
app.include_router(
    v1_users.router,
    prefix=f"{api_v1_prefix}/users",
    tags=["Users"],
)


@app.get("/")
async def root():
    logger.info("Root endpoint called")
    return {"message": "Hello World"}
