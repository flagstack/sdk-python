# FlagStack Python SDK

Official Python SDK for [FlagStack](https://github.com/flagstack/flagstack).

> **Status:** Planned / early development. Not yet ready for production use.

## Goals

The Python SDK will provide first-class FlagStack support for Python applications, including:

- synchronous applications;
- native asynchronous applications;
- Django;
- FastAPI;
- Celery workers;
- long-running services and bots;
- local feature-flag evaluation;
- real-time configuration updates;
- resilient cached configuration when FlagStack is temporarily unavailable;
- OpenFeature integration.

## Planned usage

The final API is still to be designed, but the aim is to provide a small, idiomatic Python interface suitable for both sync and async applications.

```python
from flagstack import FlagStack

client = FlagStack(...)

if client.is_enabled("new-checkout"):
    ...
```

The example above is illustrative only and is not yet a stable API.

## Package

The intended Python package name is:

```bash
pip install flagstack
```

Publishing and compatibility details will be documented once the initial SDK is implemented.

## Related repositories

- [FlagStack](https://github.com/flagstack/flagstack)
- [JavaScript / TypeScript SDK](https://github.com/flagstack/sdk-js)
- [Go SDK](https://github.com/flagstack/sdk-go)
- [.NET SDK](https://github.com/flagstack/sdk-dotnet)

## License

A license will be selected before the first public release.
