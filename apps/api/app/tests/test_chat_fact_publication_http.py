from __future__ import annotations

import asyncio
import re

import httpx
import pytest
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


@pytest.mark.parametrize(
    ("draft", "contradiction"),
    [
        ("Brunson dropped 20 in that one.", None),
        ("Brunson scored 20 points.", None),
        ("Brunson scored 20 against Boston.", None),
        ("Towns dropped 20 in that one.", "Towns"),
        ("Brunson dropped 99 in that one.", "99"),
        ("Brunson grabbed 20 rebounds in that one.", "rebounds"),
        ("Brunson dropped 20 against Cleveland.", "Cleveland"),
        ("Brunson didn't score 20 points.", "didn't"),
        ("Brunson averaged 20 points.", "averaged"),
        ("Brunson scored 20 in the first half.", "first half"),
        ("Brunson scored 20 in quarter 2.", "quarter"),
        ("Brunson scored 20 in 2024-25.", "2024-25"),
        ("Brunson scored 20 on January 2.", "January 2"),
        ("Brunson dropped twenty points.", "twenty"),
        ("Brunson shot 20%.", "%"),
        ("Towns and Brunson combined for 20.", "Towns"),
        ("Brunson's 20 points caused the win.", "caused"),
    ],
)
async def test_checked_fact_survives_writer_placement_or_bounded_repair(
    runtime, draft, contradiction
):
    await plan(runtime, [text_call(draft + " [[f1]]"), text_call("[[f1]]")])
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(
            client,
            headers,
            message("How many points did Jalen Brunson score against Boston on January 1, 2026?"),
        )
        persisted = await current(client, headers)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert re.search(r"\b20(?:\.0)? points\b", reply["text"])
    assert "Brunson" in reply["text"] and "2026-01-01" in reply["text"]
    assert settled(updates) == persisted
    assert "".join(value["text"] for kind, value in updates if kind == "delta") == reply["text"]
    requests = (await state(runtime))["requests"]
    if contradiction:
        assert contradiction not in reply["text"]
        assert len(requests) == 2
    else:
        assert len(requests) == 1
    if len(requests) > 1:
        repair_history = requests[-1]["messages"]
        assert any(
            draft in item.get("content", "") and item.get("role") == "system"
            for item in repair_history
        )


@pytest.mark.parametrize("tail", [" [[f1]]", " [[f1]]2", " [[f", " [[f999]]"])
async def test_pending_fact_stays_out_of_stream_checkpoints_and_replay(runtime, tail):
    prefix = "I love the spacing."
    draft = "Brunson dropped 20 in that one."
    first = {
        "steps": [
            {"data": packet(prefix + " " + draft)},
            {"gate": "reference"},
            {"data": packet(tail)},
            {"data": packet(finish="stop")},
            {"data": "[DONE]"},
        ]
    }
    await plan(runtime, [first, text_call("[[f1]]")])
    headers = token()
    command = message("How many points did Jalen Brunson score against Boston on January 1, 2026?")
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        async with client.stream("POST", "/chat/turns", headers=headers, json=command) as response:
            assert response.status_code == 200
            iterator = events(response)
            updates = []
            async with asyncio.timeout(10):
                while not any(kind == "delta" for kind, _ in updates):
                    updates.append(await anext(iterator))
            assert "".join(value["text"] for kind, value in updates if kind == "delta") == prefix
            snapshot = await current(client, headers)
            assert snapshot["exchanges"][0]["reply"]["text"] == prefix
            assert snapshot["exchanges"][0]["reply"]["status"] == "writing"
            assert not (await state(runtime))["gates"]["reference"]
            await release(runtime, "reference")
            updates += [item async for item in iterator]
        persisted = await current(client, headers)
        replay = await turn(client, headers, command)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert reply["text"].startswith(prefix)
    assert re.search(r"\b20(?:\.0)? points\b", reply["text"])
    assert reply["text"].count("2026-01-01") == 1
    assert draft not in reply["text"] and "[[" not in reply["text"]
    assert settled(updates) == persisted == settled(replay)
    assert not any(kind == "delta" for kind, _ in replay)
    assert len((await state(runtime))["requests"]) == (1 if tail == " [[f1]]" else 2)
