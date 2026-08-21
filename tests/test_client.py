from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
