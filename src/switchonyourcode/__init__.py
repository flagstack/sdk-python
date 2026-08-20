from .bucket import bucket
from .client import SwitchOnYourCodeClient, RefreshResult
from .config import parse_configuration
from .errors import (
    SwitchOnYourCodeAuthenticationError,
    SwitchOnYourCodeConfigurationError,
    SwitchOnYourCodeError,
    SwitchOnYourCodeHTTPError,
)
from .evaluator import evaluate_flag
from .types import (
    BUCKET_SCALE,
    SCHEMA_VERSION,
    Allocation,
    Condition,
    Configuration,
    ConfigurationEnvironment,
    ConfigurationFlag,
    EvaluationContext,
    EvaluationDetails,
    EvaluationErrorCode,
    EvaluationReason,
    FlagKind,
    Outcome,
    Policy,
    Rule,
    Segment,
    Variant,
)

__all__ = [
    "BUCKET_SCALE",
    "SCHEMA_VERSION",
    "Allocation",
    "Condition",
    "Configuration",
    "ConfigurationEnvironment",
    "ConfigurationFlag",
    "EvaluationContext",
    "EvaluationDetails",
    "EvaluationErrorCode",
    "EvaluationReason",
    "FlagKind",
    "SwitchOnYourCodeAuthenticationError",
    "SwitchOnYourCodeClient",
    "SwitchOnYourCodeConfigurationError",
    "SwitchOnYourCodeError",
    "SwitchOnYourCodeHTTPError",
    "Outcome",
    "Policy",
    "RefreshResult",
    "Rule",
    "Segment",
    "Variant",
    "bucket",
    "evaluate_flag",
    "parse_configuration",
]
