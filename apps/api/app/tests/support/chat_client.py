from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from app.tests.support.conversation_runtime import ConversationRuntime, free_port
from redis.asyncio import Redis


def packet(text=None, *, finish=None, tool_calls=None):
    delta = {}
    if text is not None:
        delta["content"] = text
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def text_call(text, gate=None):
    steps = [{"data": packet(text)}]
    if gate:
        steps.append({"gate": gate})
    steps += [{"data": packet(finish="stop")}, {"data": "[DONE]"}]
    return {"steps": steps}


def message(text="Were we contenders?", revision=0):
    return {
        "kind": "message",
        "request_id": str(uuid.uuid4()),
        "expected_revision": revision,
        "message": text,
    }


def token():
    return {"X-Chat-Token": secrets.token_urlsafe(32)}


@pytest.fixture
async def runtime(tmp_path):
    service = ConversationRuntime(tmp_path, free_port(), free_port(), free_port())
    try:
        yield await service.start()
    finally:
        await service.stop()


async def plan(runtime, calls):
    async with httpx.AsyncClient(
        base_url=runtime.upstream_url, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        response = await client.post("/__control__/plan", json={"calls": calls})
        response.raise_for_status()


async def state(runtime):
    async with httpx.AsyncClient(
        base_url=runtime.upstream_url, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        response = await client.get("/__control__/state")
        response.raise_for_status()
        return response.json()


async def release(runtime, gate):
    async with httpx.AsyncClient(
        base_url=runtime.upstream_url, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        response = await client.post("/__control__/release", json={"gate": gate})
        response.raise_for_status()


async def events(response):
    event = None
    data = []
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line and data:
            payload = json.loads("\n".join(data))
            yield event or payload.get("type"), payload
            event, data = None, []


async def turn(client, headers, command):
    async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
        assert response.status_code == 200, await response.aread()
        return [item async for item in events(response)]


async def current(client, headers):
    response = await client.get("/chat/current", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def settled(items):
    return next(payload["snapshot"] for name, payload in items if name == "settled")


def public_only(items):
    allowed = {
        "accepted": {"request_id", "exchange_id", "revision"},
        "checking": {"request_id"},
        "delta": {"request_id", "text"},
        "settled": {"request_id", "snapshot"},
        "recovery": {"request_id", "code", "retryable"},
    }
    for name, payload in items:
        assert name in allowed
        assert set(payload) <= allowed[name] | {"type"}
        if name == "settled":
            snap = payload["snapshot"]
            assert set(snap) == {"revision", "exchanges"}
            for exchange in snap["exchanges"]:
                assert set(exchange) == {"id", "message", "reply"}
                assert set(exchange["reply"]) <= {"id", "text", "status", "reason"}


async def ledger(runtime):
    redis = Redis(host="127.0.0.1", port=runtime.redis_port)
    try:
        value = await redis.get(f"ai-budget:{datetime.now(UTC):%Y-%m}")
        return float(value or 0)
    finally:
        await redis.aclose()
