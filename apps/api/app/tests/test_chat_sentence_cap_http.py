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


@pytest.mark.parametrize("lead", [396, 397, 398])
@pytest.mark.parametrize("spaced", [True, False])
async def test_decimal_near_sentence_cap_does_not_stall_the_api(runtime, lead, spaced):
    prefix = ("Brunson was " + "so " * 200)[:lead] if spaced else "x" * lead
    draft = prefix + "23.5 points and that was wild."
    await plan(runtime, [text_call(draft), text_call("He was cooking.")])
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=10
    ) as client:
        updates = await turn(client, headers, message("Were we contenders?"))
        persisted = await current(client, headers)
        health = await client.get("/health/live")
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert health.status_code == 200
    assert reply["status"] == "complete" and reply["text"].endswith("He was cooking.")
    assert "23.5" not in reply["text"]
    assert "".join(value["text"] for kind, value in updates if kind == "delta") == reply["text"]
    assert settled(updates) == persisted
    assert len((await state(runtime))["requests"]) == 2
