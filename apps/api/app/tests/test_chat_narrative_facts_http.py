from __future__ import annotations

import json

import httpx
from app.tests.support.chat_client import (
    current,
    message,
    packet,
    plan,
    public_only,
    runtime,
    settled,
    state,
    token,
    turn,
)

__all__ = ["runtime"]


async def test_best_defensive_game_keeps_its_numeric_claim_when_receipts_are_projected(runtime):
    question = "What was the Knicks' best defensive game in the 2025-26 season?"
    lookup = {
        "index": 0,
        "id": "best-defensive-game",
        "type": "function",
        "function": {"name": "lookup", "arguments": json.dumps({"question": question})},
    }
    await plan(
        runtime,
        [
            {
                "steps": [
                    {"data": packet(tool_calls=[lookup])},
                    {"data": packet(finish="tool_calls")},
                    {"data": "[DONE]"},
                ]
            },
            {"steps": [{"lookup_refs": True}, {"data": packet(finish="stop")}, {"data": "[DONE]"}]},
        ],
    )
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message(question))
        snapshot = await current(client, headers)
    public_only(updates)
    reply = snapshot["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert "points allowed" in reply["text"]
    assert settled(updates) == snapshot
    assert "".join(value["text"] for kind, value in updates if kind == "delta") == reply["text"]
    requests = (await state(runtime))["requests"]
    assert len(requests) == 2
    tool_results = [
        json.loads(item["content"])
        for item in requests[1]["messages"]
        if item.get("role") == "tool"
    ]
    numeric = [
        fact["text"]
        for result in tool_results
        for fact in result.get("facts", [])
        if "points allowed" in fact["text"]
    ]
    assert numeric and all(statement in reply["text"] for statement in numeric)
