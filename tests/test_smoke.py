from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from nebula import (
    ClientOptions,
    NebulaClient,
    NebulaNotFoundError,
    NebulaRateLimitError,
    NebulaValidationError,
    models,
)

RETRIEVAL_OPERATION_ID = "11111111-1111-4111-8111-111111111111"


def _make_client(transport: httpx.MockTransport, **overrides: Any) -> NebulaClient:
    options = ClientOptions(
        base_url="https://api.example.com",
        api_key=overrides.pop("api_key", None),
        transport=transport,
        **overrides,
    )
    return NebulaClient(options)


@pytest.mark.parametrize(
    ("request_model", "name"),
    [
        (models.CreateCollectionRequest, ""),
        (models.CreateCollectionRequest, "  "),
        (models.UpdateCollectionRequest, "  "),
    ],
)
def test_collection_models_reject_blank_names(request_model: Any, name: str) -> None:
    with pytest.raises(ValidationError):
        request_model(name=name)


def test_memory_search_model_distinguishes_omitted_from_nullable_fields() -> None:
    request = models.MemorySearchRequest(query="hello", effort=None)

    assert request.include_sources is False
    assert request.effort is None
    with pytest.raises(ValidationError):
        models.MemorySearchRequest(query="hello", include_sources=None)


def test_memory_search_model_rejects_unknown_typed_field() -> None:
    with pytest.raises(ValidationError, match="include_source"):
        models.MemorySearchRequest(query="hello", include_source=True)


@pytest.mark.asyncio
async def test_memories_search_sends_post_with_body_and_bearer() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "total_entries": 0})

    transport = httpx.MockTransport(handler)
    async with _make_client(transport, api_key="secret") as client:
        result = await client.memories.search(
            body={
                "query": "hello",
                "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
            }
        )

    assert result == []
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert str(req.url) == "https://api.example.com/v1/memories/search"
    assert req.headers["authorization"] == "Bearer secret"
    assert req.headers["content-type"] == "application/json"
    import json
    assert json.loads(req.content) == {
        "query": "hello",
        "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
    }


