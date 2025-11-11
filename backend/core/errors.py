"""
A central registry of all application-specific error codes.

This module defines unique, machine-readable error codes that can be used
throughout the application for consistent error handling and reporting.
Each error code is associated with a default HTTP status code and a
user-facing detail message.
"""

from fastapi import status

# Error code constants
USER_NOT_FOUND = "USER_NOT_FOUND"
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
SYSTEM_KIND_NOT_FOUND = "SYSTEM_KIND_NOT_FOUND"
SYSTEM_KIND_ALREADY_EXISTS = "SYSTEM_KIND_ALREADY_EXISTS"

# Mapping of error codes to (HTTP Status Code, Detail Message)
ERROR_MAP = {
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
}
