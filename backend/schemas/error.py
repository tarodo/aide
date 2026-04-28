"""
Pydantic schemas for standardized error responses.
"""

from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """
    Standardized JSON response format for application errors.
    """

    error_code: str
    detail: str
    request_id: str | None = None
    details: dict[str, Any] | None = None
