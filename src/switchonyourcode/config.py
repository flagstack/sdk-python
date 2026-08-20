from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from .errors import SwitchOnYourCodeConfigurationError
from .types import (
    SCHEMA_VERSION,
    Allocation,
    Condition,
    Configuration,
    ConfigurationEnvironment,
    ConfigurationFlag,
    FlagKind,
    MatchMode,
    Outcome,
    Policy,
    Rule,
    Segment,
    Variant,
)
from .validation import validate_evaluation_configuration


def parse_configuration(payload: object) -> Configuration:
    root = _record(payload, "SwitchOnYourCode configuration must be an object.")
    if root.get("schema_version") != SCHEMA_VERSION:
        raise SwitchOnYourCodeConfigurationError(
            f"Unsupported SwitchOnYourCode schema version {root.get('schema_version')!r}."
        )

    environment_raw = _record(root.get("environment"), "SwitchOnYourCode configuration environment is invalid.")
    environment_id = _non_empty_string(environment_raw.get("id"), "SwitchOnYourCode environment id is invalid.")
    environment_key = _non_empty_string(environment_raw.get("key"), "SwitchOnYourCode environment key is invalid.")

    flags_raw = root.get("flags")
    segments_raw = root.get("segments")
    if not isinstance(flags_raw, list) or not isinstance(segments_raw, list):
        raise SwitchOnYourCodeConfigurationError("SwitchOnYourCode configuration flags and segments must be arrays.")

    configuration = Configuration(
        schema_version=SCHEMA_VERSION,
        environment=ConfigurationEnvironment(id=environment_id, key=environment_key),
        flags=tuple(_parse_flag(value) for value in flags_raw),
        segments=tuple(_parse_segment(value) for value in segments_raw),
    )
    try:
        validate_evaluation_configuration(configuration)
    except Exception as exc:
        raise SwitchOnYourCodeConfigurationError(
            f"SwitchOnYourCode configuration is not compatible with the v1 evaluator: {exc}"
        ) from exc
    return configuration


def _parse_flag(value: object) -> ConfigurationFlag:
    data = _record(value, "Configuration contains an invalid flag.")
    flag_id = _non_empty_string(data.get("id"), "Flag entry is missing a valid id.")
    key = _non_empty_string(data.get("key"), "Flag entry is missing a valid key.")
    kind = data.get("kind")
    if kind not in {"boolean", "string", "number", "json"}:
        raise SwitchOnYourCodeConfigurationError(f"Flag {key!r} has an invalid kind.")
    enabled = data.get("enabled")
    revision = data.get("revision")
    if not isinstance(enabled, bool) or isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise SwitchOnYourCodeConfigurationError(f"Flag {key!r} has invalid enabled state or revision.")
    if "default_value" not in data:
        raise SwitchOnYourCodeConfigurationError(f"Flag {key!r} is missing default_value.")
    variants_raw = data.get("variants")
    policy_raw = data.get("policy")
    if not isinstance(variants_raw, list) or not isinstance(policy_raw, Mapping):
        raise SwitchOnYourCodeConfigurationError(f"Flag {key!r} has invalid variants or policy.")

    variants: list[Variant] = []
    for raw_variant in variants_raw:
        variant = _record(raw_variant, f"Flag {key!r} contains an invalid variant.")
        variant_key = _non_empty_string(variant.get("key"), f"Flag {key!r} contains an invalid variant.")
        if "value" not in variant:
            raise SwitchOnYourCodeConfigurationError(f"Flag {key!r} contains an invalid variant.")
        variants.append(Variant(key=variant_key, value=variant["value"]))

    return ConfigurationFlag(
        id=flag_id,
        key=key,
        kind=cast(FlagKind, kind),
        default_value=data["default_value"],
        enabled=enabled,
        variants=tuple(variants),
        policy=_parse_policy(policy_raw),
        revision=revision,
    )


