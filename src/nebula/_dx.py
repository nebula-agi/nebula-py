# Handwritten Nebula DX layer.
#
# Carries only the methods that need real dispatch logic: store_memory's
# create-vs-append branch, bulk store_memories with a concurrency cap,
# positional connector helpers (connect_provider, disconnect), and auth
# normalization.
#
# For everything else, use the resource methods directly. Resource methods
# now return unwrapped values natively (the generator peels the
# `{results: X}` wire envelope), so there's no separate auto-generated
# unwrap layer to extend.
#
# Source of truth: nebula-sdks/custom/python/_dx.py
# The generator copies this file into sdks/python/src/nebula/_dx.py on every
# `pnpm --dir nebula-sdks/generator run generate`. Edit the source, not the copy.

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any, Optional, cast

from ._client import NebulaClient
from ._runtime import ClientOptions


class Nebula(NebulaClient):
    """Nebula's handwritten DevEx facade on top of the generated async client."""

    def __init__(self, options: Optional[ClientOptions] = None, **compat: Any) -> None:
        """
        Accepts either a ClientOptions instance, or the snake_case keyword
        aliases ``api_key`` and ``base_url`` for ergonomic
        construction without instantiating ClientOptions first.
        """
        if options is None:
            options = ClientOptions()

        api_key = _first_defined(compat.get("api_key"), options.api_key)
        base_url = _first_defined(compat.get("base_url"), options.base_url)

        normalized = ClientOptions(
            base_url=base_url if base_url is not None else options.base_url,
            api_key=api_key,
            default_headers=options.default_headers,
            timeout_seconds=options.timeout_seconds,
            retry=options.retry,
            user_agent=options.user_agent,
            transport=options.transport,
        )
        super().__init__(normalized)

    # ---- memories ----

    async def store_memory(
        self,
        memory: Optional[Mapping[str, Any]] = None,
        **params: Any,
    ) -> Any:
        """
        Polymorphic memory creator: dispatches to memories.create or memories.append
        based on whether `memory_id` is set on the input. Returns the new memory id
        (string), or the updated snapshot envelope when `snapshot` is set.
        """
        body = _memory_params(memory, params)
        memory_id = _memory_id(body)

        # `memories.create` now returns the unwrapped inner type directly
        # (the generator peels the wire `{results: X}` envelope).
        if body.get("snapshot") is not None:
            result = await self.memories.create(body=cast(Any, _snapshot_create_params(body)))
            return _snapshot_result(result)

        if memory_id:
            await self.memories.append(
                id=str(memory_id),
                body=cast(Any, _memory_append_params(body)),
            )
            return str(memory_id)

        result = await self.memories.create(body=cast(Any, _memory_create_params(body)))
        return _extract_id(result)

    async def store_memories(
        self,
        memories: Sequence[Mapping[str, Any]],
        *,
        max_concurrency: int = 8,
        **options: Any,
    ) -> list[Any]:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def worker(memory: Mapping[str, Any]) -> Any:
            async with semaphore:
                return await self.store_memory(memory, **options)

        return await asyncio.gather(*(worker(memory) for memory in memories))

    # ---- memories ----

    async def list_memories(
        self,
        collection_ids: Optional[str | Sequence[str]] = None,
        **params: Any,
    ) -> Any:
        """Override of generated list_memories to add the
        collection_ids-as-str-or-list shortcut + metadata_filters JSON
        encoding. The simple generated form is replaced by this richer one.
        """
        if collection_ids is not None:
            params["collection_ids"] = _listify(collection_ids)
        if isinstance(params.get("metadata_filters"), Mapping):
            params["metadata_filters"] = json.dumps(params["metadata_filters"])
        return await self.memories.list(**params)

    # ---- connectors ----

    async def connect_provider(
        self,
        provider: str,
        collection_id: str,
        config: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Custom signature: positional provider + collection_id + optional
        config dict, packed into the wire body shape."""
        body: dict[str, Any] = {"collection_id": collection_id}
        if config is not None:
            body["config"] = dict(config)
        return await self.connectors.connect(provider=provider, body=cast(Any, body))

    async def disconnect(
        self,
        connection_id: str,
        delete_memories: bool = False,
    ) -> Any:
        """Disconnect a connector by id. Positional shortcut."""
        return await self.connectors.disconnect(
            connection_id=connection_id, delete_memories=delete_memories
        )

# ---------- helpers ----------


def _first_defined(*values: Optional[Any]) -> Optional[Any]:
    for value in values:
        if value is not None:
            return value
    return None


def _memory_params(
    memory: Optional[Mapping[str, Any]], params: Mapping[str, Any]
) -> dict[str, Any]:
    body: dict[str, Any] = dict(memory or {})
    body.update(params)
    if "collectionId" in body and "collection_id" not in body:
        body["collection_id"] = body.pop("collectionId")
    else:
        body.pop("collectionId", None)
    if "memoryId" in body and "memory_id" not in body:
        body["memory_id"] = body.pop("memoryId")
    else:
        body.pop("memoryId", None)
    content = body.pop("content", None)
    if content is not None:
        if isinstance(content, str):
            body.setdefault("raw_text", content)
        else:
            body.setdefault("content_parts", content)
    if body.get("messages") and not body.get("kind"):
        body["kind"] = "conversation"
    return body


def _memory_id(memory: Mapping[str, Any]) -> Any:
    return memory.get("memory_id") or memory.get("memoryId")


def _memory_create_params(body: Mapping[str, Any]) -> dict[str, Any]:
    params = dict(body)
    params.pop("memory_id", None)
    return params


def _snapshot_create_params(body: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"snapshot": body["snapshot"]}
    if isinstance(body.get("raw_text"), str):
        params["raw_text"] = body["raw_text"]
    if isinstance(body.get("contents"), list):
        params["contents"] = body["contents"]
    return params


def _memory_append_params(body: Mapping[str, Any]) -> dict[str, Any]:
    collection_id = body.get("collection_id")
    if not collection_id:
        raise ValueError(
            "collection_id is required when appending to an existing memory"
        )
    params: dict[str, Any] = {"collection_id": collection_id}
    for key in (
        "metadata",
        "ingestion_config",
        "raw_text",
        "chunks",
        "messages",
    ):
        if body.get(key) is not None:
            params[key] = body[key]
    return params


def _extract_value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _snapshot_result(value: Any) -> Any:
    return _extract_value(value, "snapshot", value)


def _extract_id(value: Any) -> str:
    mapping = value if isinstance(value, Mapping) else None
    for key in ("id", "memory_id", "engram_id", "ephemeral_collection_id"):
        attr = getattr(value, key, None)
        if isinstance(attr, str):
            return attr
        if mapping is not None:
            mapped = mapping.get(key)
            if isinstance(mapped, str):
                return mapped
    raise RuntimeError("Nebula memory create response did not include an id")


def _listify(value: str | Sequence[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)
