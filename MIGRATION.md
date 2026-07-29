# Migrating to nebula-sdk 1.4.x

The 1.4.x line replaces the Stainless-generated SDK with an in-house generator.
Public method names and call signatures are preserved; the **wire shapes**
for errors and list responses changed — see the breaking-change section
below.

## Breaking changes

### 1. Error envelope

Every 4xx / 5xx now returns the canonical envelope:

```jsonc
{
  "type": "validation_error",       // stable machine-readable class
  "message": "raw_text must be non-empty",
  "code": "raw_text.empty",         // optional, stable per type
  "request_id": "rid-abc-123",      // X-Request-Id round-trip
  "details": { ... }                // optional structured context
}
```

The SDK surfaces these on `NebulaAPIError`:

```python
from nebula import NebulaValidationError

try:
    await client.store_memory(collection_id="...", raw_text="")
except NebulaValidationError as err:
    err.type         # "validation_error"
    err.code         # "raw_text.empty"
    err.request_id   # "rid-abc-123" — quote in support tickets
    err.details      # {"field": "raw_text", "limit": 1}
    str(err)         # "raw_text must be non-empty"
```

**1.3.x callers reading `err.body["message"]` or `err.body["error_type"]` keep
working** — `err.body` is still the raw response body. The new typed
attributes (`err.type`, `err.code`, `err.request_id`, `err.details`) are the
recommended accessors going forward.

If you wrote error-class checks against the body's `error_type` field, those
no longer match — `error_type` was renamed to `type`. Switch the check to
`err.type` or the typed-class hierarchy.

### 2. Cursor pagination

List endpoints (`list_memories`, `list_collections`) moved from offset to
opaque cursors:

```python
# 1.x
page = await client.list_memories(offset=0, limit=50)
page.results
page.total_entries

# 1.4.x
page = await client.list_memories(limit=50)
page.data
page.has_more
page.next_cursor

while page.has_more:
    page = await client.list_memories(limit=50, cursor=page.next_cursor)
    # ...
```

`total_entries` is no longer returned. If you displayed it as a UI count,
either drop it or query a dedicated count endpoint (none exists today —
file an issue if you need one).

## Non-breaking improvements

- `store_memories` accepts a `max_concurrency` argument (default 8) —
  bounded worker pool, no more accidental unbounded fan-out under the hood.
- Cancellation via `asyncio.CancelledError` propagates through all methods.
- PEP 561 `py.typed` ships in the wheel — `mypy --strict` works against
  the public surface.
- Python 3.11+ required.

## Need help?

File issues at https://github.com/zeroset-inc/nebula-python/issues with
the `request_id` from `err.request_id`.
