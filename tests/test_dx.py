from __future__ import annotations

import warnings
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from nebula import ClientOptions, Nebula, NebulaClient, inputs, models

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
    assert client.memory is not None
    assert client.collections is not None


@pytest.mark.asyncio
async def test_memory_store_uses_one_document_and_conversation_surface() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "results": {
                    "id": "11111111-2222-4333-8444-555555555555",
                    "state": "processing",
                    "failure": None,
                }
            },
        )

    body = {
        "collection_id": COLLECTION_ID,
        "messages": [{"role": "user", "content": "hi"}],
    }
    async with _make_dx(httpx.MockTransport(handler)) as client:
        result = await client.memory.store(body=body)
    assert str(result.id) == "11111111-2222-4333-8444-555555555555"
    assert captured[0].method == "POST"
    assert str(captured[0].url) == "https://api.example.com/v1/memories"
    import json
    wire_body = json.loads(captured[0].content)
    assert wire_body["collection_id"] == COLLECTION_ID
    assert wire_body["messages"] == body["messages"]
    assert len(wire_body["memory_id"]) == 36
    assert "memory_id" not in body


@pytest.mark.asyncio
async def test_typed_memory_inputs_generate_and_preserve_identities() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": {
                    "id": body["memory_id"],
                    "state": "processing",
                    "failure": None,
                }
            },
        )

    body = inputs.StoreMemoryInput(
        collection_id=COLLECTION_ID,
        messages=[{"role": "user", "content": "hi"}],
    )
    async with _make_dx(httpx.MockTransport(handler)) as client:
        result = await client.memory.store(body=body)

    wire_body = __import__("json").loads(captured[0].content)
    assert wire_body["memory_id"] == str(body.memory_id)
    assert str(result.id) == str(body.memory_id)


def test_typed_batch_inputs_generate_nested_identities() -> None:
    collection = inputs.CreateCollectionInput(name="Research")
    body = inputs.StoreMemoriesInput(
        collection_id=COLLECTION_ID,
        memories=[
            inputs.StoreMemoryBatchItemInput(raw_text="first"),
            inputs.StoreMemoryBatchItemInput(
                messages=[{"role": "user", "content": "second"}],
            ),
        ],
    )

    assert collection.collection_id.version == 4
    assert len({item.memory_id for item in body.memories}) == 2


def test_wire_models_keep_generated_identities_required() -> None:
    with pytest.raises(ValidationError):
        models.CreateCollectionRequest(name="Research")
    with pytest.raises(ValidationError):
        models.StoreMemoryRequest(
            collection_id=COLLECTION_ID,
            raw_text="hello",
        )
    with pytest.raises(ValidationError):
        models.StoreMemoryBatchItem(raw_text="hello")


def test_deprecated_response_fields_warn_on_access() -> None:
    connection = models.ConnectorConnectionResponse.model_construct(
        uses_workspace_oauth_app=True
    )

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        assert connection.uses_workspace_oauth_app is True

    assert len(captured) == 1
    assert captured[0].category is DeprecationWarning
    assert "Use oauth_credential_source" in str(captured[0].message)


def test_connection_response_uses_enum_for_omitted_credential_source() -> None:
    connection = models.ConnectorConnectionResponse.model_validate(
        {
            "collection_id": "11111111-1111-1111-1111-111111111111",
            "created_at": "2026-08-12T00:00:00Z",
            "id": "22222222-2222-2222-2222-222222222222",
            "provider": "outlook",
            "status": "active",
            "updated_at": "2026-08-12T00:00:00Z",
            "user_id": "33333333-3333-3333-3333-333333333333",
        }
    )

    assert (
        connection.oauth_credential_source
        is models.OauthCredentialSource.default
    )


@pytest.mark.asyncio
async def test_memory_search_unwraps_envelope() -> None:
    # SnapshotSearchResult has the shape `{entities, relationships}` —
    # use it so the union TypeAdapter discriminates to a typed model.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": {"entities": [], "relationships": []}},
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        result = await client.memory.search(
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
async def test_memory_delete_hits_path_by_id() -> None:
    captured: list[httpx.Request] = []
    memory_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            202,
            json={
                "results": {
                    "id": memory_id,
                    "state": "deleting",
                    "failure": None,
                }
            },
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        result = await client.memory.delete(
            id=memory_id,
            collection_id="collection-1",
        )
    assert result.state == "deleting"
    assert captured[0].method == "DELETE"
    assert (
        str(captured[0].url)
        == f"https://api.example.com/v1/memories/{memory_id}?collection_id=collection-1"
    )
    assert captured[0].headers["x-nebula-owner-key"] == "collection:collection-1"


@pytest.mark.asyncio
async def test_memory_delete_many_takes_collection_scoped_body() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            202,
            json={
                "results": {
                    "memories": [
                        {
                            "id": memory_ids[0],
                            "state": "deleting",
                            "failure": None,
                        },
                        {
                            "id": memory_ids[1],
                            "state": "deleting",
                            "failure": None,
                        },
                    ]
                }
            },
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        memory_ids = [
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "11111111-aaaa-4bbb-8ccc-222222222222",
        ]
        result = await client.memory.delete_many(
            body={"collection_id": COLLECTION_ID, "ids": memory_ids}
        )
    assert [memory.state for memory in result.memories] == [
        "deleting",
        "deleting",
    ]
    assert captured[0].method == "POST"
    assert str(captured[0].url) == "https://api.example.com/v1/memories/delete"
    assert captured[0].headers["x-nebula-owner-key"] == f"collection:{COLLECTION_ID}"
    import json
    body = json.loads(captured[0].content)
    assert body["collection_id"] == COLLECTION_ID
    assert body["ids"] == memory_ids
    assert UUID(body["operation_id"]).version == 4


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
        await client.memory.list()
    finally:
        await client.aclose()

    assert captured[0].headers.get("authorization") == "Bearer key_real.token"


@pytest.mark.asyncio
async def test_collections_delete_returns_durable_product_state() -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(
            202,
            json={
                "results": {
                    "id": "123e4567-e89b-42d3-a456-426614174000",
                    "state": "deleting",
                    "failure": None,
                }
            },
        )

    async with _make_dx(httpx.MockTransport(handler)) as client:
        resp = await client.collections.delete(
            id="123e4567-e89b-42d3-a456-426614174000"
        )
    assert str(resp.id) == "123e4567-e89b-42d3-a456-426614174000"
    assert resp.state == "deleting"
    assert "Idempotency-Key" not in captured[0].headers


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
