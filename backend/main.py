import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from backend.api.v1 import data_types as v1_data_types
from backend.api.v1 import credential_refs as v1_credential_refs
from backend.api.v1 import login as v1_login
from backend.api.v1 import system_flavors as v1_system_flavors
from backend.api.v1 import system_kinds as v1_system_kinds
from backend.api.v1 import systems as v1_systems
from backend.api.v1 import users as v1_users
from backend.core.errors import ERROR_MAP
from backend.core.exceptions import AppException
from backend.core.log_conf import setup_logging
from backend.core.settings import settings
from backend.db.uow import UnitOfWork
from backend.schemas.error import ErrorResponse
from backend.services.user import UserService

setup_logging()

logger = structlog.get_logger(__name__)


async def _ensure_initial_superuser() -> None:
    if not settings.FIRST_SUPERUSER_EMAIL or not settings.FIRST_SUPERUSER_PASSWORD:
        logger.warning("FIRST_SUPERUSER_EMAIL or FIRST_SUPERUSER_PASSWORD not set")
        return

    try:
        user_service = UserService()
        uow = UnitOfWork()
    except Exception:
        logger.exception("Failed to create user service or unit of work")
        return

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


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handles all custom application exceptions."""
    error_code = exc.error_code
    status_code, detail = ERROR_MAP.get(
        error_code,
        (status.HTTP_500_INTERNAL_SERVER_ERROR, "An internal error occurred"),
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error_code=error_code, detail=detail).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Handles any unhandled exceptions as a fallback."""
    logger.exception("Unhandled exception occurred", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            detail="An unexpected internal error occurred.",
        ).model_dump(),
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

app.include_router(
    v1_login.router,
    prefix=f"{api_v1_prefix}/login",
    tags=["Login"],
)

app.include_router(
    v1_system_kinds.router,
    prefix=f"{api_v1_prefix}/system-kinds",
    tags=["System Kinds"],
)

app.include_router(
    v1_system_flavors.router,
    prefix=f"{api_v1_prefix}/system-flavors",
    tags=["System Flavors"],
)

app.include_router(
    v1_data_types.router,
    prefix=f"{api_v1_prefix}/data-types",
    tags=["Data Types"],
)

app.include_router(
    v1_credential_refs.router,
    prefix=f"{api_v1_prefix}/credential-refs",
    tags=["Credential Refs"],
)

app.include_router(
    v1_systems.router,
    prefix=f"{api_v1_prefix}/systems",
    tags=["Systems"],
)


@app.get("/")
async def root():
    logger.info("Root endpoint called")
    return {"message": "Hello World"}
