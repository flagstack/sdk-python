from __future__ import annotations

import math

from .errors import EvaluationFailure
from .regex import compile_re2
from .semver import compare_semver
from .types import (
    BUCKET_SCALE,
    Condition,
    Configuration,
    ConfigurationFlag,
    Outcome,
    Segment,
)

_SUPPORTED_OPERATORS = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
    "exists",
    "not_exists",
    "matches_regex",
    "semver_greater_than",
    "semver_greater_than_or_equal",
    "semver_less_than",
    "semver_less_than_or_equal",
    "in_segment",
    "not_in_segment",
}


def validate_evaluation_configuration(configuration: Configuration) -> None:
    for segment in configuration.segments:
        validate_segment(segment)
    for flag in configuration.flags:
        validate_flag(flag, configuration.environment.id)


def validate_flag(flag: ConfigurationFlag, environment_id: str) -> None:
    if not flag.id.strip() or not environment_id.strip():
        raise EvaluationFailure("PARSE_ERROR", "flag and environment IDs are required")
    _validate_value_kind(flag.kind, flag.default_value)

    allowed = {"default"}
    if flag.kind == "boolean":
        allowed.update({"on", "off"})
    for variant in flag.variants:
        key = variant.key.strip()
        if not key:
            raise EvaluationFailure("PARSE_ERROR", "variant key is required")
        if key in allowed:
            raise EvaluationFailure("PARSE_ERROR", f"variant key {key!r} is reserved or duplicated")
        _validate_value_kind(flag.kind, variant.value)
        allowed.add(key)

    seen_rules: set[str] = set()
    for rule in flag.policy.rules:
        if not rule.id.strip():
            raise EvaluationFailure("PARSE_ERROR", "rule ID is required")
        if rule.id in seen_rules:
            raise EvaluationFailure("PARSE_ERROR", f"duplicate rule ID {rule.id!r}")
        seen_rules.add(rule.id)
        _validate_match_mode(rule.match)
        if not rule.conditions:
            raise EvaluationFailure("PARSE_ERROR", f"rule {rule.id!r} must contain at least one condition")
        for condition in rule.conditions:
            _validate_condition(condition)
        _validate_outcome(rule.outcome, allowed, required=True)
    _validate_outcome(flag.policy.fallthrough, allowed, required=False)


def validate_segment(segment: Segment) -> None:
    if not segment.key.strip():
        raise EvaluationFailure("PARSE_ERROR", "segment key is required")
    _validate_match_mode(segment.match)
    if not segment.conditions:
        raise EvaluationFailure("PARSE_ERROR", f"segment {segment.key!r} must contain at least one condition")
    for condition in segment.conditions:
        _validate_condition(condition)


def _validate_condition(condition: Condition) -> None:
    if condition.operator not in _SUPPORTED_OPERATORS:
        raise EvaluationFailure("PARSE_ERROR", f"unsupported operator {condition.operator!r}")

    if condition.operator in {"in_segment", "not_in_segment"}:
        if not isinstance(condition.value, str) or not condition.value.strip():
            raise EvaluationFailure("PARSE_ERROR", "segment reference must be a non-empty string")
        return
    if condition.operator in {"exists", "not_exists"}:
        if not (condition.attribute or "").strip():
            raise EvaluationFailure("PARSE_ERROR", "condition attribute is required")
        return
    if not (condition.attribute or "").strip():
        raise EvaluationFailure("PARSE_ERROR", "condition attribute is required")
    if not condition.has_value:
        raise EvaluationFailure("PARSE_ERROR", "condition value is required")

    if condition.operator in {"in", "not_in"} and not isinstance(condition.value, list):
        raise EvaluationFailure("PARSE_ERROR", f"{condition.operator} condition value must be an array")
    if condition.operator == "matches_regex":
        if not isinstance(condition.value, str):
            raise EvaluationFailure("PARSE_ERROR", "regex condition value must be a string")
        compile_re2(condition.value)
    if condition.operator.startswith("semver_"):
        if not isinstance(condition.value, str) or compare_semver(condition.value, condition.value) is None:
            raise EvaluationFailure("PARSE_ERROR", "semantic-version condition value must be a valid semantic version")


def _validate_outcome(outcome: Outcome, allowed: set[str], *, required: bool) -> None:
    has_variant = bool((outcome.variant or "").strip())
    has_rollout = bool(outcome.rollout)
    if has_variant and has_rollout:
        raise EvaluationFailure("PARSE_ERROR", "outcome cannot contain both a variant and a rollout")
    if not has_variant and not has_rollout:
        if required:
            raise EvaluationFailure("PARSE_ERROR", "outcome must contain a variant or rollout")
        return
    if has_variant:
        assert outcome.variant is not None
        if outcome.variant not in allowed:
            raise EvaluationFailure("PARSE_ERROR", f"unknown variant {outcome.variant!r}")
        return

    total = 0
    for allocation in outcome.rollout:
        if allocation.variant not in allowed:
            raise EvaluationFailure("PARSE_ERROR", f"unknown rollout variant {allocation.variant!r}")
        if isinstance(allocation.weight, bool) or allocation.weight <= 0:
            raise EvaluationFailure("PARSE_ERROR", "rollout weights must be positive integers")
        total += allocation.weight
    if total != BUCKET_SCALE:
        raise EvaluationFailure("PARSE_ERROR", f"rollout weights must total {BUCKET_SCALE}")


def _validate_match_mode(mode: str) -> None:
    if mode not in {"all", "any"}:
        raise EvaluationFailure("PARSE_ERROR", 'match mode must be "all" or "any"')


def _validate_value_kind(kind: str, value: object) -> None:
    if kind == "boolean" and not isinstance(value, bool):
        raise EvaluationFailure("PARSE_ERROR", "value must be a boolean")
    if kind == "string" and not isinstance(value, str):
        raise EvaluationFailure("PARSE_ERROR", "value must be a string")
    if kind == "number" and (
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
    ):
        raise EvaluationFailure("PARSE_ERROR", "value must be a number")
