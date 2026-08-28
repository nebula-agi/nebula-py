# Handwritten Nebula DX layer.
#
# Carries only the methods that need real dispatch logic: positional
# connector helpers and auth normalization.
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
        return await self.memory.list(**params)

    # ---- connectors ----

    async def connect_provider(
        self,
        provider: str,
        collection_id: str,
        config: Optional[Mapping[str, Any]] = None,
        oauth_client_mode: Optional[str] = None,
        oauth_client_id: Optional[str] = None,
        oauth_client_secret: Optional[str] = None,
    ) -> Any:
        """Custom signature: positional provider + collection_id + optional
        config/OAuth fields, packed into the wire body shape."""
        body: dict[str, Any] = {"collection_id": collection_id}
        if config is not None:
            body["config"] = dict(config)
        if oauth_client_mode is not None:
            body["oauth_client_mode"] = oauth_client_mode
        if oauth_client_id is not None:
            body["oauth_client_id"] = oauth_client_id
        if oauth_client_secret is not None:
            body["oauth_client_secret"] = oauth_client_secret
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


def _listify(value: str | Sequence[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)
