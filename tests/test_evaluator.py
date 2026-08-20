from __future__ import annotations

import unittest

from flagstack import bucket, evaluate_flag, parse_configuration
from flagstack.types import ConfigurationFlag


def boolean_flag(**overrides: object) -> ConfigurationFlag:
    payload = {
        "schema_version": 1,
        "environment": {"id": "env-1", "key": "production"},
        "flags": [
            {
                "id": "flag-1",
                "key": "new-checkout",
                "kind": "boolean",
                "default_value": False,
                "enabled": True,
                "variants": [],
                "policy": {},
                "revision": 1,
                **overrides,
            }
        ],
        "segments": [],
    }
    return parse_configuration(payload).flags[0]


class EvaluatorTests(unittest.TestCase):
    def test_bucket_matches_v1_compatibility_vector(self) -> None:
        self.assertEqual(bucket("env-1", "flag-1", "user-123"), 22683)

    def test_disabled_flags_return_project_default(self) -> None:
        details = evaluate_flag(boolean_flag(enabled=False), "env-1")
        self.assertEqual(details.value, False)
        self.assertEqual(details.variant, "default")
        self.assertEqual(details.reason, "DISABLED")

    def test_enabled_boolean_without_policy_returns_on(self) -> None:
        details = evaluate_flag(boolean_flag(), "env-1")
        self.assertEqual(details.value, True)
        self.assertEqual(details.variant, "on")
        self.assertEqual(details.reason, "STATIC")

    def test_ordered_rules_and_transitive_segments(self) -> None:
        configuration = parse_configuration(
            {
                "schema_version": 1,
                "environment": {"id": "env-1", "key": "production"},
                "flags": [
                    {
                        "id": "flag-1",
                        "key": "new-checkout",
                        "kind": "boolean",
                        "default_value": False,
                        "enabled": True,
                        "variants": [],
                        "policy": {
                            "rules": [
                                {
                                    "id": "staff-rule",
                                    "match": "all",
                                    "conditions": [{"operator": "in_segment", "value": "staff"}],
                                    "outcome": {"variant": "on"},
                                }
                            ],
                            "fallthrough": {"variant": "off"},
                        },
                        "revision": 1,
                    }
                ],
                "segments": [
                    {
                        "key": "staff",
                        "name": "Staff",
                        "match": "all",
                        "conditions": [{"operator": "in_segment", "value": "internal"}],
                    },
                    {
                        "key": "internal",
                        "name": "Internal",
                        "match": "all",
                        "conditions": [
                            {
                                "attribute": "profile.email",
                                "operator": "ends_with",
                                "value": "@example.com",
                            }
                        ],
                    },
                ],
            }
        )
        flag = configuration.flags[0]
        matched = evaluate_flag(
            flag,
            "env-1",
            {"targetingKey": "user-1", "profile": {"email": "adam@example.com"}},
            configuration.segments,
        )
        self.assertEqual(matched.value, True)
        self.assertEqual(matched.reason, "TARGETING_MATCH")
        self.assertEqual(matched.rule_id, "staff-rule")

        unmatched = evaluate_flag(
            flag,
            "env-1",
            {"targetingKey": "user-2", "profile": {"email": "user@elsewhere.test"}},
            configuration.segments,
        )
        self.assertEqual(unmatched.value, False)
        self.assertEqual(unmatched.variant, "off")

    def test_percentage_rollout_is_stable(self) -> None:
        flag = boolean_flag(
            policy={
                "fallthrough": {
                    "rollout": [
                        {"variant": "on", "weight": 25_000},
                        {"variant": "off", "weight": 75_000},
                    ]
                }
            }
        )
        details = evaluate_flag(flag, "env-1", {"targetingKey": "user-123"})
        self.assertEqual(details.value, True)
        self.assertEqual(details.reason, "SPLIT")

    def test_string_bucket_attributes_match_go_json_escaping(self) -> None:
        flag = boolean_flag(
            policy={
                "fallthrough": {
                    "bucket_by": "account.label",
                    "rollout": [
                        {"variant": "on", "weight": 68_609},
                        {"variant": "off", "weight": 31_391},
                    ],
                }
            }
        )
        details = evaluate_flag(flag, "env-1", {"account": {"label": "<&>"}})
        self.assertEqual(details.value, True)

    def test_numeric_bucket_attributes_match_go_json_formatting(self) -> None:
        cases = [
            (1.0, 91129),
            (1e-6, 69539),
            (1e-7, 35740),
            (1e20, 82981),
            (1e21, 86769),
            (-0.0, 15580),
        ]
        for value, expected_bucket in cases:
            with self.subTest(value=value):
                flag = boolean_flag(
                    policy={
                        "fallthrough": {
                            "bucket_by": "account.score",
                            "rollout": [
                                {"variant": "on", "weight": expected_bucket + 1},
                                {"variant": "off", "weight": 100_000 - expected_bucket - 1},
                            ],
                        }
                    }
                )
                details = evaluate_flag(flag, "env-1", {"account": {"score": value}})
                self.assertEqual(details.value, True)

    def test_rollout_without_targeting_key_fails_safely(self) -> None:
        flag = boolean_flag(
            policy={
                "fallthrough": {
                    "rollout": [
                        {"variant": "on", "weight": 50_000},
                        {"variant": "off", "weight": 50_000},
                    ]
                }
            }
        )
        details = evaluate_flag(flag, "env-1")
        self.assertEqual(details.value, False)
        self.assertEqual(details.reason, "ERROR")
        self.assertEqual(details.error_code, "TARGETING_KEY_MISSING")

    def test_regex_matches_re2_inline_flags(self) -> None:
        flag = boolean_flag(
            policy={
                "rules": [
                    {
                        "id": "staff-email",
                        "match": "all",
                        "conditions": [
                            {
                                "attribute": "email",
                                "operator": "matches_regex",
                                "value": r"(?i)@example\.com$",
                            }
                        ],
                        "outcome": {"variant": "on"},
                    }
                ],
                "fallthrough": {"variant": "off"},
            }
        )
        self.assertEqual(evaluate_flag(flag, "env-1", {"email": "Adam@EXAMPLE.COM"}).value, True)
        self.assertEqual(evaluate_flag(flag, "env-1", {"email": "user@elsewhere.test"}).value, False)

    def test_semver_accepts_go_shorthand(self) -> None:
        flag = boolean_flag(
            policy={
                "rules": [
                    {
                        "id": "modern-app",
                        "match": "all",
                        "conditions": [
                            {
                                "attribute": "app_version",
                                "operator": "semver_greater_than_or_equal",
                                "value": "2.4",
                            }
                        ],
                        "outcome": {"variant": "on"},
                    }
                ],
                "fallthrough": {"variant": "off"},
            }
        )
        self.assertEqual(evaluate_flag(flag, "env-1", {"app_version": "v2.4.1"}).value, True)
        self.assertEqual(evaluate_flag(flag, "env-1", {"app_version": "2.3.9"}).value, False)

    def test_segment_cycles_fail_safely(self) -> None:
        configuration = parse_configuration(
            {
                "schema_version": 1,
                "environment": {"id": "env-1", "key": "production"},
                "flags": [
                    {
                        "id": "flag-1",
                        "key": "new-checkout",
                        "kind": "boolean",
                        "default_value": False,
                        "enabled": True,
                        "variants": [],
                        "policy": {
                            "rules": [
                                {
                                    "id": "cycle",
                                    "match": "all",
                                    "conditions": [{"operator": "in_segment", "value": "a"}],
                                    "outcome": {"variant": "on"},
                                }
                            ]
                        },
                        "revision": 1,
                    }
                ],
                "segments": [
                    {
                        "key": "a",
                        "name": "A",
                        "match": "all",
                        "conditions": [{"operator": "in_segment", "value": "b"}],
                    },
                    {
                        "key": "b",
                        "name": "B",
                        "match": "all",
                        "conditions": [{"operator": "in_segment", "value": "a"}],
                    },
                ],
            }
        )
        details = evaluate_flag(
            configuration.flags[0],
            "env-1",
            {},
            configuration.segments,
        )
        self.assertEqual(details.reason, "ERROR")
        self.assertEqual(details.error_code, "PARSE_ERROR")

    def test_multivariate_string_rollout(self) -> None:
        configuration = parse_configuration(
            {
                "schema_version": 1,
                "environment": {"id": "env-1", "key": "production"},
                "flags": [
                    {
                        "id": "flag-layout",
                        "key": "checkout-layout",
                        "kind": "string",
                        "default_value": "control",
                        "enabled": True,
                        "variants": [
                            {"key": "control", "value": "control"},
                            {"key": "new", "value": "new"},
                        ],
                        "policy": {
                            "fallthrough": {
                                "rollout": [
                                    {"variant": "control", "weight": 50_000},
                                    {"variant": "new", "weight": 50_000},
                                ]
                            }
                        },
                        "revision": 2,
                    }
                ],
                "segments": [],
            }
        )
        result = evaluate_flag(
            configuration.flags[0],
            "env-1",
            {"targetingKey": "user-123"},
        )
        self.assertIn(result.value, {"control", "new"})
        self.assertEqual(result.reason, "SPLIT")


if __name__ == "__main__":
    unittest.main()
