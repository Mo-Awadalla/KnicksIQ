"""Bound public request bodies and redact configured error telemetry."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BYTES = 128 * 1024

DEFAULT_READ_TIMEOUT_SECONDS = 30.0

_BODIED_METHODS = frozenset({"POST", "PUT", "PATCH"})
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_REDACTED = "<redacted>"

_RESERVED_REQUEST_KEYS = ("data", "headers", "cookies", "env", "query_string")
_FRAME_CONTENT_KEYS = ("vars",)
_SPAN_SENSITIVE_KEYS = frozenset(
    {
        "url",
        "http.url",
        "http.query",
        "http.request.parameter",
        "db.statement",
        "db.params",
        "db.query",
        "graphql.query",
        "graphql.variables",
        "prompt",
        "question",
        "body",
        "params",
    }
)


def _header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers", ()):  # type: ignore[union-attr]
        if key.lower() == name:
            return value
    return None


def _declared_length(scope: Scope) -> int | None:
    """Return ``Content-Length`` when it is trustworthy, else ``None``.

    A chunked transfer ignores any ``Content-Length`` (§3.3.3 RFC 7230), and a
    malformed or negative length is treated as absent so the streaming cap
    still governs the body.
    """
    transfer_encoding = _header(scope, b"transfer-encoding")
    if transfer_encoding and b"chunked" in transfer_encoding.lower():
        return None
    raw = _header(scope, b"content-length")
    if raw is None:
        return None
    try:
        declared = int(raw.decode("ascii", "strict").strip())
    except (UnicodeDecodeError, ValueError):
        return None
    return declared if declared >= 0 else None


def request_id_for(scope: Scope) -> str:
    """Let the outer request middleware establish the id reused by inner errors."""
    state = scope.get("state")
    candidate = state.get("request_id") if isinstance(state, dict) else None
    if not isinstance(candidate, str) or not candidate:
        header = _header(scope, b"x-request-id")
        candidate = header.decode("latin-1").strip() if header else ""
    if _SAFE_REQUEST_ID.match(candidate):
        return candidate
    return uuid.uuid4().hex


def _error_body(code: str, message: str, request_id: str) -> bytes:
    return json.dumps(
        {"error": {"code": code, "message": message}, "request_id": request_id},
        separators=(",", ":"),
    ).encode()


async def _send_error(
    send: Send,
    *,
    status: int,
    code: str,
    message: str,
    request_id: str,
    close: bool = False,
) -> None:
    body = _error_body(code, message, request_id)
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"x-request-id", request_id.encode()),
        (b"x-content-type-options", b"nosniff"),
        (b"cache-control", b"no-store"),
    ]
    if close:
        # The remainder of an oversized body is never drained; closing the
        # connection is what stops it being parsed as another request.
        headers.append((b"connection", b"close"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


class RequestBodyLimitMiddleware:
    """Cap the public request body before it reaches the application.

    Memory is bounded by ``max_bytes`` plus one incoming ASGI chunk: a chunk
    that would cross the cap is never stored.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int = MAX_REQUEST_BYTES,
        read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.read_timeout = read_timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = request_id_for(scope)
        if isinstance(scope.get("state"), dict):
            scope["state"]["request_id"] = request_id

        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _send_error(
                send,
                status=413,
                code="request_too_large",
                message=f"Request body exceeds {self.max_bytes} bytes",
                request_id=request_id,
                close=True,
            )
            return

        if scope.get("method", "").upper() not in _BODIED_METHODS:
            await self.app(scope, receive, send)
            return

        buffered = bytearray()
        try:
            async with asyncio.timeout(self.read_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        # The client is gone. Answer anyway so outer middleware
                        # still sees a complete response; the transport drops it.
                        await _send_error(
                            send,
                            status=400,
                            code="request_incomplete",
                            message="Client disconnected before the request body was complete",
                            request_id=request_id,
                        )
                        return
                    if message["type"] != "http.request":
                        continue
                    chunk = message.get("body") or b""
                    if len(buffered) + len(chunk) > self.max_bytes:
                        await _send_error(
                            send,
                            status=413,
                            code="request_too_large",
                            message=f"Request body exceeds {self.max_bytes} bytes",
                            request_id=request_id,
                            close=True,
                        )
                        return
                    buffered.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await _send_error(
                send,
                status=408,
                code="request_timeout",
                message="Request body was not delivered in time",
                request_id=request_id,
                close=True,
            )
            return

        body = bytes(buffered)
        del buffered
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def _without_query(value: str) -> str:
    head, separator, _ = value.partition("?")
    return head if separator else value


def _scrub_request(request: Any) -> None:
    if not isinstance(request, dict):
        return
    for key in _RESERVED_REQUEST_KEYS:
        request.pop(key, None)
    url = request.get("url")
    if isinstance(url, str):
        request["url"] = _without_query(url)


def _scrub_stacktrace(stacktrace: Any) -> None:
    if not isinstance(stacktrace, dict):
        return
    frames = stacktrace.get("frames")
    if not isinstance(frames, list):
        return
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        for key in _FRAME_CONTENT_KEYS:
            frame.pop(key, None)


def _scrub_exception(exception: Any) -> None:
    if not isinstance(exception, dict):
        return
    values = exception.get("values")
    if not isinstance(values, list):
        return
    for value in values:
        if not isinstance(value, dict):
            continue
        if "value" in value:
            value["value"] = _REDACTED
        _scrub_stacktrace(value.get("stacktrace"))


def _scrub_breadcrumbs(breadcrumbs: Any) -> None:
    if not isinstance(breadcrumbs, dict):
        return
    values = breadcrumbs.get("values")
    if not isinstance(values, list):
        return
    for breadcrumb in values:
        if not isinstance(breadcrumb, dict):
            continue
        breadcrumb.pop("data", None)
        breadcrumb.pop("message", None)


_HTTP_DESCRIPTION = re.compile(r"^[A-Z]{3,10} \S+\?")


def _scrub_span(span: Any) -> None:
    if not isinstance(span, dict):
        return
    data = span.get("data")
    if isinstance(data, dict):
        for key in list(data):
            if key in _SPAN_SENSITIVE_KEYS or key.endswith(("_query", "_url", "_body")):
                data.pop(key, None)
            elif key.endswith("target") and isinstance(data[key], str):
                data[key] = _without_query(data[key])
    description = span.get("description")
    if isinstance(description, str) and _HTTP_DESCRIPTION.match(description):
        # SQL descriptions use "?" placeholders, unlike HTTP query strings.
        span["description"] = _without_query(description)


def _scrub_sampling_context(event: dict[str, Any]) -> None:
    """Strip the query from the transaction name the SDK copies into the envelope header.

    ``Client.capture_event`` lifts ``contexts.trace.dynamic_sampling_context``
    out of the event after these callbacks run, so a name left here reaches the
    wire even though the event itself was scrubbed.
    """
    contexts = event.get("contexts")
    trace = contexts.get("trace") if isinstance(contexts, dict) else None
    context = trace.get("dynamic_sampling_context") if isinstance(trace, dict) else None
    if not isinstance(context, dict):
        return
    name = context.get("transaction")
    if isinstance(name, str):
        context["transaction"] = _without_query(name)


def _scrub_transaction(event: dict[str, Any]) -> None:
    _scrub_sampling_context(event)
    transaction = event.get("transaction")
    if isinstance(transaction, str):
        event["transaction"] = _without_query(transaction)
    spans = event.get("spans")
    if isinstance(spans, list):
        for span in spans:
            _scrub_span(span)


def scrub_sentry_event(event: dict[str, Any], hint: Any = None) -> dict[str, Any]:
    """Remove user content from a Sentry error or transaction event.

    Pass as both ``before_send`` and ``before_send_transaction``. The hint is
    accepted for the SDK signature and never inspected.
    """
    del hint
    if not isinstance(event, dict):
        return event
    event.pop("user", None)
    _scrub_request(event.get("request"))
    _scrub_exception(event.get("exception"))
    threads = event.get("threads")
    if isinstance(threads, dict):
        values = threads.get("values")
        if isinstance(values, list):
            for thread in values:
                if isinstance(thread, dict):
                    _scrub_stacktrace(thread.get("stacktrace"))
    _scrub_breadcrumbs(event.get("breadcrumbs"))
    _scrub_transaction(event)
    return event


SENTRY_INIT_OPTIONS: dict[str, Any] = {
    "send_default_pii": False,
    "max_request_body_size": "never",
    "include_local_variables": False,
    "attach_stacktrace": False,
    "before_send": scrub_sentry_event,
    "before_send_transaction": scrub_sentry_event,
}
