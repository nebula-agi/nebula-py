from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, NotRequired, Optional, TypedDict
from uuid import uuid4

import httpx
from pydantic import BaseModel

from .errors import (
    NebulaConnectionError,
    NebulaTimeoutError,
    error_from_response,
)
from .retry import DEFAULT_RETRY, RetryPolicy, backoff_seconds, is_retryable_status


def _serialize_body(body: Any) -> Any:
    """Convert Pydantic models to JSON-ready dicts so httpx can serialize.

    httpx's `json=` arg uses stdlib `json.dumps`, which does not know how
    to serialize `BaseModel` instances. Generated method signatures expose
    bodies as typed Pydantic models for autocomplete DX, so the runtime
    is the right layer to dump them. We use `mode='json'` so nested types
    like datetimes / UUIDs become wire-ready strings. `exclude_unset=True`
    preserves the distinction between omitted fields and explicitly supplied
    defaults or nulls.

    `warnings='none'` silences Pydantic's serializer warnings during dump.
    Those warnings can fire when generated model defaults are represented
    in a shape Pydantic does not expect, while the wire output remains
    correct.
    """
    if isinstance(body, BaseModel):
        return body.model_dump(
            mode="json", by_alias=True, exclude_unset=True, warnings="none"
        )
    if isinstance(body, list):
        return [
            item.model_dump(
                mode="json", by_alias=True, exclude_unset=True, warnings="none"
            )
            if isinstance(item, BaseModel)
            else item
            for item in body
        ]
    return body


_DEFAULT_BASE_URL = "https://api.zeroset.com"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_USER_AGENT = "nebula-sdk-py/0.0.1"


@dataclass
class ClientOptions:
    base_url: str = _DEFAULT_BASE_URL
    api_key: Optional[str] = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = _DEFAULT_TIMEOUT
    retry: RetryPolicy = DEFAULT_RETRY
    user_agent: str = _DEFAULT_USER_AGENT
    transport: Optional[httpx.AsyncBaseTransport] = None


@dataclass(frozen=True)
class RequestOptions:
    """Per-call controls applied to one complete invocation."""

    timeout_seconds: Optional[float] = None


class MutationReplayIdentity(TypedDict):
    source: Literal["body", "header", "intrinsic"]
    name: str
    generated: NotRequired[Literal["uuid"]]


class GeneratedBodyField(TypedDict):
    path: list[str]
    kind: Literal["uuid"]


class Utf8ByteLimit(TypedDict):
    source: Literal["body", "header"]
    path: list[str]
    maximum: int


class RequestArgs(TypedDict, total=False):
    method: str
    path: str
    path_params: Mapping[str, Any]
    query: Mapping[str, Any]
    body: Any
    headers: Mapping[str, Optional[str]]
    routing: Mapping[str, Any]
    retryable: bool
    http_semantically_idempotent: bool
    mutation_replay_identity: MutationReplayIdentity
    utf8_byte_limits: list[Utf8ByteLimit]
    timeout_seconds: Optional[float]


def prepare_generated_body(
    body: Any,
    fields: list[GeneratedBodyField],
) -> Any:
    """Clone a body and fill generated fields before validation and transport."""
    prepared = _serialize_body(body)
    for generated_field in fields:
        prepared = _prepare_generated_path(
            prepared,
            generated_field["path"],
            generated_field["kind"],
            source=body,
        )
    return prepared


def _generated_source_child(source: Any, name: str) -> Any:
    if isinstance(source, BaseModel):
        return getattr(source, name, None)
    if isinstance(source, Mapping):
        return source.get(name)
    return None


def _prepare_generated_path(
    value: Any,
    path: list[str],
    kind: Literal["uuid"],
    *,
    source: Any = None,
) -> Any:
    if not path:
        return value
    head, *tail = path
    if head == "*":
        if value is None:
            return value
        if not isinstance(value, list):
            raise TypeError("Generated body field wildcard must traverse a list")
        source_items = source if isinstance(source, list) else [None] * len(value)
        return [
            _prepare_generated_path(
                item,
                tail,
                kind,
                source=source_items[index] if index < len(source_items) else None,
            )
            for index, item in enumerate(value)
        ]
    if value is None:
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Generated body field must traverse a mapping")
    copy = dict(value)
    source_child = _generated_source_child(source, head)
    if not tail:
        if copy.get(head) is None:
            copy[head] = (
                str(source_child)
                if source_child is not None
                else _generate_body_value(kind)
            )
    elif copy.get(head) is not None:
        copy[head] = _prepare_generated_path(
            copy[head],
            tail,
            kind,
            source=source_child,
        )
    return copy


