"""
Custom application-level exceptions.
"""

from typing import Any


class AppException(Exception):
    """
    Base class for all business logic exceptions in the application.

    Attributes:
        error_code (str): A unique, machine-readable error code.
        details (dict[str, Any] | None): Optional structured payload surfaced
            in the JSON error response under the ``details`` key.
    """

    def __init__(
        self,
        error_code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.error_code = error_code
        self.details = details
        super().__init__(f"Application Exception: {error_code}")
