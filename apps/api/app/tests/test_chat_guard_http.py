"""Quoted statements are synthetic test fixtures, not actual player quotations."""

from __future__ import annotations

import json

import httpx
import pytest
from app.models.game import Game
from app.models.report import Report
from app.tests.support.chat_client import (
    current,
    message,
    packet,
    plan,
    public_only,
    runtime,
    settled,
    state,
    text_call,
    token,
    turn,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

__all__ = ["runtime"]

REPLACEMENT = "I cannot verify that claim."


@pytest.mark.parametrize(
    "unsupported",
    [
        "Brunson scored zero points.",
        "Towns grabbed one rebound.",
        "Brunson dropped forty on Boston.",
        "Towns put up twenty and twelve in that one.",
        "Back in nineteen seventy-three the Knicks were champs.",
        "Hart grabbed a dozen in the fourth quarter alone.",
        "Brunson scored forty-two.",
        "Brunson scored 999 points.",
        "In my opinion, Brunson dropped forty on Boston.",
        "If you ask me, Brunson scored forty.",
        "Brunson told reporters, ‘We are winning the whole thing this year.’",
        "Thibs said, 'We need way more effort from everybody tonight.'",
        "Brunson said 'I demand a trade immediately'.",
        'Brunson said "trade me".',
        "Brunson said “no”.",
        "'Trade me,' Brunson said.",
        "Brunson’s 'trade me' comment was blunt.",
        "Brunson said 'trade me",
        'If he is "the guy," he scored forty.',
        'If your bar is "top-five player," Brunson scored forty.',
        'His answer was "old news".',
        '"No."',
        'Thibs answered with "more effort".',
        'Brunson wants "more effort" from everybody.',
        'Your "Brunson scored forty" claim is true.',
        'The term "trade me" is what Brunson told reporters.',
        "I have two concerns: Brunson scored forty and Towns grabbed twelve.",
        'His "trade me" argument was blunt.',
        "I have two championship rings.",
        "There were two concerns in the official report.",
        "Brunson had forty.",
        "His points total was forty.",
        "He shot seven-for-eleven.",
        "Brunson netted ninety against Boston.",
    ],
)
async def test_unsupported_assertion_is_withheld_and_continued(runtime, unsupported):
    await plan(runtime, [text_call(unsupported), text_call(REPLACEMENT)])
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message("Give me a Knicks take."))
        persisted = await current(client, headers)
    public_only(updates)
    assert "".join(data["text"] for kind, data in updates if kind == "delta") == REPLACEMENT
    assert settled(updates) == persisted
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert reply["text"] == REPLACEMENT
    requests = (await state(runtime))["requests"]
    assert len(requests) == 2
    repair = json.loads(requests[1]["messages"][-1]["content"].splitlines()[-1])
    assert repair["unpublished_draft"] == unsupported


@pytest.mark.parametrize(
    "prose",
    [
        "Brunson's handle isn't fair, and Towns’ spacing makes it nastier.",
        "A good wing and an honest center make the offense easier.",
        "Give me two-way wings, one-on-one creation, and three-and-D support.",
        "One thing I love is Hart's motor.",
        "He's one of my favorite players to watch.",
        "On the one hand, I love the spacing; on the other, defense matters.",
        "That 'clutch' label is an opinion, not a stat.",
        "Call it “three-and-D” basketball, not magic.",
        "If Brunson scored forty, I'd love our chances.",
        "I'd take two wings over one center for this hypothetical roster.",
        "For 2025-26, I like the Knicks' chances.",
        "1. Trust the defense.\n2. Let Brunson cook.",
        'So if your bar is "top-five guy who does everything," yeah, he is not that.',
        'Those are legit knocks, and if your bar for "credit" is two-way superstar, '
        "he does not clear it.",
        'Your "credit" standard is pretty harsh.',
        'The "clutch" argument leaves out defense.',
        'Even if your definition of "star" is narrow, he fits it.',
        "Here is one for you. Which Knicks guard would you trust late?",
        "I have two concerns: spacing and defense.",
        "Give me three reasons you trust this roster.",
        'Their "two-way" label is generous.',
        "My gripe is the same one I've had all year: keep the offense organized.",
        "I had one concern all season: defense.",
    ],
)
async def test_conversational_prose_keeps_its_original_stream_and_completion(runtime, prose):
    await plan(runtime, [text_call(prose)])
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message("Give me a Knicks take."))
        persisted = await current(client, headers)
    assert "".join(data["text"] for kind, data in updates if kind == "delta") == prose
    assert settled(updates) == persisted
    reply = persisted["exchanges"][0]["reply"]
    assert reply["text"] == prose and reply["status"] == "complete"
    assert len((await state(runtime))["requests"]) == 1