@pytest.mark.parametrize(
    ("resource", "method", "body", "invalid_field"),
    [
        (
            "memories",
            "search",
            {"query": "hello", "include_sources": None},
            "include_sources",
        ),
        (
            "memories",
            "search",
            {"query": "hello", "include_source": True},
            "include_source",
        ),
        (
            "collections",
            "create",
            {"name": "Support", "workflow_enabled": True},
            "workflow_enabled",
        ),
        (
            "memories",
            "search",
            {"query": "hello", "search_settings": {"include_score": True}},
            "include_score",
        ),
        (
            "memories",
            "recall_workflow",
            {
                "intent": "bootstrap",
                "collection_id": "11111111-2222-3333-4444-555555555555",
                "top_kk": 5,
            },
            "top_kk",
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_request_dictionary_is_rejected_before_transport(
    resource: str,
    method: str,
    body: dict[str, Any],
    invalid_field: str,
) -> None:
    def fail_on_request(_request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid request reached transport")

    async with _make_client(httpx.MockTransport(fail_on_request)) as client:
        request_method = getattr(getattr(client, resource), method)
        with pytest.raises(ValidationError, match=invalid_field):
            await request_method(body=body)


@pytest.mark.asyncio
async def test_resolve_search_sources_parses_direct_source_union() -> None:
    retrieval_id = "11111111-1111-4111-8111-111111111111"
    collection_id = "22222222-2222-4222-8222-222222222222"
    chunk_id = "33333333-3333-4333-8333-333333333333"
    source_id = "44444444-4444-4444-8444-444444444444"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/memories/searches/{retrieval_id}/sources"
        evidence_ref = {
            "ref_type": "chunk",
            "chunk_id": chunk_id,
            "collection_id": collection_id,
        }
        return httpx.Response(
            200,
            json={
                "results": {
                    "retrieval_id": retrieval_id,
                    "status": "partial",
                    "future_response_field": "accepted",
                    "groups": [
                        {
                            "memory_id": source_id,
                            "memory_kind": "semantic",
                            "rank": 0,
                            "activation_score": 0.9,
                            "sources": [
                                {
                                    "status": "available",
                                    "evidence_ref": evidence_ref,
                                    "id": source_id,
                                    "text": "grounding text",
                                    "activation_score": 0.8,
                                    "supporting_fact_ids": [],
                                    "future_source_field": "accepted",
                                },
                                {
                                    "status": "unavailable",
                                    "evidence_ref": evidence_ref,
                                },
                            ],
                        }
                    ],
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        response = await client.memories.resolve_search_sources(retrieval_id)

    sources = response.groups[0].sources
    assert isinstance(sources[0], models.AvailableRetrievalAuditSource)
    assert sources[0].status == "available"
    assert isinstance(sources[1], models.UnavailableRetrievalAuditSource)
    assert sources[1].status == "unavailable"
    assert not hasattr(sources[0], "root")


def test_resolved_search_source_arrays_are_required_and_accept_empty_lists() -> None:
    retrieval_id = "11111111-1111-4111-8111-111111111111"
    response = models.RetrievalAuditSourcesResponse.model_validate(
        {
            "retrieval_id": retrieval_id,
            "status": "complete",
            "groups": [],
        }
    )

    assert response.groups == []
    with pytest.raises(ValidationError, match="groups"):
        models.RetrievalAuditSourcesResponse.model_validate(
            {"retrieval_id": retrieval_id, "status": "complete"}
        )

    group = {
        "memory_id": retrieval_id,
        "memory_kind": "semantic",
        "rank": 0,
        "activation_score": 0.9,
    }
    with pytest.raises(ValidationError, match="sources"):
        models.RetrievalAuditSourceGroup.model_validate(group)
    parsed_group = models.RetrievalAuditSourceGroup.model_validate(
        {**group, "sources": []}
    )
    assert parsed_group.sources == []


@pytest.mark.asyncio
async def test_request_validation_preserves_open_dictionary_fields() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "total_entries": 0})

    body = {
        "query": "hello",
        "filters": {"custom_operator": {"arbitrary_key": [1, 2]}},
        "search_settings": {
            "graph_settings": {"provider_extension": {"depth": 3}}
        },
    }
    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        await client.memories.search(body=body)

    import json
    sent = json.loads(captured[0].content)
    assert sent["filters"] == body["filters"]
    assert sent["search_settings"]["graph_settings"] == body["search_settings"][
        "graph_settings"
    ]


@pytest.mark.asyncio
async def test_single_collection_search_derives_edge_routing_header() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "total_entries": 0})

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        await client.memories.search(
            body={
                "query": "hello",
                "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
                "collection_ids": ["33333333-3333-4333-8333-333333333333"],
            }
        )
        await client.memories.search(
            body={
                "query": "hello",
                "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
                "collection_ids": [
                    "33333333-3333-4333-8333-333333333333",
                    "44444444-4444-4444-8444-444444444444",
                ],
            }
        )

    assert (
        captured[0].headers["x-nebula-owner-key"]
        == "collection:33333333-3333-4333-8333-333333333333"
    )
    assert "x-nebula-owner-key" not in captured[1].headers


@pytest.mark.asyncio
async def test_workspace_scoped_upload_uses_canonical_query_routing() -> None:
    captured: list[httpx.Request] = []
    workspace_id = "22222222-2222-4222-8222-222222222222"

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "results": {
                    "upload_session_id": "33333333-3333-4333-8333-333333333333",
                    "part_size": 8388608,
                    "expires_in": 3600,
                    "max_size": 104857600,
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        await client.memories.create_upload(
            filename="image.png",
            content_type="image/png",
            file_size=12,
            workspace_id=workspace_id,
        )

    assert captured[0].url.path == "/v1/memories/upload"
    assert captured[0].url.params["workspace_id"] == workspace_id
    assert "x-nebula-owner-key" not in captured[0].headers


@pytest.mark.asyncio
async def test_filter_scoped_search_derives_edge_routing_header() -> None:
    captured: list[httpx.Request] = []
    collection_id = "33333333-3333-4333-8333-333333333333"
    other_collection_id = "44444444-4444-4444-8444-444444444444"

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "total_entries": 0})

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        await client.memories.search(
            body={
                "query": "hello",
                "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
                "filters": {
                    "collection_ids": {"$overlap": [collection_id]},
                },
            }
        )
        await client.memories.search(
            body={
                "query": "hello",
                "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
                "filters": {
                    "collection_ids": {
                        "$overlap": [collection_id, other_collection_id]
                    }
                },
            }
        )
    assert captured[0].headers["x-nebula-owner-key"] == f"collection:{collection_id}"
    assert "x-nebula-owner-key" not in captured[1].headers


@pytest.mark.asyncio
async def test_write_calls_derive_edge_routing_headers_from_body_ids() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/v1/collections":
            return httpx.Response(200, json={"results": {"id": "collection-id"}})
        if request.url.path == "/v1/memories":
            return httpx.Response(
                200,
                json={"results": {"id": "memory-id", "message": "ok"}},
            )
        return httpx.Response(200, json={"results": {"message": "ok"}})

    transport = httpx.MockTransport(handler)
    options = ClientOptions(
        base_url="https://api.example.com",
        transport=transport,
    )
    async with NebulaClient(options) as client:
        await client.collections.create(body={"name": "Personal collection"})
        await client.collections.create(
            body={
                "name": "Team collection",
                "workspace_id": "22222222-2222-4222-8222-222222222222",
            }
        )
        await client.memories.create(
            body={
                "collection_id": "33333333-3333-4333-8333-333333333333",
                "raw_text": "hello",
            }
        )
        await client.memories.append(
            id="44444444-4444-4444-8444-444444444444",
            body={
                "collection_id": "55555555-5555-4555-8555-555555555555",
                "raw_text": "more",
            },
        )

    assert "x-nebula-owner-key" not in captured[0].headers
    assert (
        captured[1].headers["x-nebula-owner-key"]
        == "workspace:22222222-2222-4222-8222-222222222222"
    )
    assert (
        captured[2].headers["x-nebula-owner-key"]
        == "collection:33333333-3333-4333-8333-333333333333"
    )
    assert (
        captured[3].headers["x-nebula-owner-key"]
        == "collection:55555555-5555-4555-8555-555555555555"
    )


@pytest.mark.asyncio
async def test_zero_config_personal_collection_create_omits_routing_header() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {"id": "collection-id"}})

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        await client.collections.create(body={"name": "Personal collection"})

    assert "x-nebula-owner-key" not in captured[0].headers


