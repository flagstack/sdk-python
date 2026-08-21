from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
from email.message import Message
from typing import Any

from switchonyourcode import (
    SwitchOnYourCodeAuthenticationError,
    SwitchOnYourCodeClient,
    SwitchOnYourCodeConfigurationError,
)


def configuration(*, default: bool = False) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "environment": {"id": "env-1", "key": "production"},
        "flags": [
            {
                "id": "flag-1",
                "key": "new-checkout",
                "kind": "boolean",
                "default_value": default,
                "enabled": True,
                "variants": [],
                "policy": {},
                "revision": 1,
            }
        ],
        "segments": [],
    }


class FakeResponse:
    def __init__(self, payload: object, *, status: int = 200, etag: str | None = '"config-1"') -> None:
        self.status = status
        self._body = json.dumps(payload).encode()
        self.headers = Message()
        if etag is not None:
            self.headers["ETag"] = etag
        self.closed = False

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self.closed = True


class FakeEventResponse:
    def __init__(self) -> None:
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "text/event-stream"
        self.closed = False

    def __iter__(self):
        yield b"retry: 5000\n"
        yield b"event: ready\n"
        yield b"data: {}\n"
        yield b"\n"
        yield b"event: configuration_changed\n"
        yield b"data: {}\n"
        yield b"\n"
        while not self.closed:
            time.sleep(0.005)

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self.closed = True


def wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for client condition.")
        time.sleep(0.005)


class ClientTests(unittest.TestCase):
    def test_server_key_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "syoc_server"):
            SwitchOnYourCodeClient(base_url="https://flags.example.com", server_key="syoc_client_public")

    def test_refresh_loads_configuration_and_evaluates_locally(self) -> None:
        requests: list[Any] = []

        def opener(request: Any, *, timeout: float) -> FakeResponse:
            requests.append(request)
            self.assertEqual(timeout, 10.0)
            return FakeResponse(configuration())

        client = SwitchOnYourCodeClient(
            base_url="https://flags.example.com/",
            server_key="syoc_server_test",
            opener=opener,
        )
        self.assertEqual(client.refresh(), "updated")
        self.assertTrue(client.ready)
        self.assertEqual(client.etag, '"config-1"')
        self.assertTrue(client.get_boolean_value("new-checkout", False))
        self.assertEqual(requests[0].full_url, "https://flags.example.com/sdk/v1/config")
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer syoc_server_test")

    def test_etag_revalidation_retains_configuration(self) -> None:
        calls = 0

        def opener(request: Any, *, timeout: float) -> FakeResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeResponse(configuration())
            self.assertEqual(request.get_header("If-none-match"), '"config-1"')
            raise urllib.error.HTTPError(request.full_url, 304, "Not Modified", Message(), None)

        client = SwitchOnYourCodeClient(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=opener,
        )
        self.assertEqual(client.refresh(), "updated")
        self.assertEqual(client.refresh(), "not-modified")
        self.assertTrue(client.get_boolean_value("new-checkout", False))

    def test_invalid_refresh_keeps_last_known_good_configuration(self) -> None:
        calls = 0

        def opener(request: Any, *, timeout: float) -> FakeResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeResponse(configuration())
            return FakeResponse({"schema_version": 999})

        client = SwitchOnYourCodeClient(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=opener,
        )
        client.refresh()
        with self.assertRaises(SwitchOnYourCodeConfigurationError):
            client.refresh()
        self.assertTrue(client.get_boolean_value("new-checkout", False))
        self.assertEqual(client.etag, '"config-1"')

    def test_authentication_error_is_specific(self) -> None:
        def opener(request: Any, *, timeout: float) -> FakeResponse:
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", Message(), None)

        client = SwitchOnYourCodeClient(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=opener,
        )
        with self.assertRaises(SwitchOnYourCodeAuthenticationError):
            client.refresh()

    def test_typed_getters_return_caller_fallback_before_ready(self) -> None:
        client = SwitchOnYourCodeClient(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=lambda *_args, **_kwargs: FakeResponse(configuration()),
        )
        details = client.get_boolean_details("new-checkout", False)
        self.assertEqual(details.value, False)
        self.assertEqual(details.reason, "ERROR")
        self.assertEqual(details.error_code, "PROVIDER_NOT_READY")

    def test_disabling_polling_preserves_no_background_work_default(self) -> None:
        requests = 0

        def opener(_request: Any, *, timeout: float) -> FakeResponse:
            nonlocal requests
            requests += 1
            return FakeResponse(configuration())

        client = SwitchOnYourCodeClient(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=opener,
        )
        client.initialize(start_polling=False)

        self.assertEqual(requests, 1)
        self.assertFalse(client.realtime_running)
        client.close()

    def test_realtime_invalidation_refreshes_through_etag_path(self) -> None:
        event_response = FakeEventResponse()
        config_requests = 0
        seen_etags: list[str | None] = []
        event_request_seen = threading.Event()

        def opener(request: Any, *, timeout: float):
            nonlocal config_requests
            if request.full_url.endswith("/sdk/v1/events"):
                self.assertEqual(timeout, 30.0)
                self.assertEqual(request.get_header("Authorization"), "Bearer syoc_server_test")
                self.assertEqual(request.get_header("Accept"), "text/event-stream")
                event_request_seen.set()
                return event_response

            self.assertEqual(timeout, 10.0)
            config_requests += 1
            seen_etags.append(request.get_header("If-none-match"))
            if config_requests == 1:
                return FakeResponse(configuration(default=False), etag='"config-1"')
            return FakeResponse(configuration(default=True), etag='"config-2"')

        client = SwitchOnYourCodeClient(
            base_url="https://flags.example.com",
            server_key="syoc_server_test",
            opener=opener,
        )
        client.initialize(start_polling=False, start_realtime=True)
        self.assertTrue(event_request_seen.wait(1.0))
        wait_for(lambda: client.etag == '"config-2"')

        self.assertEqual(seen_etags, [None, '"config-1"'])
        self.assertTrue(client.get_boolean_value("new-checkout", False))
        client.close()
        self.assertTrue(event_response.closed)
        self.assertFalse(client.realtime_running)


if __name__ == "__main__":
    unittest.main()
