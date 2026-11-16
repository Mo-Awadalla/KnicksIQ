from __future__ import annotations

import httpx
from app.tests.support.chat_client import (
    ledger,
    message,
    packet,
    plan,
    runtime,
    settled,
    text_call,
    token,
    turn,
)

__all__ = ["runtime"]


async def test_unclosed_oversized_quote_never_reaches_public_text(runtime):
    unsupported = '"' + "Unverified" * 50 + " invented words attributed to a player."
    await plan(runtime, [text_call(unsupported), text_call("I cannot verify that quote.")])
    async with httpx.AsyncClient(
        base_url=runtime.base_url,
        headers={"X-Forwarded-Proto": "https"},
        timeout=20,
    ) as client:
        updates = await turn(client, token(), message("Give me your take"))
    visible = "".join(data["text"] for kind, data in updates if kind == "delta")
    assert "Unverified" not in visible
    assert "Unverified" not in settled(updates)["exchanges"][0]["reply"]["text"]


async def test_socket_truncation_after_finish_does_not_claim_complete(runtime):
    await plan(
        runtime,
        [
            {
                "steps": [
                    {"data": packet("A real partial sentence.")},
                    {"data": packet(finish="stop")},
                ],
                "truncate": True,
            }
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url,
        headers={"X-Forwarded-Proto": "https"},
        timeout=20,
    ) as client:
        updates = await turn(client, token(), message())
    reply = settled(updates)["exchanges"][0]["reply"]
    assert reply["status"] == "interrupted"
    assert await ledger(runtime) > 0