@pytest.mark.asyncio
async def test_collections_list_serializes_query_params() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"data": [], "next_cursor": None, "has_more": False}
        )

    transport = httpx.MockTransport(handler)
    async with _make_client(transport, api_key="k1") as client:
        await client.collections.list(cursor="MTA=", limit=5, owner_only=True)

    req = captured[0]
    assert req.headers["authorization"] == "Bearer k1"
    # `=` in `MTA=` (base64-encoded "10") is URL-encoded as `%3D`.
    assert "cursor=MTA" in str(req.url)
    assert "limit=5" in str(req.url)
    assert "owner_only=true" in str(req.url)


@pytest.mark.asyncio
async def test_path_params_substituted() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        # Wire shape is the `{results: Engram}` envelope; the generator
        # peels `.results` before model-validating into Engram.
        return httpx.Response(
            200,
            json={"results": {"id": "abc", "kind": "document"}},
        )

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        await client.memories.retrieve(id="11111111-2222-3333-4444-555555555555")

    assert str(captured[0].url) == (
        "https://api.example.com/v1/memories/11111111-2222-3333-4444-555555555555"
    )


@pytest.mark.asyncio
async def test_422_maps_to_validation_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"msg": "bad"}]})

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        with pytest.raises(NebulaValidationError):
            await client.memories.search(body={})


@pytest.mark.asyncio
async def test_404_maps_to_not_found_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "missing"})

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        with pytest.raises(NebulaNotFoundError):
            await client.memories.retrieve(id="missing")


@pytest.mark.asyncio
async def test_does_not_retry_post_when_not_idempotent() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"detail": "down"})

    transport = httpx.MockTransport(handler)
    from nebula import RetryPolicy
    async with _make_client(
        transport, retry=RetryPolicy(max_retries=5, base_seconds=0.001, max_seconds=0.005)
    ) as client:
        with pytest.raises(Exception):
            await client.memories.create(
                body={
                    "collection_id": "11111111-2222-3333-4444-555555555555"
                }
            )

    assert attempts == 1