def _parse_policy(value: Mapping[str, Any]) -> Policy:
    rules_raw = value.get("rules", [])
    if not isinstance(rules_raw, list):
        raise SwitchOnYourCodeConfigurationError("Policy rules must be an array.")
    rules: list[Rule] = []
    for raw_rule in rules_raw:
        rule = _record(raw_rule, "Policy contains an invalid rule.")
        rule_id = _non_empty_string(rule.get("id"), "Policy contains an invalid rule.")
        match = rule.get("match")
        conditions_raw = rule.get("conditions")
        outcome_raw = rule.get("outcome")
        if match not in {"all", "any"} or not isinstance(conditions_raw, list) or not isinstance(outcome_raw, Mapping):
            raise SwitchOnYourCodeConfigurationError("Policy contains an invalid rule.")
        name = rule.get("name")
        if name is not None and not isinstance(name, str):
            raise SwitchOnYourCodeConfigurationError("Policy rule name must be a string.")
        rules.append(
            Rule(
                id=rule_id,
                name=name,
                match=cast(MatchMode, match),
                conditions=tuple(_parse_condition(condition) for condition in conditions_raw),
                outcome=_parse_outcome(outcome_raw),
            )
        )

    fallthrough_raw = value.get("fallthrough", {})
    if not isinstance(fallthrough_raw, Mapping):
        raise SwitchOnYourCodeConfigurationError("Policy fallthrough must be an object.")
    return Policy(rules=tuple(rules), fallthrough=_parse_outcome(fallthrough_raw))


def _parse_segment(value: object) -> Segment:
    data = _record(value, "Configuration contains an invalid segment.")
    key = _non_empty_string(data.get("key"), "Configuration contains an invalid segment.")
    name = data.get("name")
    match = data.get("match")
    conditions_raw = data.get("conditions")
    if not isinstance(name, str) or match not in {"all", "any"} or not isinstance(conditions_raw, list):
        raise SwitchOnYourCodeConfigurationError("Configuration contains an invalid segment.")
    return Segment(
        key=key,
        name=name,
        match=cast(MatchMode, match),
        conditions=tuple(_parse_condition(condition) for condition in conditions_raw),
    )


def _parse_condition(value: object) -> Condition:
    data = _record(value, "Configuration contains an invalid condition.")
    operator = data.get("operator")
    if not isinstance(operator, str):
        raise SwitchOnYourCodeConfigurationError("Configuration contains an invalid condition.")
    attribute = data.get("attribute")
    if attribute is not None and not isinstance(attribute, str):
        raise SwitchOnYourCodeConfigurationError("Condition attribute must be a string.")
    return Condition(
        operator=operator,
        attribute=attribute,
        value=data.get("value"),
        has_value="value" in data,
    )


def _parse_outcome(value: Mapping[str, Any]) -> Outcome:
    variant = value.get("variant")
    bucket_by = value.get("bucket_by")
    if variant is not None and not isinstance(variant, str):
        raise SwitchOnYourCodeConfigurationError("Outcome variant must be a string.")
    if bucket_by is not None and not isinstance(bucket_by, str):
        raise SwitchOnYourCodeConfigurationError("Outcome bucket_by must be a string.")

    rollout_raw = value.get("rollout", [])
    if not isinstance(rollout_raw, list):
        raise SwitchOnYourCodeConfigurationError("Outcome rollout must be an array.")
    rollout: list[Allocation] = []
    for raw_allocation in rollout_raw:
        allocation = _record(raw_allocation, "Outcome contains an invalid rollout allocation.")
        allocation_variant = _non_empty_string(
            allocation.get("variant"), "Outcome contains an invalid rollout allocation."
        )
        weight = allocation.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise SwitchOnYourCodeConfigurationError("Outcome contains an invalid rollout allocation.")
        rollout.append(Allocation(variant=allocation_variant, weight=weight))
    return Outcome(variant=variant, rollout=tuple(rollout), bucket_by=bucket_by)


def _record(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SwitchOnYourCodeConfigurationError(message)
    return cast(Mapping[str, Any], value)


def _non_empty_string(value: object, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SwitchOnYourCodeConfigurationError(message)
    return value
