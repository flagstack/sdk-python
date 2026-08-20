from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, cast

from .bucket import bucket
from .errors import EvaluationFailure
from .regex import compile_re2
from .semver import compare_semver
from .types import (
    Condition,
    ConfigurationFlag,
    EvaluationContext,
    EvaluationDetails,
    MatchMode,
    Outcome,
    Segment,
)
from .validation import validate_flag, validate_segment

T = TypeVar("T")
_MISSING = object()


def evaluate_flag(
    flag: ConfigurationFlag,
    environment_id: str,
    context: EvaluationContext | None = None,
    segments: Sequence[Segment] = (),
) -> EvaluationDetails[Any]:
    evaluation_context = context or {}
    try:
        validate_flag(flag, environment_id)
        segment_index: dict[str, Segment] = {}
        for segment in segments:
            validate_segment(segment)
            segment_index[segment.key] = segment

        if not flag.enabled:
            return EvaluationDetails(value=flag.default_value, variant="default", reason="DISABLED")

        for rule in flag.policy.rules:
            if not _match_conditions(rule.match, rule.conditions, evaluation_context, segment_index, set()):
                continue
            result = _resolve_outcome(flag, environment_id, rule.outcome, evaluation_context)
            return EvaluationDetails(
                value=result.value,
                variant=result.variant,
                reason="SPLIT" if rule.outcome.rollout else "TARGETING_MATCH",
                rule_id=rule.id,
            )

        fallthrough = flag.policy.fallthrough
        if _outcome_empty(fallthrough):
            if flag.kind == "boolean":
                return EvaluationDetails(value=True, variant="on", reason="STATIC")
            return EvaluationDetails(value=flag.default_value, variant="default", reason="DEFAULT")

        result = _resolve_outcome(flag, environment_id, fallthrough, evaluation_context)
        return EvaluationDetails(
            value=result.value,
            variant=result.variant,
            reason="SPLIT" if fallthrough.rollout else "STATIC",
        )
    except Exception as exc:
        failure = exc if isinstance(exc, EvaluationFailure) else EvaluationFailure("PARSE_ERROR", str(exc))
        return EvaluationDetails(
            value=flag.default_value,
            variant="default",
            reason="ERROR",
            error_code=failure.code,
            error_message=str(failure),
        )


def _resolve_outcome(
    flag: ConfigurationFlag,
    environment_id: str,
    outcome: Outcome,
    context: EvaluationContext,
) -> EvaluationDetails[Any]:
    if (outcome.variant or "").strip():
        assert outcome.variant is not None
        return EvaluationDetails(value=_variant_value(flag, outcome.variant), variant=outcome.variant, reason="STATIC")

    selected_bucket = bucket(environment_id, flag.id, _resolve_bucket_value(context, outcome.bucket_by))
    cumulative = 0
    for allocation in outcome.rollout:
        cumulative += allocation.weight
        if selected_bucket < cumulative:
            return EvaluationDetails(
                value=_variant_value(flag, allocation.variant),
                variant=allocation.variant,
                reason="SPLIT",
            )
    raise EvaluationFailure("PARSE_ERROR", "rollout did not resolve a variant")


def _resolve_bucket_value(context: EvaluationContext, bucket_by: str | None) -> str:
    if not bucket_by or bucket_by == "targetingKey":
        targeting_key = context.get("targetingKey")
        if not isinstance(targeting_key, str) or not targeting_key:
            raise EvaluationFailure("TARGETING_KEY_MISSING", "targeting key is required for percentage rollout")
        return targeting_key

    value = _context_value(context, bucket_by)
    if value is _MISSING:
        raise EvaluationFailure("INVALID_CONTEXT", f"bucket attribute {bucket_by!r} is missing")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise EvaluationFailure("INVALID_CONTEXT", f"bucket attribute {bucket_by!r} must be a finite number")
        return _json_number(value)
    raise EvaluationFailure(
        "INVALID_CONTEXT",
        f"bucket attribute {bucket_by!r} must be a scalar string, boolean or number",
    )


def _variant_value(flag: ConfigurationFlag, key: str) -> Any:
    if key == "default":
        return flag.default_value
    if flag.kind == "boolean" and key == "on":
        return True
    if flag.kind == "boolean" and key == "off":
        return False
    for variant in flag.variants:
        if variant.key == key:
            return variant.value
    raise EvaluationFailure("PARSE_ERROR", f"unknown variant {key!r}")


def _match_conditions(
    mode: MatchMode,
    conditions: Sequence[Condition],
    context: EvaluationContext,
    segments: Mapping[str, Segment],
    visiting: set[str],
) -> bool:
    matches = (_condition_matches(condition, context, segments, visiting) for condition in conditions)
    return any(matches) if mode == "any" else all(matches)


