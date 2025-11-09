"""
Custom application-level exceptions.
"""


class AppException(Exception):
    """
    Base class for all business logic exceptions in the application.

    Attributes:
        error_code (str): A unique, machine-readable error code.
    """

    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(f"Application Exception: {error_code}")
