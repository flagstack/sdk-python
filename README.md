# FlagStack Python SDK

Official Python SDK for [FlagStack](https://github.com/flagstack/flagstack).

> **Status:** Early development. The package is not yet published for production use.

The SDK downloads FlagStack schema-v1 configuration with a server SDK key and evaluates flags locally in-process. Targeting, reusable segments, variants and percentage rollouts therefore do not require a network request for each evaluation.

## Requirements

Python 3.11 or newer. The runtime SDK uses only the Python standard library.

## Basic usage

```python
from flagstack import FlagStackClient

flags = FlagStackClient(
    base_url="https://flags.example.com",
    server_key="fs_server_...",
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
with FlagStackClient(
    base_url="https://flags.example.com",
    server_key="fs_server_...",
) as flags:
    flags.initialize(start_polling=False)
    enabled = flags.get_boolean_value("new-checkout", False)
```

## Configuration delivery

The client calls:

```text
GET /sdk/v1/config
Authorization: Bearer fs_server_...
```

It uses strong ETag revalidation. A `304 Not Modified` keeps the current in-memory configuration without reparsing it. A failed later refresh never replaces the last known-good configuration.

## Local evaluation

The Python evaluator implements the same FlagStack v1 contract as the JavaScript SDK:

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
bucket("env-1", "flag-1", "user-123") == 22683
```

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

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

CI validates the SDK on Python 3.11, 3.12, 3.13 and 3.14.

## Related repositories

- [FlagStack](https://github.com/flagstack/flagstack)
- [JavaScript SDK](https://github.com/flagstack/sdk-js)
- [Go SDK](https://github.com/flagstack/sdk-go)
- [.NET SDK](https://github.com/flagstack/sdk-dotnet)

## Licence

This SDK is licensed under the **Apache License 2.0**. See [`LICENSE`](LICENSE).