@pytest.mark.parametrize("quote", ["'No. Trade me.'", "‘No. Trade me.’", '"No. Trade me."'])
async def test_fragmented_quotation_never_releases_an_inner_sentence(runtime, quote):
    unsafe = f"Brunson said {quote}"
    await plan(
        runtime,
        [
            {
                "steps": [
                    *({"data": packet(char)} for char in unsafe),
                    {"data": packet(finish="stop")},
                    {"data": "[DONE]"},
                ]
            },
            text_call(REPLACEMENT),
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, token(), message("Give me a Knicks take."))
    assert "".join(data["text"] for kind, data in updates if kind == "delta") == REPLACEMENT
    assert settled(updates)["exchanges"][0]["reply"]["text"] == REPLACEMENT
    assert len((await state(runtime))["requests"]) == 2


async def test_second_violation_preserves_only_safe_prefix_and_stays_interrupted(runtime):
    prefix = "I love the spacing."
    await plan(
        runtime,
        [text_call(prefix + " Brunson dropped forty."), text_call("Towns grabbed one rebound.")],
    )
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message("Give me a Knicks take."))
        persisted = await current(client, headers)
    assert "".join(data["text"] for kind, data in updates if kind == "delta") == prefix
    assert settled(updates) == persisted
    reply = persisted["exchanges"][0]["reply"]
    assert reply["text"] == prefix
    assert reply["status"] == "interrupted" and reply["reason"] == "incomplete"
    assert len((await state(runtime))["requests"]) == 2


@pytest.mark.parametrize("kind", ["stat", "quote"])
async def test_checked_reference_expands_to_unchanged_canonical_fact(runtime, kind):
    if kind == "stat":
        question = "How many points did Jalen Brunson score against Boston on January 1, 2026?"
    else:
        question = "Show the report for Boston on January 1, 2026."
        engine = create_async_engine(runtime.url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                game = (
                    await session.execute(select(Game).where(Game.nba_game_id == "analytics-1"))
                ).scalar_one()
                session.add(
                    Report(
                        game_id=game.id,
                        release_id=game.release_id,
                        reviewed=True,
                        title=question,
                        summary='Brunson said "trade me".',
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
    lookup = {
        "index": 0,
        "id": "checked_fact",
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
            text_call("[[f1]]"),
        ],
    )
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message(question))
        persisted = await current(client, headers)
    public_only(updates)
    requests = (await state(runtime))["requests"]
    assert len(requests) == 2
    found = [
        json.loads(item["content"]) for item in requests[1]["messages"] if item["role"] == "tool"
    ]
    assert found[0]["status"] == "found"
    canonical = found[0]["facts"][0]["text"]
    assert ("20" if kind == "stat" else 'Brunson said "trade me".') in canonical
    assert "2026-01-01" in canonical
    assert "".join(data["text"] for name, data in updates if name == "delta") == canonical
    assert settled(updates) == persisted
    reply = persisted["exchanges"][0]["reply"]
    assert reply["text"] == canonical and reply["status"] == "complete"
