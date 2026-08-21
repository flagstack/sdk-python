from __future__ import annotations

from .types import EvaluationErrorCode


class SwitchOnYourCodeError(Exception):
    """Base exception for Switch On Your Code SDK failures."""


class SwitchOnYourCodeAuthenticationError(SwitchOnYourCodeError):
    """Raised when an SDK credential is rejected."""


class SwitchOnYourCodeHTTPError(SwitchOnYourCodeError):
    """Raised for unexpected HTTP responses from Switch On Your Code."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class SwitchOnYourCodeConfigurationError(SwitchOnYourCodeError):
    """Raised when a downloaded configuration is invalid or unsupported."""


class SwitchOnYourCodeRealtimeError(SwitchOnYourCodeError):
    """Raised when the realtime event stream is invalid or unusable."""


class EvaluationFailure(Exception):
    def __init__(self, code: EvaluationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
