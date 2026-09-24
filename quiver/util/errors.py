"""Error types with stable exit codes and actionable hints."""

from __future__ import annotations


class AimError(Exception):
    """Base error for all quiver failures.

    Attributes:
        exit_code: Process exit code the CLI should use.
        hint: Optional actionable hint shown to the user.
    """

    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class UsageError(AimError):
    """Invalid usage or invalid configuration value."""

    exit_code = 2


class NotFoundError(AimError):
    """Alias or file not found."""

    exit_code = 3


class UpdateFailedError(AimError):
    """An update could not be completed."""

    exit_code = 4


class VerificationError(UpdateFailedError):
    """A downloaded file failed verification."""


class NetworkError(AimError):
    """Network-level failure talking to an update source."""

    exit_code = 5


class CancelledError(AimError):
    """User declined a confirmation."""

    exit_code = 1
