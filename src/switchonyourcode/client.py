from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from types import TracebackType
from typing import Any, Literal, TypeVar, cast

from .config import parse_configuration
from .errors import (
    SwitchOnYourCodeAuthenticationError,
    SwitchOnYourCodeConfigurationError,
    SwitchOnYourCodeHTTPError,
)
from .evaluator import evaluate_flag
from .realtime import SwitchOnYourCodeRealtimeStream
from .types import Configuration, EvaluationContext, EvaluationDetails, FlagKind

RefreshResult = Literal["updated", "not-modified"]
T = TypeVar("T")
_SERVER_KEY_PREFIX = "syoc_server_"
_DEFAULT_FALLBACK_POLL_INTERVAL = 5 * 60.0


class SwitchOnYourCodeClient:
    def __init__(
        self,
        *,
        base_url: str,
        server_key: str,
        poll_interval: float = _DEFAULT_FALLBACK_POLL_INTERVAL,
        timeout: float = 10.0,
        realtime_reconnect_delay: float = 5.0,
        realtime_timeout: float = 30.0,
        opener: Callable[..., Any] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_configuration_changed: Callable[[Configuration], None] | None = None,
    ) -> None:
        normalized_url = base_url.strip().rstrip("/")
        normalized_key = server_key.strip()
        if not normalized_url:
            raise ValueError("Switch On Your Code base_url is required.")
        if not normalized_key.startswith(_SERVER_KEY_PREFIX):
            raise ValueError("Python SDK requires a Switch On Your Code server key (syoc_server_...).")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive.")
        if timeout <= 0:
            raise ValueError("timeout must be positive.")

        self._base_url = normalized_url
        self._server_key = normalized_key
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen
        self._on_error = on_error
        self._on_configuration_changed = on_configuration_changed
        self._configuration: Configuration | None = None
        self._etag: str | None = None
        self._flags: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._realtime = SwitchOnYourCodeRealtimeStream(
            base_url=normalized_url,
            server_key=normalized_key,
            opener=self._opener,
            reconnect_delay=realtime_reconnect_delay,
            timeout=realtime_timeout,
            on_configuration_changed=self.refresh,
            on_error=on_error,
        )

    @property
    def configuration(self) -> Configuration | None:
        with self._lock:
            return self._configuration

    @property
    def etag(self) -> str | None:
        with self._lock:
            return self._etag

    @property
    def ready(self) -> bool:
        return self.configuration is not None

    @property
    def realtime_running(self) -> bool:
        return self._realtime.running

    def initialize(
        self,
        *,
        start_polling: bool = True,
        start_realtime: bool = True,
    ) -> RefreshResult:
        result = self.refresh()
        if start_realtime:
            self.start_realtime()
        if start_polling:
            self.start_polling()
        return result

    def refresh(self) -> RefreshResult:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._server_key}",
        }
        with self._lock:
            if self._etag:
                headers["If-None-Match"] = self._etag

        request = urllib.request.Request(
            f"{self._base_url}/sdk/v1/config",
            headers=headers,
            method="GET",
        )
        try:
            response = self._opener(request, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                if self.configuration is None:
                    raise SwitchOnYourCodeConfigurationError(
                        "Switch On Your Code returned 304 before any configuration was loaded."
                    ) from exc
                return "not-modified"
            if exc.code == 401:
                raise SwitchOnYourCodeAuthenticationError("Switch On Your Code SDK credential was rejected.") from exc
            raise SwitchOnYourCodeHTTPError(
                exc.code,
                f"Switch On Your Code configuration request failed with HTTP {exc.code}.",
            ) from exc
        except urllib.error.URLError as exc:
            raise SwitchOnYourCodeHTTPError(
                0,
                f"Switch On Your Code configuration request failed: {exc.reason}",
            ) from exc

        try:
            status = getattr(response, "status", response.getcode())
            if status == 304:
                if self.configuration is None:
                    raise SwitchOnYourCodeConfigurationError(
                        "Switch On Your Code returned 304 before any configuration was loaded."
                    )
                return "not-modified"
            if status == 401:
                raise SwitchOnYourCodeAuthenticationError("Switch On Your Code SDK credential was rejected.")
            if status < 200 or status >= 300:
                raise SwitchOnYourCodeHTTPError(
                    status,
                    f"Switch On Your Code configuration request failed with HTTP {status}.",
                )
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SwitchOnYourCodeConfigurationError(
                    f"Switch On Your Code configuration response was not valid JSON: {exc}"
                ) from exc
            configuration = parse_configuration(payload)
            etag = response.headers.get("ETag")
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        with self._lock:
            self._configuration = configuration
            self._flags = {flag.key: flag for flag in configuration.flags}
            self._etag = etag
        if self._on_configuration_changed is not None:
            self._on_configuration_changed(configuration)
        return "updated"

    def start_polling(self) -> None:
        with self._lock:
            if self._poll_thread is not None and self._poll_thread.is_alive():
                return
            self._poll_stop.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="switchonyourcode-config-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def stop_polling(self) -> None:
        with self._lock:
            thread = self._poll_thread
            self._poll_thread = None
            self._poll_stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=min(self._poll_interval + self._timeout, 1.0))

    def start_realtime(self) -> None:
        self._realtime.start()

    def stop_realtime(self) -> None:
        self._realtime.stop()

    def close(self) -> None:
        self.stop_realtime()
        self.stop_polling()

    def __enter__(self) -> SwitchOnYourCodeClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def get_boolean_value(
        self, key: str, fallback: bool, context: EvaluationContext | None = None
    ) -> bool:
        return self.get_boolean_details(key, fallback, context).value

    def get_boolean_details(
        self, key: str, fallback: bool, context: EvaluationContext | None = None
    ) -> EvaluationDetails[bool]:
        return self._evaluate_typed(key, "boolean", fallback, context)

    def get_string_value(
        self, key: str, fallback: str, context: EvaluationContext | None = None
    ) -> str:
        return self.get_string_details(key, fallback, context).value

    def get_string_details(
        self, key: str, fallback: str, context: EvaluationContext | None = None
    ) -> EvaluationDetails[str]:
        return self._evaluate_typed(key, "string", fallback, context)

    def get_number_value(
        self, key: str, fallback: float, context: EvaluationContext | None = None
    ) -> float:
        return self.get_number_details(key, fallback, context).value

    def get_number_details(
        self, key: str, fallback: float, context: EvaluationContext | None = None
    ) -> EvaluationDetails[float]:
        return self._evaluate_typed(key, "number", fallback, context)

    def get_json_value(
        self, key: str, fallback: T, context: EvaluationContext | None = None
    ) -> T:
        return self.get_json_details(key, fallback, context).value

    def get_json_details(
        self, key: str, fallback: T, context: EvaluationContext | None = None
    ) -> EvaluationDetails[T]:
        return self._evaluate_typed(key, "json", fallback, context)

    def _evaluate_typed(
        self,
        key: str,
        expected_kind: FlagKind,
        fallback: T,
        context: EvaluationContext | None,
    ) -> EvaluationDetails[T]:
        with self._lock:
            configuration = self._configuration
            flag = self._flags.get(key)
        if configuration is None:
            return _fallback_details(
                fallback,
                "PROVIDER_NOT_READY",
                "Switch On Your Code configuration has not been loaded yet.",
            )
        if flag is None:
            return _fallback_details(
                fallback,
                "FLAG_NOT_FOUND",
                f"Feature flag {key!r} was not found.",
            )
        if flag.kind != expected_kind:
            return _fallback_details(
                fallback,
                "TYPE_MISMATCH",
                f"Feature flag {key!r} is {flag.kind}, not {expected_kind}.",
            )
        return cast(
            EvaluationDetails[T],
            evaluate_flag(flag, configuration.environment.id, context, configuration.segments),
        )

    def _poll_loop(self) -> None:
        while not self._poll_stop.wait(self._poll_interval):
            try:
                self.refresh()
            except BaseException as exc:
                if self._on_error is not None:
                    self._on_error(exc)


def _fallback_details(
    fallback: T,
    code: Literal["PROVIDER_NOT_READY", "FLAG_NOT_FOUND", "TYPE_MISMATCH"],
    message: str,
) -> EvaluationDetails[T]:
    return EvaluationDetails(
        value=fallback,
        variant="default",
        reason="ERROR",
        error_code=code,
        error_message=message,
    )
