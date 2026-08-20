# Switch On Your Code Python SDK

Official Python SDK for [Switch On Your Code](https://github.com/switchonyourcode/switchonyourcode).

> **Status:** Early development. The package is not yet published for production use.

The SDK downloads Switch On Your Code schema-v1 configuration with a server SDK key and evaluates flags locally in-process. Targeting, reusable segments, variants and percentage rollouts therefore do not require a network request for each evaluation.

## Requirements

Python 3.11 or newer. The native runtime SDK uses only the Python standard library.

## Basic usage

```python
from switchonyourcode import SwitchOnYourCodeClient

flags = SwitchOnYourCodeClient(
    base_url="https://flags.example.com",
    server_key="syoc_server_...",
)

flags.initialize()

enabled = flags.get_boolean_value(
    "new-checkout",
    False,
    {
        "targetingKey": "user-123",
        "country": "GB",
        "plan": "enterprise",
    },
)
```

`initialize()` performs the first configuration refresh and starts background polling. Use `initialize(start_polling=False)` for short-lived processes, CLIs and serverless functions that should not keep a polling thread alive.

The client also supports string, number and JSON flags:

```python
layout = flags.get_string_value(
    "checkout-layout",
    "control",
    {"targetingKey": "user-123"},
)
```

Call `close()` during application shutdown, or use the client as a context manager when its lifetime is scoped:

```python
with SwitchOnYourCodeClient(
    base_url="https://flags.example.com",
    server_key="syoc_server_...",
) as flags:
    flags.initialize(start_polling=False)
    enabled = flags.get_boolean_value("new-checkout", False)
```

## Configuration delivery

The client calls:

```text
GET /sdk/v1/config
Authorization: Bearer syoc_server_...
```

It uses strong ETag revalidation. A `304 Not Modified` keeps the current in-memory configuration without reparsing it. A failed later refresh never replaces the last known-good configuration.

## Local evaluation

The Python evaluator implements the same Switch On Your Code v1 contract as the JavaScript SDK and Go control-plane evaluator:

- boolean, string, number and JSON values;
- ordered rules;
- arbitrary nested context attributes;
- reusable and nested segments;
- deterministic SHA-256 percentage bucketing;
- multivariate variants;
- semantic-version comparisons;
- RE2-compatible regular-expression rules;
- OpenFeature-style resolution reasons and error codes.

The compatibility vector is fixed:

```text
bucket("env-1", "flag-1", "user-123") == 3837
```

Custom scalar `bucket_by` attributes are serialized using the Go reference evaluator's JSON representation before hashing, so Python-specific number or string formatting does not move users between rollout cohorts.

Python's built-in regex engine accepts constructs that RE2 does not. The SDK validates regex targeting against the RE2-compatible subset before compiling it, so Python cannot silently broaden the rule language.

## Detailed evaluation

Every typed getter has a matching details method:

```python
details = flags.get_boolean_details(
    "new-checkout",
    False,
    {"targetingKey": "user-123"},
)

print(details.value)
print(details.variant)
print(details.reason)
print(details.rule_id)
```

When the provider is not ready, a flag is missing, or the requested type does not match the flag, the SDK returns the caller-provided fallback and exposes the failure through the details object.

## OpenFeature

OpenFeature support is optional so the native `switchonyourcode` install remains standard-library-only:

```bash
pip install "switchonyourcode[openfeature]"
```

Register `SwitchOnYourCodeProvider` with the OpenFeature Python SDK:

```python
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from switchonyourcode.openfeature import SwitchOnYourCodeProvider

api.set_provider_and_wait(
    SwitchOnYourCodeProvider(
        base_url="https://flags.example.com",
        server_key="syoc_server_...",
    )
)

client = api.get_client()

enabled = client.get_boolean_value(
    "new-checkout",
    False,
    EvaluationContext(
        targeting_key="user-123",
        attributes={"country": "GB", "plan": "enterprise"},
    ),
)
```

The provider maps Switch On Your Code values, variants, reasons and error codes into OpenFeature resolution details. Flag metadata includes the Switch On Your Code environment, environment ID, revision, enabled state and matched rule ID when present.

OpenFeature `datetime` context values are normalized to UTC ISO-8601 strings before Switch On Your Code targeting. Integer evaluation accepts Switch On Your Code number values only when they are mathematically integral; OpenFeature object evaluation accepts JSON arrays and objects rather than scalar JSON values.

Provider initialization and shutdown use the native Switch On Your Code client. Post-initialization configuration refreshes emit OpenFeature `PROVIDER_CONFIGURATION_CHANGED` events with the changed flag keys.

## Development

```bash
python -m pip install -e ".[openfeature]"
python -m unittest discover -s tests -v
```

CI validates the SDK on Python 3.11, 3.12, 3.13 and 3.14.

## Related repositories

- [Switch On Your Code](https://github.com/switchonyourcode/switchonyourcode)
- [JavaScript SDK](https://github.com/switchonyourcode/sdk-js)
- [Go SDK](https://github.com/switchonyourcode/sdk-go)
- [.NET SDK](https://github.com/switchonyourcode/sdk-dotnet)

## Licence

This SDK is licensed under the **Apache License 2.0**. See [`LICENSE`](LICENSE).
