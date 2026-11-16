from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import Receive, Scope, Send

from app.api.rate_limit import rate_limit
from app.conversation.domain import (
    TOKEN_PATTERN,
    CancelCommand,
    MessageCommand,
    Rejected,
    RetryCommand,
    Snapshot,
)
from app.conversation.store import StoreUnavailable, conversation_store
from app.conversation.turn import Emit, Turn, lease_seconds
from app.core.config import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])

NO_STORE = {"Cache-Control": "no-store"}
_MESSAGES = {
    "invalid_token": "A valid conversation token is required.",
    "revision_conflict": "The conversation changed. Refresh it before sending.",
    "request_conflict": "This request ID belongs to a different message.",
    "reply_pending": "This reply is still being written.",
    "conversation_busy": "Another reply is still being written.",
    "conversation_full": "This conversation is full. Start a new chat.",
    "not_retryable": "Only a stopped or interrupted latest reply can be retried.",
    "not_pending": "That reply is not being written.",
    "rate_limited": "Too many messages. Take a breather and try again soon.",
    "unavailable": "Chat is unavailable right now.",
}
_STATUS = {"invalid_token": 400, "rate_limited": 429, "unavailable": 503}


class _Problem(Exception):
    def __init__(self, code: str, current_revision: int | None = None):
        super().__init__(code)
        self.code, self.current_revision = code, current_revision


def problem(
    code: str, current_revision: int | None = None, request: Request | None = None
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": _MESSAGES[code]}
    if code == "revision_conflict" and current_revision is not None:
        error["current_revision"] = current_revision
    request_id = getattr(request.state, "request_id", None) if request is not None else None
    return JSONResponse(
        status_code=_STATUS.get(code, 409),
        content={"error": error, "request_id": request_id},
        headers=NO_STORE,
    )


def _token(request: Request) -> str:
    token = request.headers.get("x-chat-token", "")
    if not TOKEN_PATTERN.fullmatch(token):
        raise _Problem("invalid_token")
    return token


def frame(name: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n".encode()


async def _disconnect(receive: Receive) -> None:
    while (await receive())["type"] != "http.disconnect":
        pass


class EventStream(StreamingResponse):
    def __init__(self, produce: Callable[[Emit], Awaitable[None]]):
        super().__init__(
            content=iter(()),
            media_type="text/event-stream",
            headers={**NO_STORE, "X-Accel-Buffering": "no"},
        )
        self.produce = produce

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def emit(name: str, payload: dict[str, Any]) -> None:
            queue.put_nowait(frame(name, payload))

        async def owned() -> None:
            try:
                await self.produce(emit)
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(owned())
        gone = asyncio.create_task(_disconnect(receive))
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            while True:
                item = asyncio.ensure_future(queue.get())
                await asyncio.wait({item, gone}, return_when=asyncio.FIRST_COMPLETED)
                if not item.done():
                    item.cancel()
                    break
                body = item.result()
                await send(
                    {
                        "type": "http.response.body",
                        "body": body or b"",
                        "more_body": body is not None,
                    }
                )
                if body is None:
                    break
        except OSError:
            pass
        finally:
            gone.cancel()
            if not task.done():
                task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.wait({task})


def _replay(snapshot: Snapshot, request_id: str) -> EventStream:
    async def produce(emit: Emit) -> None:
        emit("settled", {"request_id": request_id, "snapshot": snapshot.public()})

    return EventStream(produce)


@router.post("/turns")
async def post_turn(
    request: Request,
    command: Annotated[MessageCommand | RetryCommand, Body(discriminator="kind")],
):
    try:
        token = _token(request)
        try:
            await rate_limit(request)
        except HTTPException as exc:
            if exc.status_code == 429:
                raise _Problem("rate_limited") from exc
            raise
        settings = get_settings()
        store = conversation_store()
        started = await store.begin(token, command, lease_seconds(settings))
    except _Problem as exc:
        return problem(exc.code, exc.current_revision, request)
    except Rejected as exc:
        return problem(exc.code, exc.current_revision, request)
    except StoreUnavailable:
        return problem("unavailable", request=request)
    if isinstance(started, Snapshot):
        return _replay(started, command.request_id)

    async def produce(emit: Emit) -> None:
        emit(
            "accepted",
            {
                "request_id": started.request_id,
                "exchange_id": started.exchange_id,
                "revision": started.revision,
            },
        )
        await Turn(store, started, settings, emit).run()

    return EventStream(produce)


@router.get("/current")
async def current(request: Request):
    try:
        snapshot = await conversation_store().current(_token(request))
    except _Problem as exc:
        return problem(exc.code, request=request)
    except StoreUnavailable:
        return problem("unavailable", request=request)
    return JSONResponse(snapshot.public(), headers=NO_STORE)


@router.post("/cancel")
async def cancel(request: Request, command: CancelCommand):
    try:
        snapshot = await conversation_store().cancel(
            _token(request), command.request_id, command.expected_revision
        )
    except _Problem as exc:
        return problem(exc.code, request=request)
    except Rejected as exc:
        return problem(exc.code, exc.current_revision, request)
    except StoreUnavailable:
        return problem("unavailable", request=request)
    return JSONResponse(snapshot.public(), headers=NO_STORE)