def _condition_matches(
    condition: Condition,
    context: EvaluationContext,
    segments: Mapping[str, Segment],
    visiting: set[str],
) -> bool:
    if condition.operator in {"in_segment", "not_in_segment"}:
        if not isinstance(condition.value, str):
            raise EvaluationFailure("PARSE_ERROR", "segment condition must reference a string key")
        matched = _match_segment(condition.value, context, segments, visiting)
        return not matched if condition.operator == "not_in_segment" else matched

    actual = _context_value(context, condition.attribute or "")
    if condition.operator == "exists":
        return actual is not _MISSING
    if condition.operator == "not_exists":
        return actual is _MISSING
    if actual is _MISSING:
        return False

    expected = condition.value
    if condition.operator == "equals":
        return _equal_values(actual, expected)
    if condition.operator == "not_equals":
        return not _equal_values(actual, expected)
    if condition.operator in {"in", "not_in"}:
        if not isinstance(expected, list):
            raise EvaluationFailure("PARSE_ERROR", f"{condition.operator} expects an array")
        matched = any(_equal_values(actual, candidate) for candidate in expected)
        return not matched if condition.operator == "not_in" else matched
    if condition.operator in {"contains", "not_contains"}:
        matched = _contains_value(actual, expected)
        return not matched if condition.operator == "not_contains" else matched
    if condition.operator == "starts_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.startswith(expected)
    if condition.operator == "ends_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.endswith(expected)
    if condition.operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
        if not _is_number(actual) or not _is_number(expected):
            return False
        if condition.operator == "greater_than":
            return actual > expected
        if condition.operator == "greater_than_or_equal":
            return actual >= expected
        if condition.operator == "less_than":
            return actual < expected
        return actual <= expected
    if condition.operator == "matches_regex":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        return compile_re2(expected).search(actual) is not None
    if condition.operator.startswith("semver_"):
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        comparison = compare_semver(actual, expected)
        if comparison is None:
            return False
        if condition.operator == "semver_greater_than":
            return comparison > 0
        if condition.operator == "semver_greater_than_or_equal":
            return comparison >= 0
        if condition.operator == "semver_less_than":
            return comparison < 0
        return comparison <= 0
    raise EvaluationFailure("PARSE_ERROR", f"unsupported operator {condition.operator!r}")


def _match_segment(
    key: str,
    context: EvaluationContext,
    segments: Mapping[str, Segment],
    visiting: set[str],
) -> bool:
    segment = segments.get(key)
    if segment is None:
        return False
    if key in visiting:
        raise EvaluationFailure("PARSE_ERROR", f"segment cycle detected at {key!r}")
    visiting.add(key)
    try:
        return _match_conditions(segment.match, segment.conditions, context, segments, visiting)
    finally:
        visiting.remove(key)


def _context_value(context: EvaluationContext, path: str) -> Any:
    if path == "targetingKey":
        value = context.get("targetingKey", _MISSING)
        return value if isinstance(value, str) and value else _MISSING
    if not path:
        return _MISSING
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _contains_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str):
        return isinstance(expected, str) and expected in actual
    if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
        return any(_equal_values(candidate, expected) for candidate in actual)
    if isinstance(actual, Mapping):
        return isinstance(expected, str) and expected in actual
    return False


def _equal_values(left: Any, right: Any) -> bool:
    if _is_number(left) and _is_number(right):
        return cast(float, left) == cast(float, right)
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        if set(left) != set(right):
            return False
        return all(_equal_values(left[key], right[key]) for key in left)
    if isinstance(left, Sequence) and not isinstance(left, (str, bytes, bytearray)):
        return len(left) == len(right) and all(_equal_values(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _outcome_empty(outcome: Outcome) -> bool:
    return not (outcome.variant or "").strip() and not outcome.rollout


def _json_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if value == 0.0:
        return "-0" if math.copysign(1.0, value) < 0 else "0"

    raw = repr(value).lower()
    absolute = abs(value)
    if absolute < 1e-6 or absolute >= 1e21:
        if "e" not in raw:
            raw = format(value, ".17e")
            coefficient, exponent = raw.split("e", 1)
            coefficient = coefficient.rstrip("0").rstrip(".")
            raw = f"{coefficient}e{exponent}"
        coefficient, exponent = raw.split("e", 1)
        sign = "+" if exponent.startswith("+") else "-" if exponent.startswith("-") else ""
        digits = exponent.lstrip("+-0") or "0"
        return f"{coefficient}e{sign}{digits}"

    if "e" not in raw:
        return raw[:-2] if raw.endswith(".0") else raw

    coefficient, exponent_text = raw.split("e", 1)
    exponent = int(exponent_text)
    negative = coefficient.startswith("-")
    digits = coefficient.lstrip("-").replace(".", "")
    decimal_position = coefficient.lstrip("-").find(".")
    integer_digits = decimal_position if decimal_position >= 0 else len(digits)
    target_position = integer_digits + exponent
    if target_position <= 0:
        rendered = "0." + ("0" * -target_position) + digits
    elif target_position >= len(digits):
        rendered = digits + ("0" * (target_position - len(digits)))
    else:
        rendered = digits[:target_position] + "." + digits[target_position:]
    return ("-" if negative else "") + rendered


def _json_string(value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (
        encoded.replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("&", r"\u0026")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )
