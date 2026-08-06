from __future__ import annotations

from typing import Any, Mapping, Optional

from .public_api_error import PublicApiError, parse_public_api_error


class NebulaError(Exception):
    pass


class NebulaConnectionError(NebulaError):
    pass


class NebulaTimeoutError(NebulaError):
    pass


def _envelope_fields(
    body: Any,
) -> tuple[Optional[str], Optional[str], Optional[str], Any]:
    """Extract (type, message, code, details) from the canonical envelope.

    Returns all-None when the body isn't a dict with str `type` + str
    `message`, so callers fall back to status-derived defaults. `details`
    is preserved as-is (typed `Any`) — the server emits arbitrary JSON
    here, most notably an array of {loc, msg, type} for validation
    errors. Narrowing to `Mapping` here would silently drop those.
    """
    if not isinstance(body, Mapping):
        return (None, None, None, None)
    etype = body.get("type")
    emsg = body.get("message")
    if not isinstance(etype, str) or not isinstance(emsg, str):
        return (None, None, None, None)
    ecode = body.get("code") if isinstance(body.get("code"), str) else None
    edetails = body.get("details")
    return (etype, emsg, ecode, edetails)


class NebulaAPIError(NebulaError):
    def __init__(
        self,
        status: int,
        body: Any,
        request_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        env_type, env_msg, env_code, env_details = _envelope_fields(body)
        super().__init__(message or env_msg or f"Nebula API error (status {status})")
        self.status = status
        self.body = body
        # The envelope's request_id is server-stamped and authoritative;
        # the header we captured at the transport should match, but if it
        # doesn't, prefer the envelope.
        env_rid = body.get("request_id") if isinstance(body, Mapping) else None
        self.request_id = env_rid if isinstance(env_rid, str) else request_id
        self.type: Optional[str] = env_type
        self.code: Optional[str] = env_code
        self.details: Any = env_details
        self.public_error: Optional[PublicApiError] = parse_public_api_error(body)


class NebulaBadRequestError(NebulaAPIError):
    pass


class NebulaUnauthorizedError(NebulaAPIError):
    pass


class NebulaForbiddenError(NebulaAPIError):
    pass


class NebulaNotFoundError(NebulaAPIError):
    pass


class NebulaConflictError(NebulaAPIError):
    pass


class NebulaValidationError(NebulaAPIError):
    pass


class NebulaRateLimitError(NebulaAPIError):
    def __init__(
        self,
        status: int,
        body: Any,
        request_id: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(status=status, body=body, request_id=request_id)
        self.retry_after = retry_after


class NebulaServerError(NebulaAPIError):
    pass


_STATUS_TO_CLASS: dict[int, type[NebulaAPIError]] = {
    400: NebulaBadRequestError,
    401: NebulaUnauthorizedError,
    403: NebulaForbiddenError,
    404: NebulaNotFoundError,
    409: NebulaConflictError,
    422: NebulaValidationError,
}


def error_from_response(
    *,
    status: int,
    body: Any,
    request_id: Optional[str] = None,
    retry_after: Optional[float] = None,
) -> NebulaAPIError:
    if status == 429:
        return NebulaRateLimitError(
            status=status, body=body, request_id=request_id, retry_after=retry_after
        )
    cls = _STATUS_TO_CLASS.get(status)
    if cls is not None:
        return cls(status=status, body=body, request_id=request_id)
    if status >= 500:
        return NebulaServerError(status=status, body=body, request_id=request_id)
    return NebulaAPIError(status=status, body=body, request_id=request_id)