@pytest.mark.asyncio
async def test_keyed_memory_deletion_forwards_key_and_retries() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"detail": "retry"})
        return httpx.Response(
            202,
            json={
                "results": {
                    "operation_id": "11111111-1111-4111-8111-111111111111",
                    "status_url": "/v1/memories/deletions/11111111-1111-4111-8111-111111111111",
                }
            },
        )

    from nebula import RetryPolicy

    transport = httpx.MockTransport(handler)
    async with _make_client(
        transport,
        retry=RetryPolicy(
            max_retries=1,
            base_seconds=0.001,
            max_seconds=0.001,
        ),
    ) as client:
        await client.memories.delete(
            id="memory-1",
            collection_id="collection-1",
            idempotency_key="delete-memory-1",
        )

    assert len(requests) == 2
    assert [request.headers["idempotency-key"] for request in requests] == [
        "delete-memory-1",
        "delete-memory-1",
    ]


@pytest.mark.asyncio
async def test_retries_get_on_503() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"detail": "warming up"})
        return httpx.Response(
            200, json={"data": [], "next_cursor": None, "has_more": False}
        )

    transport = httpx.MockTransport(handler)
    from nebula import RetryPolicy
    async with _make_client(
        transport, retry=RetryPolicy(max_retries=3, base_seconds=0.001, max_seconds=0.005)
    ) as client:
        result = await client.collections.list(limit=10)

    # `result` is now a validated Pydantic model (the model_validate fix);
    # `model_dump()` round-trips back to the wire shape.
    assert result.model_dump() == {
        "data": [],
        "next_cursor": None,
        "has_more": False,
    }
    assert attempts == 3


@pytest.mark.asyncio
async def test_request_body_accepts_pydantic_model_instance() -> None:
    """Regression: previously the runtime passed a BaseModel to httpx.json,
    which raised TypeError. The runtime now dumps BaseModels via
    model_dump(mode='json', by_alias=True, exclude_unset=True) before httpx.
    """
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {"id": "mem_1", "message": "ok"}})

    transport = httpx.MockTransport(handler)
    body = models.CreateMemoryRequest(
        collection_id="11111111-2222-3333-4444-555555555555",
        raw_text="hello world",
    )
    async with _make_client(transport) as client:
        await client.memories.create(body=body)

    import json
    sent = json.loads(captured[0].content)
    assert sent["collection_id"] == "11111111-2222-3333-4444-555555555555"
    assert sent["raw_text"] == "hello world"
    # by_alias=True preserves the wire-shape field names; no exclude_none
    # so an explicitly-None field would round-trip as null (we don't set
    # one here, just guard against a future regression that adds it).


@pytest.mark.asyncio
async def test_delete_many_collection_scoped_body_sets_routing_header() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {"succeeded": 2}})

    transport = httpx.MockTransport(handler)
    collection_id = "11111111-2222-3333-4444-555555555555"
    memory_ids = [
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "11111111-aaaa-bbbb-cccc-222222222222",
    ]
    async with _make_client(transport) as client:
        await client.memories.delete_many(
            body={"collection_id": collection_id, "ids": memory_ids}
        )

    import json
    sent = json.loads(captured[0].content)
    assert captured[0].headers["x-nebula-owner-key"] == f"collection:{collection_id}"
    assert sent == {"collection_id": collection_id, "ids": memory_ids}


def test_serialize_body_handles_list_of_pydantic_models() -> None:
    """Direct test of the runtime helper: a list of BaseModel instances
    serializes each element via model_dump. No spec endpoint currently uses
    list[BaseModel] bodies, so this guards the helper itself rather than a
    generated method."""
    from nebula._runtime.client import _serialize_body

    items = [
        models.CreateCollectionRequest(name="alpha"),
        models.CreateCollectionRequest(name="beta", description="b"),
    ]
    out = _serialize_body(items)
    assert isinstance(out, list)
    assert out[0]["name"] == "alpha"
    assert out[1]["name"] == "beta"
    assert out[1]["description"] == "b"
    # Verify it's a real dict, not a BaseModel.
    assert isinstance(out[0], dict)


