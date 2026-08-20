from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from email.message import Message
from unittest.mock import patch

from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.event import ProviderEvent
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import Reason

from switchonyourcode.openfeature import SwitchOnYourCodeProvider


def configuration(*, revision: int = 1, enabled: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "environment": {"id": "env-1", "key": "production"},
        "flags": [
            {
                "id": "flag-1",
                "key": "new-checkout",
                "kind": "boolean",
                "default_value": False,
                "enabled": enabled,
                "variants": [],
                "policy": {
                    "rules": [
                        {
                            "id": "release-time",
                            "match": "all",
                            "conditions": [
                                {
                                    "attribute": "released_at",
                                    "operator": "equals",
                                    "value": "2026-08-20T12:34:56.789Z",
                                }
                            ],
                            "outcome": {"variant": "on"},
                        }
                    ],
                    "fallthrough": {"variant": "off"},
                },
                "revision": revision,
            },
            {
                "id": "flag-number",
                "key": "sample-rate",
                "kind": "number",
                "default_value": 1.5,
                "enabled": True,
                "variants": [],
                "policy": {},
                "revision": 1,
            },
        ],
        "segments": [],
    }


class FakeResponse:
    def __init__(self, payload: object, *, etag: str) -> None:
        self.status = 200
        self._body = json.dumps(payload).encode()
        self.headers = Message()
        self.headers["ETag"] = etag

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        pass


class OpenFeatureProviderTests(unittest.TestCase):
    def tearDown(self) -> None:
        api.shutdown()

    def test_provider_integrates_with_openfeature_api(self) -> None:
        with patch(
            "switchonyourcode.client.urllib.request.urlopen",
            return_value=FakeResponse(configuration(), etag='"config-1"'),
        ):
            provider = SwitchOnYourCodeProvider(
                base_url="https://flags.example.com",
                server_key="syoc_server_test",
                start_polling=False,
            )
            api.set_provider_and_wait(provider)
            client = api.get_client()
            details = client.get_boolean_details(
                "new-checkout",
                False,
                EvaluationContext(
                    targeting_key="user-123",
                    attributes={
                        "released_at": datetime(2026, 8, 20, 12, 34, 56, 789000, tzinfo=UTC)
                    },
                ),
            )

        self.assertTrue(details.value)
        self.assertEqual(details.reason, Reason.TARGETING_MATCH)
        self.assertEqual(details.variant, "on")
        self.assertEqual(details.flag_metadata["switchonyourcode.environment"], "production")
        self.assertEqual(details.flag_metadata["switchonyourcode.revision"], 1)
        self.assertEqual(details.flag_metadata["switchonyourcode.rule_id"], "release-time")

    def test_integer_resolution_rejects_non_integral_number(self) -> None:
        with patch(
            "switchonyourcode.client.urllib.request.urlopen",
            return_value=FakeResponse(configuration(), etag='"config-1"'),
        ):
            provider = SwitchOnYourCodeProvider(
                base_url="https://flags.example.com",
                server_key="syoc_server_test",
                start_polling=False,
            )
            provider.initialize(EvaluationContext())
            details = provider.resolve_integer_details("sample-rate", 2)
            provider.shutdown()

        self.assertEqual(details.value, 2)
        self.assertEqual(details.reason, Reason.ERROR)
        self.assertEqual(details.error_code, ErrorCode.TYPE_MISMATCH)

    def test_post_initialization_refresh_emits_configuration_changed(self) -> None:
        responses = iter(
            [
                FakeResponse(configuration(revision=1), etag='"config-1"'),
                FakeResponse(configuration(revision=2, enabled=False), etag='"config-2"'),
            ]
        )
        events: list[tuple[ProviderEvent, list[str] | None]] = []

        with patch(
            "switchonyourcode.client.urllib.request.urlopen",
            side_effect=lambda *_args, **_kwargs: next(responses),
        ):
            provider = SwitchOnYourCodeProvider(
                base_url="https://flags.example.com",
                server_key="syoc_server_test",
                start_polling=False,
            )
            provider.attach(lambda _provider, event, details: events.append((event, details.flags_changed)))
            provider.initialize(EvaluationContext())
            self.assertEqual(events, [])
            provider.client.refresh()
            provider.shutdown()

        self.assertEqual(
            events,
            [(ProviderEvent.PROVIDER_CONFIGURATION_CHANGED, ["new-checkout"])],
        )


if __name__ == "__main__":
    unittest.main()
