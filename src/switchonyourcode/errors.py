from __future__ import annotations

from .types import EvaluationErrorCode


class SwitchOnYourCodeError(Exception):
    """Base exception for SwitchOnYourCode SDK failures."""


class SwitchOnYourCodeAuthenticationError(SwitchOnYourCodeError):
    """Raised when an SDK credential is rejected."""


class SwitchOnYourCodeHTTPError(SwitchOnYourCodeError):
    """Raised for unexpected HTTP responses from SwitchOnYourCode."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class SwitchOnYourCodeConfigurationError(SwitchOnYourCodeError):
    """Raised when a downloaded configuration is invalid or unsupported."""


class EvaluationFailure(Exception):
    def __init__(self, code: EvaluationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
