"""
Custom exceptions for the service layer.
"""


class UserAlreadyExistsError(Exception):
    """Raised when trying to create a user that already exists."""

    pass


class UserNotFoundError(Exception):
    """Raised when a user is not found in the database."""

    pass
