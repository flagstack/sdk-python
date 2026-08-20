from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Mapping, TypeVar

SCHEMA_VERSION = 1
BUCKET_SCALE = 100_000

FlagKind = Literal["boolean", "string", "number", "json"]
MatchMode = Literal["all", "any"]
EvaluationReason = Literal[
    "STATIC",
    "DEFAULT",
    "TARGETING_MATCH",
    "SPLIT",
    "DISABLED",
    "ERROR",
]
EvaluationErrorCode = Literal[
    "PARSE_ERROR",
    "TARGETING_KEY_MISSING",
    "INVALID_CONTEXT",
    "PROVIDER_NOT_READY",
    "FLAG_NOT_FOUND",
    "TYPE_MISMATCH",
]

T = TypeVar("T")
EvaluationContext = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Variant:
    key: str
    value: Any


@dataclass(frozen=True, slots=True)
class Condition:
    operator: str
    attribute: str | None = None
    value: Any = None
    has_value: bool = False


@dataclass(frozen=True, slots=True)
class Allocation:
    variant: str
    weight: int


@dataclass(frozen=True, slots=True)
class Outcome:
    variant: str | None = None
    rollout: tuple[Allocation, ...] = ()
    bucket_by: str | None = None


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    match: MatchMode
    conditions: tuple[Condition, ...]
    outcome: Outcome
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Policy:
    rules: tuple[Rule, ...] = ()
    fallthrough: Outcome = field(default_factory=Outcome)


@dataclass(frozen=True, slots=True)
class Segment:
    key: str
    name: str
    match: MatchMode
    conditions: tuple[Condition, ...]


@dataclass(frozen=True, slots=True)
class ConfigurationEnvironment:
    id: str
    key: str


@dataclass(frozen=True, slots=True)
class ConfigurationFlag:
    id: str
    key: str
    kind: FlagKind
    default_value: Any
    enabled: bool
    variants: tuple[Variant, ...]
    policy: Policy
    revision: int


@dataclass(frozen=True, slots=True)
class Configuration:
    schema_version: Literal[1]
    environment: ConfigurationEnvironment
    flags: tuple[ConfigurationFlag, ...]
    segments: tuple[Segment, ...]


@dataclass(frozen=True, slots=True)
class EvaluationDetails(Generic[T]):
    value: T
    variant: str
    reason: EvaluationReason
    rule_id: str | None = None
    error_code: EvaluationErrorCode | None = None
    error_message: str | None = None
