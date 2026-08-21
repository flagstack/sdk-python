from __future__ import annotations

import threading
import time
import unittest
import urllib.error
from email.message import Message
from typing import Any, Iterable

from switchonyourcode import (
    SwitchOnYourCodeAuthenticationError,
    SwitchOnYourCodeRealtimeStream,
)


class StreamingResponse:
    def __init__(self, lines: Iterable[bytes], *, status: int = 200, content_type: str = "text/event-stream") -> None:
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self._lines = lines
        self.closed = False

    def __iter__(self):
        yield from self._lines

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self.closed = True


def wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for realtime condition.")
        time.sleep(0.005)


class RealtimeTests(unittest.TestCase):
    def test_authenticated_stream_invalidates_configuration(self) -> None:
        changed = threading.Event()
        requests: list[Any] = []
        response = StreamingResponse(
            [
                b"retry: 5000\n",
                b"event: ready\n",
                b'data: {"schema_version":1,"environment_id":"env-1"}\n',
                b"\n",
                b"event: configuration_changed\n",
                b'data: {"environment_id":"env-1"}\n',
                b"\n",
            ]
        )

        def opener(request: Any, *, timeout: float) -> StreamingResponse:
            requests.append(request)
            self.assertEqual(timeout, 30.0)
            return response

        stream = SwitchOnYourCodeRealtimeStream(
            base_url="https://flags.example.com/",
            server_key="syoc_server_test",
            opener=opener,
            reconnect_delay=0.05,
            on_configuration_changed=changed.set,
        )
        stream.start()
        self.assertTrue(changed.wait(1.0))
        stream.stop()

        self.assertEqual(requests[0].full_url, "https://flags.example.com/sdk/v1/events")
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer syoc_server_test")
        self.assertEqual(requests[0].get_header("Accept"), "text/event-stream")
        self.assertTrue(response.closed)
        self.assertFalse(stream.running)

    def test_transient_stream_closure_reconnects(self) -> None:
        calls = 0
        errors: list[BaseException] = []

        def opener(request: Any, *, timeout: float) -> StreamingResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return StreamingResponse([b"event: ready\n", b"data: {}\n", b"\n"])
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", Message(), None)

        stream = SwitchOnYourCodeRealtimeStream(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=opener,
            reconnect_delay=0.01,
            on_configuration_changed=lambda: None,
            on_error=errors.append,
        )
        stream.start()
        wait_for(lambda: len(errors) >= 1)
        wait_for(lambda: not stream.running)

        self.assertEqual(calls, 2)
        self.assertIsInstance(errors[-1], SwitchOnYourCodeAuthenticationError)

    def test_credential_revocation_is_terminal(self) -> None:
        errors: list[BaseException] = []
        calls = 0

        def opener(_request: Any, *, timeout: float) -> StreamingResponse:
            nonlocal calls
            calls += 1
            return StreamingResponse(
                [
                    b"event: credential_revoked\n",
                    b'data: {"environment_id":"env-1"}\n',
                    b"\n",
                ]
            )

        stream = SwitchOnYourCodeRealtimeStream(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=opener,
            reconnect_delay=0.01,
            on_configuration_changed=lambda: None,
            on_error=errors.append,
        )
        stream.start()
        wait_for(lambda: len(errors) == 1)
        wait_for(lambda: not stream.running)

        self.assertEqual(calls, 1)
        self.assertIsInstance(errors[0], SwitchOnYourCodeAuthenticationError)

    def test_invalidation_burst_is_coalesced(self) -> None:
        callback_started = threading.Event()
        burst_sent = threading.Event()
        release_callback = threading.Event()
        callback_count = 0

        def lines():
            yield b"event: configuration_changed\n"
            yield b"data: {}\n"
            yield b"\n"
            if not callback_started.wait(1.0):
                raise AssertionError("Refresh callback did not start.")
            for _ in range(2):
                yield b"event: configuration_changed\n"
                yield b"data: {}\n"
                yield b"\n"
            burst_sent.set()
            release_callback.wait(1.0)

        response = StreamingResponse(lines())

        def on_configuration_changed() -> None:
            nonlocal callback_count
            callback_count += 1
            if callback_count == 1:
                callback_started.set()
                release_callback.wait(1.0)

        stream = SwitchOnYourCodeRealtimeStream(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=lambda *_args, **_kwargs: response,
            reconnect_delay=0.05,
            on_configuration_changed=on_configuration_changed,
        )
        stream.start()
        self.assertTrue(burst_sent.wait(1.0))
        release_callback.set()
        wait_for(lambda: callback_count == 2)
        stream.stop()

        self.assertEqual(callback_count, 2)


if __name__ == "__main__":
    unittest.main()
