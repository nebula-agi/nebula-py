from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, TypedDict

import httpx
from pydantic import BaseModel

from .errors import (
    NebulaAPIError,
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
    like datetimes / UUIDs become wire-ready strings; we do NOT set
    `exclude_none=True` because the API may distinguish explicit `null`
    from "absent" for optional fields.

    `warnings='none'` silences Pydantic's serializer warnings during dump.
    Those warnings can fire when generated model defaults are represented
    in a shape Pydantic does not expect, while the wire output remains
    correct.
    """
    if isinstance(body, BaseModel):
        return body.model_dump(mode="json", by_alias=True, warnings="none")
    if isinstance(body, list):
        return [
            item.model_dump(mode="json", by_alias=True, warnings="none")
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


class RequestArgs(TypedDict, total=False):
    method: str
    path: str
    path_params: Mapping[str, Any]
    query: Mapping[str, Any]
    body: Any
    headers: Mapping[str, str]
    routing: Mapping[str, Any]
    idempotent: bool


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

    def _build_headers(self, per_request: Optional[Mapping[str, str]], has_body: bool) -> dict[str, str]:
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
            headers.update(per_request)
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
        try:
            return float(value)
        except ValueError:
            pass
        # Per RFC 7231, Retry-After may also be an HTTP-date.
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            delta = (target - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, delta)
        except (TypeError, ValueError):
            return None

    async def request(self, args: RequestArgs) -> Any:
        method = args["method"].upper()
        path = self._resolve_path(args["path"], args.get("path_params"))
        query = self._filter_query(args.get("query"))
        body = _serialize_body(args.get("body"))
        has_body = body is not None
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
        idempotent = bool(args.get("idempotent", False))

        max_attempts = self._options.retry.max_retries + 1 if idempotent else 1
        last_error: Optional[BaseException] = None

        for attempt in range(max_attempts):
            try:
                response = await self._http.request(
                    method=method,
                    url=path,
                    params=query,
                    json=body if has_body else None,
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(backoff_seconds(attempt, self._options.retry))
                    last_error = exc
                    continue
                raise NebulaTimeoutError(
                    f"Request timed out after {self._options.timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(backoff_seconds(attempt, self._options.retry))
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
                await asyncio.sleep(
                    backoff_seconds(attempt, self._options.retry, retry_after)
                )
                last_error = err
                continue
            raise err

        if last_error is not None:
            raise NebulaConnectionError("retry budget exhausted") from last_error
        raise NebulaConnectionError("retry budget exhausted")


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _routing_headers_for_request(
    *,
    body: Any,
    path_params: Mapping[str, Any],
    query: Any,
    routing: Optional[Mapping[str, Any]],
) -> dict[str, str]:
    if not routing:
        return {}
    header = routing.get("header")
    body_fields = routing.get("body_fields")
    query_fields = routing.get("query_fields")
    path_fields = routing.get("path_fields")
    if (
        not isinstance(header, str)
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
    return {header: route_id} if route_id else {}


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
        value = body.get(name)
        if isinstance(value, str) and value:
            return value
    return None
