"""Real HTTP regressions for the season conversation boundary.

The scripted upstream proves protocol behavior, not model voice or factual quality.
The fixture's Boston games are not the production Cleveland game.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from app.tests.support.chat_client import (
    current,
    events,
    ledger,
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
from app.tests.support.conversation_runtime import ConversationRuntime, free_port

__all__ = ["runtime"]


async def test_stream_is_live_and_replay_does_not_generate(runtime):
    await plan(runtime, [text_call("The Knicks were dangerous.", "finish")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            assert response.status_code == 200
            iterator = events(response)
            prefix = []
            async with asyncio.timeout(10):
                while not any(name == "delta" for name, _ in prefix):
                    prefix.append(await anext(iterator))
            assert "dangerous" in "".join(p.get("text", "") for n, p in prefix if n == "delta")
            assert not (await state(runtime))["gates"]["finish"]
            snapshot = await current(client, headers)
            assert snapshot["exchanges"][0]["reply"]["status"] == "writing"
            await release(runtime, "finish")
            items = prefix + [item async for item in iterator]
        public_only(items)
        canonical = settled(items)
        replay = await turn(client, headers, command)
        assert settled(replay) == canonical
        assert not any(name == "delta" for name, _ in replay)
        assert len((await state(runtime))["requests"]) == 1


async def test_duplicate_conflict_and_revision_are_fenced(runtime):
    await plan(runtime, [text_call("I think so.", "finish")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            iterator = events(response)
            async with asyncio.timeout(10):
                while (await anext(iterator))[0] != "delta":
                    pass
            duplicate = await client.post("/chat/turns", headers=headers, json=command)
            assert duplicate.status_code in (409, 425) or "pending" in duplicate.text.lower()
            conflict = await client.post(
                "/chat/turns", headers=headers, json={**command, "message": "Different message"}
            )
            assert conflict.status_code == 409
            await release(runtime, "finish")
            _ = [item async for item in iterator]
        stale = await client.post(
            "/chat/turns", headers=headers, json=message("Another thought", 0)
        )
        assert stale.status_code == 409
        assert len((await state(runtime))["requests"]) == 1


async def test_stop_preserves_prefix_retry_replaces_reply_and_stale_stop_is_fenced(runtime):
    await plan(
        runtime, [text_call("A strong start.", "first"), text_call("A better answer.", "second")]
    )
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            iterator = events(response)
            async with asyncio.timeout(10):
                while (await anext(iterator))[0] != "delta":
                    pass
            snapshot = await current(client, headers)
            stop = await client.post(
                "/chat/cancel",
                headers=headers,
                json={
                    "request_id": command["request_id"],
                    "expected_revision": snapshot["revision"],
                },
            )
            assert stop.status_code == 200, stop.text
            stopped = await current(client, headers)
            reply = stopped["exchanges"][0]["reply"]
            assert reply["status"] == "stopped" and "strong start" in reply["text"]
            await release(runtime, "first")
        retry = {
            "kind": "retry",
            "request_id": str(uuid.uuid4()),
            "expected_revision": stopped["revision"],
            "exchange_id": command["request_id"],
        }
        async with client.stream("POST", "/chat/turns", headers=headers, json=retry) as response:
            iterator = events(response)
            async with asyncio.timeout(10):
                while (await anext(iterator))[0] != "delta":
                    pass
            active = await current(client, headers)
            await client.post(
                "/chat/cancel",
                headers=headers,
                json={"request_id": command["request_id"], "expected_revision": active["revision"]},
            )
            assert (await current(client, headers))["exchanges"][0]["reply"]["id"] == retry[
                "request_id"
            ]
            assert (await current(client, headers))["exchanges"][0]["reply"]["status"] == "writing"
            await release(runtime, "second")
            result = settled([item async for item in iterator])
        assert len(result["exchanges"]) == 1
        assert result["exchanges"][0]["message"] == command["message"]
        assert result["exchanges"][0]["reply"]["text"] == "A better answer."


async def test_disconnect_reconciles_without_regeneration(runtime):
    await plan(runtime, [text_call("First sentence.", "blocked")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            iterator = events(response)
            async with asyncio.timeout(10):
                while (await anext(iterator))[0] != "delta":
                    pass
        await release(runtime, "blocked")
        async with asyncio.timeout(10):
            while True:
                snapshot = await current(client, headers)
                if snapshot["exchanges"][0]["reply"]["status"] != "writing":
                    break
                await asyncio.sleep(0.05)
        assert snapshot["exchanges"][0]["reply"]["status"] == "interrupted"
        assert "First sentence" in snapshot["exchanges"][0]["reply"]["text"]
        assert len((await state(runtime))["requests"]) == 1


@pytest.mark.parametrize(
    "unsafe",
    ["Brunson scored 999 points.", "Towns scored 20 points.", "The Knicks scored 999 points."],
)
async def test_unverified_numbers_never_reach_client(runtime, unsafe):
    await plan(runtime, [text_call(unsafe), text_call("I cannot verify that.")])
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        items = await turn(client, headers, message("Brunson scored 999 points. Is that right?"))
        public_only(items)
        visible = " ".join(p.get("text", "") for name, p in items if name == "delta")
        assert unsafe not in visible
        assert "999" not in visible
        assert "Towns scored 20" not in visible


async def test_lookup_reference_expands_real_fixture_fact(runtime):
    call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "lookup",
            "arguments": json.dumps(
                {
                    "question": (
                        "How many points did Jalen Brunson score against Boston on January 1, 2026?"
                    )
                }
            ),
        },
    }
    await plan(
        runtime,
        [
            {
                "steps": [
                    {"data": packet("Let me check. ")},
                    {"data": packet(tool_calls=[{"index": 0, **call}])},
                    {"data": packet(finish="tool_calls")},
                    {"data": "[DONE]"},
                ]
            },
            {"steps": [{"lookup_refs": True}, {"data": packet(finish="stop")}, {"data": "[DONE]"}]},
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        items = await turn(
            client,
            token(),
            message("How many points did Jalen Brunson score against Boston on January 1, 2026?"),
        )
        public_only(items)
        text = settled(items)["exchanges"][0]["reply"]["text"]
        assert "Brunson" in text and "20" in text
        assert "[[" not in text and "analytics-" not in text
        assert len((await state(runtime))["requests"]) == 2


async def test_old_public_records_are_retired_in_production_profile(runtime):
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        for path in (
            "/games",
            "/players",
            "/teams",
            "/reports",
            "/analysis",
            "/api/games",
            "/api/reports",
        ):
            response = await client.get(path)
            assert response.status_code in (404, 405, 410), (
                path,
                response.status_code,
                response.text,
            )


async def test_first_send_lost_after_acceptance_reconciles_without_duplicate(runtime):
    await plan(runtime, [text_call("We had a shot.", "finish")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            iterator = events(response)
            async with asyncio.timeout(10):
                while (await anext(iterator))[0] != "accepted":
                    pass
        await release(runtime, "finish")
        async with asyncio.timeout(10):
            while True:
                snapshot = await current(client, headers)
                if snapshot["exchanges"][0]["reply"]["status"] != "writing":
                    break
                await asyncio.sleep(0.05)
        assert len(snapshot["exchanges"]) == 1
        assert snapshot["exchanges"][0]["id"] == command["request_id"]
        assert len((await state(runtime))["requests"]) <= 1


async def test_completion_before_stop_remains_complete(runtime):
    await plan(runtime, [text_call("That team could compete.")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        completed = settled(await turn(client, headers, command))
        assert completed["exchanges"][0]["reply"]["status"] == "complete"
        await client.post(
            "/chat/cancel",
            headers=headers,
            json={"request_id": command["request_id"], "expected_revision": completed["revision"]},
        )
        assert await current(client, headers) == completed


async def test_fragmented_tool_call_and_usage_only_packet(runtime):
    tool1 = {
        "index": 0,
        "id": "call_fragment",
        "type": "function",
        "function": {"name": "look", "arguments": '{"question":"How many '},
    }
    tool2 = {
        "index": 0,
        "function": {
            "name": "up",
            "arguments": 'points did Brunson score against Boston on January 1, 2026?"}',
        },
    }
    await plan(
        runtime,
        [
            {
                "steps": [
                    {"data": packet("Let me check. ")},
                    {"data": packet(tool_calls=[tool1]), "fragment_bytes": 1},
                    {"data": packet(tool_calls=[tool2]), "fragment_bytes": 2},
                    {"data": packet(finish="tool_calls")},
                    {
                        "data": {
                            "choices": [],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 5,
                                "total_tokens": 15,
                            },
                        }
                    },
                    {"data": "[DONE]"},
                ]
            },
            {"steps": [{"lookup_refs": True}, {"data": packet(finish="stop")}, {"data": "[DONE]"}]},
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        items = await turn(
            client,
            token(),
            message("How many points did Brunson score against Boston on January 1, 2026?"),
        )
        text = settled(items)["exchanges"][0]["reply"]["text"]
        assert "20" in text and "Brunson" in text
        public_only(items)


async def test_missing_credentials_are_not_mock_success(tmp_path):
    runtime = ConversationRuntime(
        tmp_path, free_port(), free_port(), free_port(), {"AI_API_KEY": ""}
    )
    try:
        await runtime.start()
        async with httpx.AsyncClient(
            base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
        ) as client:
            response = await client.post("/chat/turns", headers=token(), json=message())
            assert (
                response.status_code >= 400
                or "recovery" in response.text
                or "interrupted" in response.text
            )
            assert len((await state(runtime))["requests"]) == 0
    finally:
        await runtime.stop()


async def test_budget_cutoff_prevents_provider_call(tmp_path):
    runtime = ConversationRuntime(
        tmp_path, free_port(), free_port(), free_port(), {"OPENROUTER_MONTHLY_CUTOFF_USD": "0.001"}
    )
    try:
        await runtime.start()
        async with httpx.AsyncClient(
            base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
        ) as client:
            response = await client.post("/chat/turns", headers=token(), json=message())
            assert (
                response.status_code >= 400
                or "recovery" in response.text
                or "interrupted" in response.text
            )
            assert len((await state(runtime))["requests"]) == 0
    finally:
        await runtime.stop()


async def test_unknown_usage_remains_charged(runtime):
    await plan(
        runtime,
        [
            {
                "steps": [
                    {"data": packet("A partial answer.")},
                    {"data": packet(finish="stop")},
                    {"data": "[DONE]"},
                ]
            }
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        await turn(client, token(), message())
    assert await ledger(runtime) > 0


async def test_cancelled_provider_call_remains_charged(runtime):
    await plan(runtime, [text_call("A partial answer.", "finish")])
    headers, command = token(), message()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            iterator = events(response)
            async with asyncio.timeout(10):
                while (await anext(iterator))[0] != "delta":
                    pass
            revision = (await current(client, headers))["revision"]
            stopped = await client.post(
                "/chat/cancel",
                headers=headers,
                json={"request_id": command["request_id"], "expected_revision": revision},
            )
            assert stopped.status_code == 200
            await release(runtime, "finish")
    assert await ledger(runtime) > 0


async def test_invalid_and_excess_tool_calls_all_receive_results(runtime):
    calls = [
        {
            "index": index,
            "id": f"call_{index}",
            "type": "function",
            "function": {"name": "lookup", "arguments": "not-json" if index == 0 else "{}"},
        }
        for index in range(8)
    ]
    await plan(
        runtime,
        [
            {
                "steps": [
                    {"data": packet(tool_calls=calls)},
                    {"data": packet(finish="tool_calls")},
                    {"data": "[DONE]"},
                ]
            },
            text_call("I cannot verify that."),
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        items = await turn(client, token(), message())
        public_only(items)
        requests = (await state(runtime))["requests"]
        assert len(requests) == 2
        results = [m for m in requests[1]["messages"] if m.get("role") == "tool"]
        assert {m["tool_call_id"] for m in results} == {call["id"] for call in calls}
        assert all(
            "error" in m["content"].lower()
            or "invalid" in m["content"].lower()
            or "unsupported" in m["content"].lower()
            for m in results
        )


async def test_verified_player_fact_does_not_authorize_another_player(runtime):
    call = {
        "index": 0,
        "id": "brunson_lookup",
        "type": "function",
        "function": {
            "name": "lookup",
            "arguments": json.dumps(
                {"question": "How many points did Brunson score against Boston on January 1, 2026?"}
            ),
        },
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
            text_call("Towns scored 20 points."),
            text_call("I cannot verify that claim."),
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, timeout=20, headers={"X-Forwarded-Proto": "https"}
    ) as client:
        items = await turn(
            client, token(), message("Did Towns score 20? Check Brunson's score too.")
        )
        public_only(items)
        visible = " ".join(payload.get("text", "") for name, payload in items if name == "delta")
        assert "Towns scored 20" not in visible
        requests = (await state(runtime))["requests"]
        assert any(
            message.get("role") == "tool" and "20" in message.get("content", "")
            for request in requests
            for message in request.get("messages", [])
        )