def test_serialize_body_passes_through_dict_unchanged() -> None:
    """Dicts (the most common DX-layer path) skip serialization entirely."""
    from nebula._runtime.client import _serialize_body

    body = {"collection_id": "c1", "raw_text": "x"}
    out = _serialize_body(body)
    assert out is body  # same object, no copy


@pytest.mark.asyncio
async def test_429_retry_after_accepts_http_date() -> None:
    """RFC 7231 allows Retry-After as either numeric-seconds or HTTP-date.
    The Python runtime now matches the TS runtime's parser behavior.
    """
    from datetime import datetime, timezone, timedelta
    from email.utils import format_datetime

    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    http_date = format_datetime(future, usegmt=True)

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "slow"}, headers={"Retry-After": http_date})

    transport = httpx.MockTransport(handler)
    from nebula import RetryPolicy
    async with _make_client(
        transport, retry=RetryPolicy(max_retries=0, base_seconds=0.001, max_seconds=0.005)
    ) as client:
        with pytest.raises(NebulaRateLimitError) as excinfo:
            await client.memories.retrieve(id="x")

    # ~30 seconds (allow a small drift window for the time between header
    # construction and parser invocation).
    assert excinfo.value.retry_after is not None
    assert 25.0 <= excinfo.value.retry_after <= 35.0


@pytest.mark.asyncio
async def test_429_surfaces_rate_limit_error_with_retry_after() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "slow"}, headers={"Retry-After": "2"})

    transport = httpx.MockTransport(handler)
    from nebula import RetryPolicy
    async with _make_client(
        transport, retry=RetryPolicy(max_retries=0, base_seconds=0.001, max_seconds=0.005)
    ) as client:
        with pytest.raises(NebulaRateLimitError) as excinfo:
            await client.memories.retrieve(id="x")

    assert excinfo.value.retry_after == 2.0


@pytest.mark.asyncio
async def test_canonical_envelope_populates_type_code_details_request_id() -> None:
    envelope = {
        "type": "validation_error",
        "message": "raw_text must be non-empty",
        "code": "raw_text.empty",
        "request_id": "rid-abc-123",
        "details": {"field": "raw_text", "limit": 1},
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json=envelope,
            headers={"X-Request-Id": "header-rid-should-lose-to-body"},
        )

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        with pytest.raises(NebulaValidationError) as excinfo:
            await client.memories.search(
                body={
                    "query": "x",
                    "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
                }
            )

    err = excinfo.value
    assert err.type == "validation_error"
    assert err.code == "raw_text.empty"
    assert err.details == {"field": "raw_text", "limit": 1}
    # Envelope's request_id wins over the transport header.
    assert err.request_id == "rid-abc-123"
    assert str(err) == "raw_text must be non-empty"


@pytest.mark.asyncio
async def test_array_shaped_details_survive_intact() -> None:
    # FastAPI's RequestValidationError emits `details` as a list of
    # {loc, msg, type} entries. Narrowing to Mapping would drop the
    # array; the runtime preserves it as-is (typed Any).
    validation_details = [
        {"loc": ["body", "raw_text"], "msg": "field required", "type": "value_error.missing"},
        {"loc": ["body", "collection_id"], "msg": "uuid_parsing", "type": "value_error"},
    ]
    envelope = {
        "type": "validation_error",
        "message": "Request validation failed",
        "code": "validation_error",
        "request_id": "rid-validation",
        "details": validation_details,
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json=envelope)

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        with pytest.raises(NebulaValidationError) as excinfo:
            await client.memories.search(
                body={
                    "query": "x",
                    "retrieval_operation_id": RETRIEVAL_OPERATION_ID,
                }
            )

    err = excinfo.value
    assert isinstance(err.details, list)
    assert err.details == validation_details


@pytest.mark.asyncio
async def test_non_envelope_body_leaves_envelope_fields_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"detail": "missing"},
            headers={"X-Request-Id": "rid-fallback"},
        )

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as client:
        with pytest.raises(NebulaNotFoundError) as excinfo:
            await client.memories.retrieve(id="nope")

    err = excinfo.value
    assert err.type is None
    assert err.code is None
    assert err.details is None
    # Falls back to the transport header when the body isn't an envelope.
    assert err.request_id == "rid-fallback"
    assert str(err) == "Nebula API error (status 404)"
