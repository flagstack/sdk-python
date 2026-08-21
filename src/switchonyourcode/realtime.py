from __future__ import annotations

import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

from .errors import (
    SwitchOnYourCodeAuthenticationError,
    SwitchOnYourCodeHTTPError,
    SwitchOnYourCodeRealtimeError,
)


class _ServerSentEvent:
    def __init__(self, event: str, data: str) -> None:
        self.event = event
        self.data = data


class SwitchOnYourCodeRealtimeStream:
    """Authenticated SSE invalidation stream for Switch On Your Code SDK clients."""

    def __init__(
        self,
        *,
        base_url: str,
        server_key: str,
        opener: Callable[..., Any] | None = None,
        reconnect_delay: float = 5.0,
        timeout: float = 30.0,
        on_configuration_changed: Callable[[], None],
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        normalized_url = base_url.strip().rstrip("/")
        normalized_key = server_key.strip()
        if not normalized_url:
            raise ValueError("Switch On Your Code realtime base_url is required.")
        if not normalized_key:
            raise ValueError("Switch On Your Code realtime server_key is required.")
        if reconnect_delay <= 0:
            raise ValueError("reconnect_delay must be positive.")
        if timeout <= 0:
            raise ValueError("realtime timeout must be positive.")

        self._base_url = normalized_url
        self._server_key = normalized_key
        self._opener = opener or urllib.request.urlopen
        self._default_reconnect_delay = reconnect_delay
        self._timeout = timeout
        self._on_configuration_changed = on_configuration_changed
        self._on_error = on_error

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._response: Any | None = None
        self._refresh_thread: threading.Thread | None = None
        self._refresh_pending = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            thread = threading.Thread(
                target=self._run,
                name="switchonyourcode-config-realtime",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            response = self._response
            self._thread = None
            self._response = None
            self._refresh_pending = False
            self._stop.set()

        if response is not None:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except OSError:
                    pass

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def close(self) -> None:
        self.stop()

    def _run(self) -> None:
        reconnect_delay = self._default_reconnect_delay

        while not self._stop.is_set():
            response: Any | None = None
            try:
                request = urllib.request.Request(
                    f"{self._base_url}/sdk/v1/events",
                    headers={
                        "Accept": "text/event-stream",
                        "Authorization": f"Bearer {self._server_key}",
                    },
                    method="GET",
                )
                response = self._opener(request, timeout=self._timeout)
                status = getattr(response, "status", response.getcode())
                if status == 401:
                    self._report_error(
                        SwitchOnYourCodeAuthenticationError(
                            "Switch On Your Code SDK credential was rejected."
                        )
                    )
                    return
                if status < 200 or status >= 300:
                    raise SwitchOnYourCodeHTTPError(
                        status,
                        f"Switch On Your Code event stream request failed with HTTP {status}.",
                    )

                content_type = response.headers.get("Content-Type", "")
                if not content_type.lower().startswith("text/event-stream"):
                    raise SwitchOnYourCodeRealtimeError(
                        "Switch On Your Code event stream returned an unexpected Content-Type."
                    )

                with self._lock:
                    if self._stop.is_set():
                        return
                    self._response = response

                credential_revoked = False
                for item_type, value in _consume_server_sent_events(response):
                    if self._stop.is_set():
                        return
                    if item_type == "retry":
                        reconnect_delay = max(1.0, float(value) / 1000.0)
                        continue

                    event = value
                    if event.event == "configuration_changed":
                        self._queue_configuration_refresh()
                    elif event.event == "credential_revoked":
                        credential_revoked = True
                        self._report_error(
                            SwitchOnYourCodeAuthenticationError(
                                "Switch On Your Code SDK credential was revoked."
                            )
                        )
                        self._stop.set()
                        break

                if credential_revoked or self._stop.is_set():
                    return
            except urllib.error.HTTPError as exc:
                if self._stop.is_set():
                    return
                if exc.code == 401:
                    self._report_error(
                        SwitchOnYourCodeAuthenticationError(
                            "Switch On Your Code SDK credential was rejected."
                        )
                    )
                    return
                self._report_error(
                    SwitchOnYourCodeHTTPError(
                        exc.code,
                        f"Switch On Your Code event stream request failed with HTTP {exc.code}.",
                    )
                )
            except urllib.error.URLError as exc:
                if self._stop.is_set():
                    return
                self._report_error(
                    SwitchOnYourCodeHTTPError(
                        0,
                        f"Switch On Your Code event stream request failed: {exc.reason}",
                    )
                )
            except (OSError, ValueError) as exc:
                if self._stop.is_set():
                    return
                self._report_error(exc)
            except BaseException as exc:
                if self._stop.is_set():
                    return
                self._report_error(exc)
            finally:
                with self._lock:
                    if self._response is response:
                        self._response = None
                if response is not None:
                    close = getattr(response, "close", None)
                    if callable(close):
                        try:
                            close()
                        except OSError:
                            pass

            self._stop.wait(reconnect_delay)

    def _queue_configuration_refresh(self) -> None:
        with self._lock:
            self._refresh_pending = True
            if self._refresh_thread is not None and self._refresh_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._refresh_loop,
                name="switchonyourcode-config-refresh",
                daemon=True,
            )
            self._refresh_thread = thread
            thread.start()

    def _refresh_loop(self) -> None:
        while True:
            with self._lock:
                if self._stop.is_set() or not self._refresh_pending:
                    self._refresh_thread = None
                    return
                self._refresh_pending = False

            try:
                self._on_configuration_changed()
            except BaseException as exc:
                self._report_error(exc)

    def _report_error(self, error: BaseException) -> None:
        if self._on_error is not None:
            self._on_error(error)


def _consume_server_sent_events(response: Any) -> Iterator[tuple[str, Any]]:
    event_name = ""
    data_lines: list[str] = []

    def dispatch() -> _ServerSentEvent | None:
        nonlocal event_name, data_lines
        if not event_name and not data_lines:
            return None
        event = _ServerSentEvent(event_name or "message", "\n".join(data_lines))
        event_name = ""
        data_lines = []
        return event

    for raw_line in response:
        if isinstance(raw_line, bytes):
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SwitchOnYourCodeRealtimeError(
                    "Switch On Your Code event stream was not valid UTF-8."
                ) from exc
        else:
            line = str(raw_line)

        line = line.rstrip("\n")
        if line.endswith("\r"):
            line = line[:-1]

        if line == "":
            event = dispatch()
            if event is not None:
                yield "event", event
            continue
        if line.startswith(":"):
            continue

        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]

        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)
        elif field == "retry" and value.isdigit():
            yield "retry", int(value)

    event = dispatch()
    if event is not None:
        yield "event", event
