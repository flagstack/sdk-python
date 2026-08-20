from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from openfeature.evaluation_context import EvaluationContext as OpenFeatureEvaluationContext
from openfeature.event import ProviderEventDetails
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import FlagResolutionDetails, Reason
from openfeature.provider import AbstractProvider, Metadata

from .client import SwitchOnYourCodeClient
from .types import Configuration, EvaluationContext, EvaluationDetails

T = TypeVar("T")


class SwitchOnYourCodeProvider(AbstractProvider):
    """OpenFeature provider backed by the SwitchOnYourCode Python SDK."""

    def __init__(
        self,
        *,
        base_url: str,
        server_key: str,
        poll_interval: float = 30.0,
        timeout: float = 10.0,
        start_polling: bool = True,
    ) -> None:
        super().__init__()
        self._start_polling = start_polling
        self._initialized = False
        self._last_configuration: Configuration | None = None
        self._client = SwitchOnYourCodeClient(
            base_url=base_url,
            server_key=server_key,
            poll_interval=poll_interval,
            timeout=timeout,
            on_configuration_changed=self._configuration_changed,
        )

    @property
    def client(self) -> SwitchOnYourCodeClient:
        return self._client

    def initialize(self, evaluation_context: OpenFeatureEvaluationContext) -> None:
        self._client.initialize(start_polling=self._start_polling)
        self._initialized = True

    def shutdown(self) -> None:
        self._initialized = False
        self._client.close()

    def get_metadata(self) -> Metadata:
        return Metadata(name="Switch On Your Code")

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: OpenFeatureEvaluationContext | None = None,
    ) -> FlagResolutionDetails[bool]:
        details = self._client.get_boolean_details(
            flag_key,
            default_value,
            _convert_context(evaluation_context),
        )
        return self._resolution(flag_key, details)

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: OpenFeatureEvaluationContext | None = None,
    ) -> FlagResolutionDetails[str]:
        details = self._client.get_string_details(
            flag_key,
            default_value,
            _convert_context(evaluation_context),
        )
        return self._resolution(flag_key, details)

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: OpenFeatureEvaluationContext | None = None,
    ) -> FlagResolutionDetails[int]:
        details = self._client.get_number_details(
            flag_key,
            default_value,
            _convert_context(evaluation_context),
        )
        if details.error_code is not None:
            return self._resolution(flag_key, details, value=default_value)
        value = details.value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return self._type_mismatch(flag_key, default_value, details, "integer")
        if isinstance(value, float) and not value.is_integer():
            return self._type_mismatch(flag_key, default_value, details, "integer")
        return self._resolution(flag_key, details, value=int(value))

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: OpenFeatureEvaluationContext | None = None,
    ) -> FlagResolutionDetails[float]:
        details = self._client.get_number_details(
            flag_key,
            default_value,
            _convert_context(evaluation_context),
        )
        if details.error_code is not None:
            return self._resolution(flag_key, details, value=default_value)
        value = details.value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return self._type_mismatch(flag_key, default_value, details, "float")
        return self._resolution(flag_key, details, value=float(value))

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Sequence[Any] | Mapping[str, Any],
        evaluation_context: OpenFeatureEvaluationContext | None = None,
    ) -> FlagResolutionDetails[Sequence[Any] | Mapping[str, Any]]:
        details = self._client.get_json_details(
            flag_key,
            default_value,
            _convert_context(evaluation_context),
        )
        if details.error_code is not None:
            return self._resolution(flag_key, details, value=default_value)
        value = details.value
        if not _is_openfeature_object(value):
            return self._type_mismatch(flag_key, default_value, details, "object")
        return self._resolution(flag_key, details, value=value)

    def _resolution(
        self,
        flag_key: str,
        details: EvaluationDetails[Any],
        *,
        value: T | None = None,
    ) -> FlagResolutionDetails[T]:
        resolved_value = details.value if value is None else value
        return FlagResolutionDetails(
            value=cast(T, resolved_value),
            variant=details.variant,
            reason=Reason(details.reason),
            error_code=ErrorCode(details.error_code) if details.error_code is not None else None,
            error_message=details.error_message,
            flag_metadata=self._flag_metadata(flag_key, details.rule_id),
        )

    def _type_mismatch(
        self,
        flag_key: str,
        default_value: T,
        details: EvaluationDetails[Any],
        expected: str,
    ) -> FlagResolutionDetails[T]:
        return FlagResolutionDetails(
            value=default_value,
            variant="default",
            reason=Reason.ERROR,
            error_code=ErrorCode.TYPE_MISMATCH,
            error_message=f"Feature flag {flag_key!r} did not resolve to an OpenFeature {expected} value.",
            flag_metadata=self._flag_metadata(flag_key, details.rule_id),
        )

    def _flag_metadata(self, flag_key: str, rule_id: str | None) -> dict[str, bool | int | float | str]:
        configuration = self._client.configuration
        if configuration is None:
            return {}
        flag = next((candidate for candidate in configuration.flags if candidate.key == flag_key), None)
        if flag is None:
            return {}
        metadata: dict[str, bool | int | float | str] = {
            "switchonyourcode.environment": configuration.environment.key,
            "switchonyourcode.environment_id": configuration.environment.id,
            "switchonyourcode.revision": flag.revision,
            "switchonyourcode.enabled": flag.enabled,
        }
        if rule_id is not None:
            metadata["switchonyourcode.rule_id"] = rule_id
        return metadata

    def _configuration_changed(self, configuration: Configuration) -> None:
        previous = self._last_configuration
        self._last_configuration = configuration
        if not self._initialized or previous is None:
            return
        previous_flags = {flag.key: flag for flag in previous.flags}
        current_flags = {flag.key: flag for flag in configuration.flags}
        changed = sorted(
            key
            for key in previous_flags.keys() | current_flags.keys()
            if previous_flags.get(key) != current_flags.get(key)
        )
        self.emit_provider_configuration_changed(
            ProviderEventDetails(
                flags_changed=changed,
                metadata={"switchonyourcode.environment": configuration.environment.key},
            )
        )


def _convert_context(context: OpenFeatureEvaluationContext | None) -> EvaluationContext:
    if context is None:
        return {}
    converted = {key: _convert_context_value(value) for key, value in context.attributes.items()}
    if context.targeting_key:
        converted["targetingKey"] = context.targeting_key
    return converted


def _convert_context_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {key: _convert_context_value(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_convert_context_value(nested) for nested in value]
    return value


def _is_openfeature_object(value: Any) -> bool:
    if isinstance(value, Mapping):
        return True
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
