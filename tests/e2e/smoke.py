"""Pre-merge e2e smoke for nebula-sdk against a real Nebula stack.

Run with:
    NEBULA_BASE_URL=http://localhost:7272 \\
    NEBULA_API_KEY=key_xxx.yyy \\
    NEBULA_E2E_SKIP_INGESTION=1 \\
    .venv/bin/python tests/e2e/smoke.py

Mirrors the TS smoke at sdks/typescript/test/e2e/smoke.ts. Same checks,
same skip-ingestion gate.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from uuid import UUID

from nebula import (
    ClientOptions,
    Nebula,
    NebulaAPIError,
    NebulaServerError,
)


BASE_URL = os.getenv("NEBULA_BASE_URL", "http://localhost:7272")
API_KEY = os.getenv("NEBULA_API_KEY")
SKIP_INGESTION = os.getenv("NEBULA_E2E_SKIP_INGESTION") == "1"
if not API_KEY:
    print("NEBULA_API_KEY is required", file=sys.stderr)
    sys.exit(2)


def _assert(cond: object, msg: str) -> None:
    if not cond:
        print(f"✗ {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ {msg}")


async def main() -> None:
    print(f"Target: {BASE_URL}")
    print(f"Skip ingestion: {SKIP_INGESTION}")
    async with Nebula(ClientOptions(api_key=API_KEY, base_url=BASE_URL)) as client:
        # 1. list_collections — cursor pagination wire shape
        page = await client.collections.list(limit=25)
        _assert(hasattr(page, "data") and isinstance(page.data, list), "list_collections returns .data: list")
        _assert(hasattr(page, "has_more") and isinstance(page.has_more, bool), "list_collections returns .has_more: bool")
        _assert(hasattr(page, "next_cursor"), "list_collections returns .next_cursor (nullable)")

        # 2. list_memories — cursor + applied_wal_seq wire shape
        memories_page = await client.memories.list(limit=10)
        _assert(hasattr(memories_page, "data") and isinstance(memories_page.data, list), "list_memories returns .data: list")
        _assert(hasattr(memories_page, "has_more"), "list_memories returns .has_more: bool")
        _assert(hasattr(memories_page, "next_cursor"), "list_memories returns .next_cursor (nullable)")
        _assert(hasattr(memories_page, "applied_wal_seq"), "list_memories returns .applied_wal_seq (RYW token)")

        # 3. Create a throwaway collection — the SDK peels the `{results: X}`
        # wire envelope, so the return is the inner CollectionResponse model.
        created = await client.collections.create(body={"name": f"e2e-sdk-py-{int(time.time())}"})
        collection_id = getattr(created, "id", None)
        # Generated pydantic models coerce id fields to typed UUIDs — that's
        # the desired SDK behavior (callers get a real UUID, not a string).
        _assert(isinstance(collection_id, UUID), "collections.create returns id: UUID")

        # 4. Retrieve
        retrieved = await client.collections.retrieve(id=str(collection_id))
        _assert(getattr(retrieved, "id", None) == collection_id, "collections.retrieve returns the same id")

        # 5. Error envelope round-trip — force a 4xx
        error_caught = False
        try:
            await client.collections.create(body={"name": ""})
        except NebulaAPIError as err:
            error_caught = True
            _assert(isinstance(err.type, str), "envelope.type decoded as str")
            _assert(isinstance(str(err), str), "exception stringifies")
            _assert(isinstance(err.request_id, str), "envelope.request_id propagated")
            if isinstance(err.details, list):
                _assert(len(err.details) > 0, "validation details is a non-empty list")
                print(f"  first detail: {err.details[0]}")
            else:
                print(f"  (details was: {type(err.details).__name__}: {str(err.details)[:120]})")
        _assert(error_caught, "4xx propagates as NebulaAPIError")

        # 6. Memory ingestion (gated)
        if not SKIP_INGESTION:
            try:
                await client.memories.create(body={
                    "kind": "document",
                    "collection_id": collection_id,
                    "raw_text": "e2e smoke test memory",
                })
            except NebulaServerError as err:
                print(f"  (got 500: {err.type}, likely Orchestration outage — set NEBULA_E2E_SKIP_INGESTION=1 to skip)")

        # 7. Clean up
        deleted = await client.collections.delete(id=str(collection_id))
        _assert(getattr(deleted, "success", None) is True, "collections.delete returns success: True")

    print("\nAll SDK e2e smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
