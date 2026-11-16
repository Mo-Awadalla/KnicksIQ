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
    ("draft", "allowed"),
    [
        ('But "contender" and "favorite" are different zip codes.', True),
        ('"Good" and "elite" are not the same thing.', True),
        ('"Contender" is not "favorite".', True),
        ('Brunson said "contender" and "favorite" are different zip codes.', False),
        ('His "contender" and "favorite" are different zip codes.', False),
        ('Brunson\'s "contender" and "favorite" are different zip codes.', False),
        (
            'These are Brunson’s exact words. "Trade me" and "I hate New York" '
            "are different messages.",
            False,
        ),
        (
            'Brunson said this. "Trade me" and "I hate New York" are different messages.',
            False,
        ),
        (
            'Brunson’s words? "Trade me" and "I hate New York" are different messages.',
            False,
        ),
        ('The phrase "Trade me" came from Brunson.', False),
        ('Brunson explained the phrase "Trade me".', False),
        ('Your "Make it fun" request is exactly what I heard.', True),
        ('"Brunson scored forty" and "favorite" are different labels.', False),
    ],
)
async def test_label_comparisons_are_not_reported_quotations(runtime, draft, allowed):
    replacement = "I cannot confirm those words."
    await plan(runtime, [text_call(draft), text_call(replacement)])
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message("Are we actually contenders?"))
        persisted = await current(client, headers)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert reply["text"] == (draft if allowed else replacement)
    assert settled(updates) == persisted
    assert "".join(value["text"] for kind, value in updates if kind == "delta") == reply["text"]
    assert len((await state(runtime))["requests"]) == (1 if allowed else 2)
