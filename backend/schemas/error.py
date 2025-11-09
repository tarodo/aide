"""
Pydantic schemas for standardized error responses.
"""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """
    Standardized JSON response format for application errors.
    """

    error_code: str
    detail: str
