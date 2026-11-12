"""Exceptions whose message is always safe to show to ordinary users."""


class AppError(Exception):
    """A friendly, user-safe error (the message can be shown on screen)."""


class ValidationError(AppError):
    """The user typed something that is not acceptable."""


class PermissionDenied(AppError):
    """The user is not allowed to do this."""


class NotFound(AppError):
    """The requested record does not exist (or is not visible to this user)."""


class DatabaseUnavailable(AppError):
    """The database could not be used right now (busy, locked or unreachable)."""