def _generate_body_value(kind: Literal["uuid"]) -> str:
    if kind == "uuid":
        return str(uuid4())
    raise AssertionError(f"Unsupported generated body field kind: {kind}")


class NebulaCore:
    def __init__(self, options: Optional[ClientOptions] = None) -> None:
        self._options = options or ClientOptions()
        self._http = httpx.AsyncClient(
            base_url=self._options.base_url.rstrip("/"),
            timeout=self._options.timeout_seconds,
            transport=self._options.transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "NebulaCore":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    def _build_headers(self, per_request: Optional[Mapping[str, Optional[str]]], has_body: bool) -> dict[str, str]:
        headers: dict[str, str] = dict(self._options.default_headers)
        headers["User-Agent"] = self._options.user_agent
        headers["Accept"] = "application/json"
        if has_body:
            headers["Content-Type"] = "application/json"
        # The API key authenticates via the Authorization header -- the backend
        # resolves a Nebula API key (or, for internal callers, a JWT) from the
        # same bearer credential.
        if self._options.api_key:
            headers["Authorization"] = f"Bearer {self._options.api_key}"
        if per_request:
            headers.update({key: value for key, value in per_request.items() if value is not None})
        return headers

    @staticmethod
    def _resolve_path(path: str, path_params: Optional[Mapping[str, Any]]) -> str:
        if not path_params:
            return path
        resolved = path
        for k, v in path_params.items():
            resolved = resolved.replace("{" + k + "}", _quote(str(v)))
        return resolved

    @staticmethod
    def _filter_query(query: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
        if not query:
            return None
        out: dict[str, Any] = {}
        for k, v in query.items():
            if v is None:
                continue
            if isinstance(v, bool):
                out[k] = "true" if v else "false"
            elif isinstance(v, (list, tuple)):
                out[k] = [str(item) for item in v]
            else:
                out[k] = v
        return out or None

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> Optional[float]:
        """Accept both numeric-seconds and HTTP-date forms of Retry-After.

        Matches the TS runtime's parseRetryAfter so behavior is symmetric
        across SDKs. Returns the wait time in seconds (>= 0) or None.
        """
        if not value:
            return None
        normalized = value.strip()
        if normalized.isascii() and normalized.isdigit():
            return float(int(normalized))
        # Per RFC 7231, Retry-After may also be an HTTP-date.
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        try:
            target = parsedate_to_datetime(normalized)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            delta = (target - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, delta)
        except (TypeError, ValueError):
            return None

    async def request(self, args: RequestArgs) -> Any:
        timeout_seconds = args.get("timeout_seconds")
        if timeout_seconds is None:
            timeout_seconds = self._options.timeout_seconds
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        deadline = time.monotonic() + timeout_seconds
        method = args["method"].upper()
        path = self._resolve_path(args["path"], args.get("path_params"))
        query = self._filter_query(args.get("query"))
        body = _serialize_body(args.get("body"))
        has_body = body is not None
        encoded_body = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if has_body
            else None
        )
        route_headers = _routing_headers_for_request(
            body=body,
            path_params=args.get("path_params") or {},
            query=query,
            routing=args.get("routing"),
        )
        headers = self._build_headers(
            {**route_headers, **dict(args.get("headers") or {})},
            has_body,
        )
        _validate_utf8_byte_limits(
            body=body,
            headers=headers,
            limits=args.get("utf8_byte_limits", []),
        )
        retryable = bool(args.get("retryable", False))

        max_attempts = self._options.retry.max_retries + 1 if retryable else 1
        last_error: Optional[BaseException] = None

        for attempt in range(max_attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _invocation_timeout(timeout_seconds)
            try:
                async with asyncio.timeout(remaining):
                    response = await self._http.request(
                        method=method,
                        url=path,
                        params=query,
                        content=encoded_body,
                        headers=headers,
                        timeout=remaining,
                    )
            except (TimeoutError, httpx.TimeoutException) as exc:
                if time.monotonic() < deadline and attempt + 1 < max_attempts:
                    await _sleep_with_deadline(
                        backoff_seconds(attempt, self._options.retry),
                        deadline,
                        timeout_seconds,
                    )
                    last_error = exc
                    continue
                raise _invocation_timeout(timeout_seconds) from exc
            except httpx.HTTPError as exc:
                if attempt + 1 < max_attempts:
                    await _sleep_with_deadline(
                        backoff_seconds(attempt, self._options.retry),
                        deadline,
                        timeout_seconds,
                    )
                    last_error = exc
                    continue
                raise NebulaConnectionError(str(exc)) from exc

            if response.is_success:
                if response.status_code == 204:
                    return None
                if not response.content:
                    return None
                return response.json()

            try:
                body_parsed: Any = response.json()
            except Exception:
                body_parsed = response.text
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            err = error_from_response(
                status=response.status_code,
                body=body_parsed,
                request_id=response.headers.get("X-Request-Id"),
                retry_after=retry_after,
            )

            if is_retryable_status(response.status_code) and attempt + 1 < max_attempts:
                await _sleep_with_deadline(
                    backoff_seconds(attempt, self._options.retry, retry_after),
                    deadline,
                    timeout_seconds,
                )
                last_error = err
                continue
            raise err

        if last_error is not None:
            raise NebulaConnectionError("retry budget exhausted") from last_error
        raise NebulaConnectionError("retry budget exhausted")


def _invocation_timeout(timeout_seconds: float) -> NebulaTimeoutError:
    return NebulaTimeoutError(
        f"Invocation timed out after {timeout_seconds}s"
    )


async def _sleep_with_deadline(
    delay_seconds: float,
    deadline: float,
    timeout_seconds: float,
) -> None:
    remaining = deadline - time.monotonic()
    if delay_seconds >= remaining:
        raise _invocation_timeout(timeout_seconds)
    await asyncio.sleep(delay_seconds)
    if time.monotonic() >= deadline:
        raise _invocation_timeout(timeout_seconds)


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _validate_utf8_byte_limits(
    *,
    body: Any,
    headers: Mapping[str, Any],
    limits: list[Utf8ByteLimit],
) -> None:
    for limit in limits:
        root = body if limit["source"] == "body" else headers
        _validate_utf8_path(
            root,
            limit["path"],
            limit["maximum"],
            ".".join(limit["path"]),
        )


def _validate_utf8_path(
    value: Any,
    path: list[str],
    maximum: int,
    label: str,
) -> None:
    if not path:
        if isinstance(value, str) and len(value.encode("utf-8")) > maximum:
            raise ValueError(f"{label} must be at most {maximum} UTF-8 bytes")
        return
    head, *tail = path
    if head == "*":
        if isinstance(value, list):
            for item in value:
                _validate_utf8_path(item, tail, maximum, label)
        return
    if not isinstance(value, Mapping):
        return
    _validate_utf8_path(value.get(head), tail, maximum, label)


def _routing_headers_for_request(
    *,
    body: Any,
    path_params: Mapping[str, Any],
    query: Any,
    routing: Optional[Mapping[str, Any]],
) -> dict[str, str]:
    if not routing:
        return {}
    owner = routing.get("owner")
    body_fields = routing.get("body_fields")
    query_fields = routing.get("query_fields")
    path_fields = routing.get("path_fields")
    if (
        not isinstance(owner, str)
        or not _valid_field_list(body_fields)
        or not _valid_field_list(query_fields)
        or not _valid_field_list(path_fields)
    ):
        return {}
    route_id = (
        _string_field(body, *(body_fields or []))
        or _string_field(query, *(query_fields or []))
        or _string_field(path_params, *(path_fields or []))
    )
    return {"X-Nebula-Owner-Key": f"{owner}:{route_id}"} if route_id else {}


def _valid_field_list(value: Any) -> bool:
    return value is None or (
        isinstance(value, list) and all(isinstance(field, str) for field in value)
    )


def _string_field(
    body: Any,
    *names: str,
) -> Optional[str]:
    if not isinstance(body, Mapping):
        return None
    for name in names:
        route_id = _route_id_value(_nested_field(body, name))
        if route_id:
            return route_id
    return None


def _nested_field(body: Mapping[str, Any], path: str) -> Any:
    current: Any = body
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _route_id_value(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    if (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], str)
        and value[0]
    ):
        return value[0]
    if isinstance(value, Mapping):
        if "$eq" in value:
            return _route_id_value(value.get("$eq"))
        for op in ("$in", "$overlap"):
            if op in value:
                return _route_id_value(value.get(op))
    return None
