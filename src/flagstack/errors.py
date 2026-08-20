from __future__ import annotations

from .types import EvaluationErrorCode


class FlagStackError(Exception):
    """Base exception for FlagStack SDK failures."""


class FlagStackAuthenticationError(FlagStackError):
    """Raised when an SDK credential is rejected."""


class FlagStackHTTPError(FlagStackError):
    """Raised for unexpected HTTP responses from FlagStack."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class FlagStackConfigurationError(FlagStackError):
    """Raised when a downloaded configuration is invalid or unsupported."""


class EvaluationFailure(Exception):
    def __init__(self, code: EvaluationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
