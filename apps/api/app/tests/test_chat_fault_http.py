import asyncio
import uuid

import httpx
from app.tests.support.chat_client import (
    current,
    events,
    message,
    packet,
    plan,
    public_only,
    release,
    runtime,
    settled,
    state,
    text_call,
    token,
    turn,
)

__all__ = ["runtime"]


async def test_lost_terminal_ack_requires_recovery_then_replays(runtime):
    await plan(runtime, [text_call("That team had a real chance.", "finish")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=30, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            assert response.status_code == 200
            iterator = events(response)
            prefix = []
            async with asyncio.timeout(10):
                while not any(name == "delta" for name, _ in prefix):
                    prefix.append(await anext(iterator))
            assert "real chance" in "".join(p.get("text", "") for n, p in prefix if n == "delta")
            before = await current(client, headers)
            assert before["exchanges"][0]["reply"]["status"] == "writing"
            runtime.proxy.arm_terminal_response_loss(headers["X-Chat-Token"])
            await release(runtime, "finish")
            async with asyncio.timeout(10):
                await runtime.proxy.fired.wait()
            read_task = asyncio.create_task(client.get("/chat/current", headers=headers))
            async with asyncio.timeout(10):
                await runtime.proxy.reads_held.wait()
            assert not read_task.done()

            rest = []

            async def remaining():
                async for item in iterator:
                    rest.append(item)

            pending = asyncio.create_task(remaining())
            done, _ = await asyncio.wait({pending}, timeout=1)
            public_only(rest)
            assert not any(name == "settled" for name, _ in rest)
            if done:
                pending.result()
                assert any(name == "recovery" for name, _ in rest)
            runtime.proxy.release()
            read_response = await read_task
            assert read_response.status_code == 200, read_response.text
            async with asyncio.timeout(20):
                await pending
        public_only(prefix + rest)
        canonical = await current(client, headers)
        reply = canonical["exchanges"][0]["reply"]
        assert reply["status"] == "complete"
        assert reply["text"] == "That team had a real chance."
        assert canonical["revision"] > before["revision"]
        replay = await turn(client, headers, command)
        assert settled(replay) == canonical
        assert not any(name == "delta" for name, _ in replay)
        assert len((await state(runtime))["requests"]) == 1


async def test_expired_owner_cannot_publish_or_overwrite_retry(runtime):
    old = {
        "steps": [
            {"data": packet("The first thought.")},
            {"gate": "old"},
            {"data": packet(" Stale owner returns.")},
            {"data": packet(finish="stop")},
            {"data": "[DONE]"},
        ]
    }
    await plan(runtime, [old, text_call("A fresh answer.", "retry")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=30, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            assert response.status_code == 200
            old_events = events(response)
            async with asyncio.timeout(10):
                while (await anext(old_events))[0] != "delta":
                    pass
            writing = await current(client, headers)
            assert writing["exchanges"][0]["reply"]["status"] == "writing"
            await runtime.proxy.expire_lease(headers["X-Chat-Token"])
            async with asyncio.timeout(10):
                while True:
                    orphan = await current(client, headers)
                    if orphan["exchanges"][0]["reply"]["status"] != "writing":
                        break
                    await asyncio.sleep(0.05)
            assert orphan["exchanges"][0]["reply"]["status"] == "interrupted"
            assert "The first thought." in orphan["exchanges"][0]["reply"]["text"]
            retry = {
                "kind": "retry",
                "request_id": str(uuid.uuid4()),
                "expected_revision": orphan["revision"],
                "exchange_id": command["request_id"],
            }
            async with client.stream(
                "POST", "/chat/turns", headers=headers, json=retry
            ) as retry_response:
                assert retry_response.status_code == 200
                retry_events = events(retry_response)
                retry_prefix = []
                async with asyncio.timeout(10):
                    while not any(name == "delta" for name, _ in retry_prefix):
                        retry_prefix.append(await anext(retry_events))
                active = await current(client, headers)
                assert active["exchanges"][0]["reply"]["id"] == retry["request_id"]
                await release(runtime, "old")
                async with asyncio.timeout(10):
                    old_tail = [item async for item in old_events]
                assert not any(
                    "Stale owner returns" in p.get("text", "") for n, p in old_tail if n == "delta"
                )
                assert await current(client, headers) == active
                await release(runtime, "retry")
                result = settled(retry_prefix + [item async for item in retry_events])
            assert len(result["exchanges"]) == 1
            assert result["exchanges"][0]["reply"]["id"] == retry["request_id"]
            assert result["exchanges"][0]["reply"]["status"] == "complete"
            assert result["exchanges"][0]["reply"]["text"] == "A fresh answer."
            assert await current(client, headers) == result
            assert len((await state(runtime))["requests"]) == 2


async def test_unknown_tool_receives_explicit_tool_error(runtime):
    call = {
        "index": 0,
        "id": "bad_tool",
        "type": "function",
        "function": {"name": "not_a_tool", "arguments": "{}"},
    }
    await plan(
        runtime,
        [
            {
                "steps": [
                    {"data": packet(tool_calls=[call])},
                    {"data": packet(finish="tool_calls")},
                    {"data": "[DONE]"},
                ]
            },
            text_call("I cannot check that."),
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        items = await turn(client, token(), message())
        public_only(items)
        requests = (await state(runtime))["requests"]
        assert len(requests) == 2
        results = [
            m
            for m in requests[1]["messages"]
            if m.get("role") == "tool" and m.get("tool_call_id") == "bad_tool"
        ]
        assert len(results) == 1
        assert (
            "error" in results[0]["content"].lower()
            or "unsupported" in results[0]["content"].lower()
        )
