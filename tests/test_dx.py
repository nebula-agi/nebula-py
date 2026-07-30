from __future__ import annotations

from typing import Any

import httpx
import pytest

from nebula import Nebula, NebulaClient, ClientOptions

RETRIEVAL_OPERATION_ID = "11111111-1111-4111-8111-111111111111"
COLLECTION_ID = "11111111-2222-4333-8444-555555555555"


def _make_dx(transport: httpx.MockTransport, **overrides: Any) -> Nebula:
    options = ClientOptions(
        base_url=overrides.pop("base_url", "https://api.example.com"),
        api_key=overrides.pop("api_key", None),
        transport=transport,
        **overrides,
    )
    return Nebula(options)


@pytest.mark.asyncio
async def test_nebula_extends_nebula_client() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(204))
    client = _make_dx(transport)
    assert isinstance(client, NebulaClient)
    assert client.memories is not None
    assert client.collections is not None


@pytest.mark.asyncio
async def test_store_memory_create_dispatches_to_create() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {"id": "mem_new"}})

    async with _make_dx(httpx.MockTransport(handler)) as client:
        new_id = await client.store_memory(collection_id=COLLECTION_ID, raw_text="hi")
    assert new_id == "mem_new"
    assert captured[0].method == "POST"
    assert str(captured[0].url) == "https://api.example.com/v1/memories"
    import json
    body = json.loads(captured[0].content)
    assert body["collection_id"] == COLLECTION_ID
    assert body["raw_text"] == "hi"


@pytest.mark.asyncio
async def test_store_memory_append_dispatches_when_memory_id_set() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {"id": "appended"}})

    async with _make_dx(httpx.MockTransport(handler)) as client:
        result = await client.store_memory(
            {
                "memory_id": "mem_existing",
                "collection_id": COLLECTION_ID,
                "raw_text": "more",
            }
        )
    assert result == "mem_existing"
    assert str(captured[0].url) == "https://api.example.com/v1/memories/mem_existing/append"


@pytest.mark.asyncio
async def test_store_memory_content_string_maps_to_raw_text() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {"id": "x"}})

    async with _make_dx(httpx.MockTransport(handler)) as client:
        await client.store_memory(collection_id=COLLECTION_ID, content="shorthand")
    import json
    body = json.loads(captured[0].content)
    assert body["raw_text"] == "shorthand"
    assert "content" not in body


@pytest.mark.asyncio
async def test_store_memory_messages_sets_kind_conversation() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {"id": "mem_conv"}})

    async with _make_dx(httpx.MockTransport(handler)) as client:
        await client.store_memory(
            collection_id=COLLECTION_ID,
            messages=[{"role": "user", "content": "hi"}],
        )
    import json
    body = json.loads(captured[0].content)
    assert body["kind"] == "conversation"
    assert "engram_type" not in body


@pytest.mark.asyncio
async def test_memories_search_unwraps_envelope() -> None:
    # SnapshotSearchResult has the shape `{entities, relationships}` —
    # use it so the union TypeAdapter discriminates to a typed model.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": {"entities": [], "relationships": []}},
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        result = await client.memories.search(
            body={
                "query": "find me",
                "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
            }
        )
    # The response schema is an inline anyOf of Wrapped* variants — the
    # generator peels `.results` and TypeAdapter discriminates the inner
    # dict into the matching union variant.
    assert getattr(result, "entities", None) == []
    assert getattr(result, "relationships", None) == []


@pytest.mark.asyncio
async def test_memories_delete_hits_path_by_id() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            202,
            json={
                "results": {
                    "operation_id": "11111111-2222-4333-8444-555555555555",
                    "status_url": "/v1/memories/deletions/11111111-2222-4333-8444-555555555555",
                }
            },
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        await client.memories.delete(
            id="mem_to_delete",
            collection_id="collection-1",
        )
    assert captured[0].method == "DELETE"
    assert (
        str(captured[0].url)
        == "https://api.example.com/v1/memories/mem_to_delete?collection_id=collection-1"
    )
    assert captured[0].headers["x-nebula-owner-key"] == "collection:collection-1"


@pytest.mark.asyncio
async def test_memories_delete_many_takes_collection_scoped_body() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            202,
            json={
                "results": {
                    "operation_id": "11111111-2222-4333-8444-555555555555",
                    "status_url": "/v1/memories/deletions/11111111-2222-4333-8444-555555555555",
                }
            },
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        memory_ids = [
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "11111111-aaaa-4bbb-8ccc-222222222222",
        ]
        await client.memories.delete_many(
            body={"collection_id": COLLECTION_ID, "ids": memory_ids}
        )
    assert captured[0].method == "POST"
    assert str(captured[0].url) == "https://api.example.com/v1/memories/delete"
    assert captured[0].headers["x-nebula-owner-key"] == f"collection:{COLLECTION_ID}"
    import json
    body = json.loads(captured[0].content)
    assert body == {"collection_id": COLLECTION_ID, "ids": memory_ids}


@pytest.mark.asyncio
async def test_compat_api_key_alias_via_init_kwargs() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {}})

    transport = httpx.MockTransport(handler)
    client = Nebula(
        ClientOptions(base_url="https://api.example.com", transport=transport),
        api_key="key_real.token",
    )
    try:
        await client.memories.retrieve(id="m1")
    finally:
        await client.aclose()

    assert captured[0].headers.get("authorization") == "Bearer key_real.token"


@pytest.mark.asyncio
async def test_collections_delete_returns_accepted_operation() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            json={
                "results": {
                    "operation_id": "11111111-2222-4333-8444-555555555555",
                    "status_url": "/v1/collections/deletions/11111111-2222-4333-8444-555555555555",
                }
            },
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        resp = await client.collections.delete(id="c1")
    assert str(resp.operation_id) == "11111111-2222-4333-8444-555555555555"


@pytest.mark.asyncio
async def test_list_memories_string_becomes_collection_ids() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "total_entries": 0})

    async with _make_dx(httpx.MockTransport(handler)) as client:
        await client.list_memories("collection-abc")
    assert "collection_ids=collection-abc" in str(captured[0].url)


@pytest.mark.asyncio
async def test_connect_provider_can_select_saved_workspace_oauth_app() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "results": {
                    "auth_url": "https://provider.example/auth",
                    "state": "state",
                }
            },
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        await client.connect_provider(
            "gmail",
            COLLECTION_ID,
            oauth_client_mode="workspace",
        )

    assert str(captured[0].url) == (
        "https://api.example.com/v1/connectors/gmail/connect"
    )
    import json

    body = json.loads(captured[0].content)
    assert body["collection_id"] == COLLECTION_ID
    assert body["oauth_client_mode"] == "workspace"
