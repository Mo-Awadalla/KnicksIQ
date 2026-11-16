from __future__ import annotations

import httpx
import pytest
from app.tests.support.chat_client import (
    current,
    message,
    plan,
    public_only,
    runtime,
    settled,
    state,
    text_call,
    token,
    turn,
)

__all__ = ["runtime"]


@pytest.mark.parametrize(
    "draft", ["[[f1]] [[f1]]", "[[f1]] ", "[[f1]]\n", "I love the spacing. [[f1]]\n"]
)
async def test_settlement_and_replay_preserve_every_emitted_character(runtime, draft):
    await plan(runtime, [text_call(draft)])
    headers = token()
    command = message("How many points did Jalen Brunson score against Boston on January 1, 2026?")
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, command)
        persisted = await current(client, headers)
        replay = await turn(client, headers, command)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert reply["text"].count("2026-01-01") == 1
    assert "Brunson" in reply["text"] and "points" in reply["text"]
    assert "[[" not in reply["text"]
    assert "".join(value["text"] for kind, value in updates if kind == "delta") == reply["text"]
    assert settled(updates) == persisted == settled(replay)
    assert not any(kind == "delta" for kind, _ in replay)
    assert len((await state(runtime))["requests"]) == 1
