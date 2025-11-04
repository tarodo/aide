from fastapi import FastAPI
import structlog

from backend.core.log_conf import setup_logging

setup_logging()

logger = structlog.get_logger(__name__)

app = FastAPI()


@app.get("/")
async def root():
    logger.info("Root endpoint called")
    return {"message": "Hello World"}
