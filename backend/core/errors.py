"""
A central registry of all application-specific error codes.

This module defines unique, machine-readable error codes that can be used
throughout the application for consistent error handling and reporting.
Each error code is associated with a default HTTP status code and a
user-facing detail message.
"""

from collections import defaultdict
from typing import Any, Dict, Iterable, Protocol, Tuple, Type, cast

from fastapi import status
from pydantic import BaseModel

# Error code constants
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
USER_NOT_FOUND = "USER_NOT_FOUND"
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
SYSTEM_KIND_NOT_FOUND = "SYSTEM_KIND_NOT_FOUND"
SYSTEM_KIND_ALREADY_EXISTS = "SYSTEM_KIND_ALREADY_EXISTS"
SYSTEM_FLAVOR_NOT_FOUND = "SYSTEM_FLAVOR_NOT_FOUND"
SYSTEM_FLAVOR_ALREADY_EXISTS = "SYSTEM_FLAVOR_ALREADY_EXISTS"
DATA_TYPE_NOT_FOUND = "DATA_TYPE_NOT_FOUND"
DATA_TYPE_ALREADY_EXISTS = "DATA_TYPE_ALREADY_EXISTS"
CREDENTIAL_REF_NOT_FOUND = "CREDENTIAL_REF_NOT_FOUND"
CREDENTIAL_REF_ALREADY_EXISTS = "CREDENTIAL_REF_ALREADY_EXISTS"
SYSTEM_NOT_FOUND = "SYSTEM_NOT_FOUND"
SYSTEM_ALREADY_EXISTS = "SYSTEM_ALREADY_EXISTS"
DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
DATASET_ALREADY_EXISTS = "DATASET_ALREADY_EXISTS"
INVALID_DATASET_KIND = "INVALID_DATASET_KIND"
DATASET_KIND_MISMATCH = "DATASET_KIND_MISMATCH"
CAST_RULE_NOT_FOUND = "CAST_RULE_NOT_FOUND"
CAST_RULE_ALREADY_EXISTS = "CAST_RULE_ALREADY_EXISTS"

ErrorInfo = Tuple[int, str]


class ResponsesMapping(Protocol):
    def keys(self) -> Iterable[int | str]: ...

    def __getitem__(self, __key: int | str) -> Dict[str, Any]: ...


# Mapping of error codes to (HTTP Status Code, Detail Message)
ERROR_MAP = {
    UNAUTHORIZED: (
        status.HTTP_401_UNAUTHORIZED,
        "Unauthorized.",
    ),
    FORBIDDEN: (
        status.HTTP_403_FORBIDDEN,
        "Forbidden.",
    ),
    USER_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested user was not found.",
    ),
    INVALID_CREDENTIALS: (
        status.HTTP_401_UNAUTHORIZED,
        "Incorrect email or password.",
    ),
    USER_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A user with this email already exists.",
    ),
    SYSTEM_KIND_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested system kind was not found.",
    ),
    SYSTEM_KIND_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A system kind with this code already exists.",
    ),
    SYSTEM_FLAVOR_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested system flavor was not found.",
    ),
    SYSTEM_FLAVOR_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A system flavor with this code already exists.",
    ),
    DATA_TYPE_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested data type was not found.",
    ),
    DATA_TYPE_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A data type with this code already exists for the given system flavor.",
    ),
    CREDENTIAL_REF_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested credential reference was not found.",
    ),
    CREDENTIAL_REF_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A credential reference with this provider and path already exists.",
    ),
    SYSTEM_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested system was not found.",
    ),
    SYSTEM_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A system with this code already exists.",
    ),
    DATASET_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested dataset was not found.",
    ),
    DATASET_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A dataset with this system and object name already exists.",
    ),
    INVALID_DATASET_KIND: (
        status.HTTP_400_BAD_REQUEST,
        "The provided dataset kind is invalid.",
    ),
    DATASET_KIND_MISMATCH: (
        status.HTTP_400_BAD_REQUEST,
        "Changing the kind of a dataset is not allowed.",
    ),
    CAST_RULE_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested cast rule was not found.",
    ),
    CAST_RULE_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A cast rule with this source and target data type already exists.",
    ),
}


def build_error_responses(
    *error_codes: str,
    error_schema: Type[BaseModel] | None = None,
) -> ResponsesMapping:
    """
    Turn a list of registered error codes into a FastAPI `responses` mapping.

    Args:
        *error_codes: Error codes defined in `ERROR_MAP`.
        error_schema: Optional Pydantic schema to use for the response model.
            Defaults to `backend.schemas.error.ErrorResponse`.

    Returns:
        Dict[int, Dict[str, Any]]: A mapping suitable for FastAPI route
            declarations (status code -> response metadata).
    """

    if not error_codes:
        return {}

    if error_schema is None:
        from backend.schemas.error import ErrorResponse as DefaultErrorResponse

        error_schema = DefaultErrorResponse

    grouped: Dict[int, list[tuple[str, ErrorInfo]]] = defaultdict(list)
    for code in error_codes:
        if code not in ERROR_MAP:
            raise KeyError(
                f"Unknown error code '{code}'. Register it in ERROR_MAP first."
            )
        grouped[ERROR_MAP[code][0]].append((code, ERROR_MAP[code]))

    responses: Dict[int, Dict[str, Any]] = {}
    for status_code, items in grouped.items():
        description = (
            items[0][1][1]
            if len(items) == 1
            else " | ".join(f"{code}: {detail}" for code, (_, detail) in items)
        )
        examples = {
            code: {
                "summary": code,
                "value": {"error_code": code, "detail": detail},
            }
            for code, (_, detail) in items
        }
        responses[status_code] = {
            "model": error_schema,
            "description": description,
            "content": {
                "application/json": {
                    "examples": examples,
                },
            },
        }

    return cast(ResponsesMapping, responses)
