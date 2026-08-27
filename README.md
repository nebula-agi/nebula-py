# nebula-sdk

Official Python SDK for Nebula by Zeroset. Provides typed async access to the
public Nebula REST API: collections, memories, connectors, snapshots, and
system health.

## Install

```bash
# Stable
pip install nebula-sdk
# Preview (next iteration, RC versions)
pip install --pre nebula-sdk
```

> **Pre-launch:** The public surface is still being shaped. Plain
> semver releases (`1.6.0`, `1.7.0`, …) are stable. Iteration ships
> as PEP 440 pre-release versions (`1.6.0rc1`, `rc2`, …) which
> pip's default resolver excludes — `pip install nebula-sdk` gets
> stable; `--pre` opts in to the iteration channel. Version
> specifiers like `nebula-sdk>=1.6.0,<2.0.0` likewise exclude
> pre-releases unless the specifier itself names one.

## Quick start

```python
import asyncio
import uuid
from nebula import Nebula, ClientOptions

async def main() -> None:
    async with Nebula(ClientOptions(api_key="...")) as client:
        stored = await client.memory.store(body={
            "collection_id": "01234567-...",
            "raw_text": "hello, world",
        })
        results = await client.memory.search(body={
            "query": "hello",
            "retrieval_operation_id": str(uuid.uuid4()),
        })
        print(stored)
        print(results)

asyncio.run(main())
```

This SDK is **async-first**. If you need to call it from a sync context, wrap
each call with `asyncio.run(...)`. A dedicated sync client is not currently
provided.

## Auth

Pass your Nebula API key as `api_key` when constructing the client. It is sent
via the `Authorization: Bearer` header.

```python
async with Nebula(ClientOptions(api_key="...")) as client:
    ...
```

## Errors

All HTTP errors map to a typed exception hierarchy:

- `NebulaBadRequestError` (400)
- `NebulaUnauthorizedError` (401)
- `NebulaForbiddenError` (403)
- `NebulaNotFoundError` (404)
- `NebulaConflictError` (409)
- `NebulaValidationError` (422)
- `NebulaRateLimitError` (429) — carries `retry_after` when the server returns `Retry-After`
- `NebulaServerError` (5xx)
- `NebulaConnectionError` / `NebulaTimeoutError` — transport-level

## Docs

- Product documentation: https://docs.zeroset.com
- OpenAPI contract: https://api.zeroset.com/openapi.json
- Migration notes: see `MIGRATION.md` in the source repo

## License

MIT
