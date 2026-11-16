"""Language-boundary regressions through streaming HTTP and persisted replies."""

from __future__ import annotations

import httpx
import pytest
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

__all__ = ["runtime"]

REPLACEMENT = "I cannot verify that claim."


@pytest.mark.parametrize(
    "prose",
    [
        "Let 'em cook. The bench is fun. Hart is a menace.",
        "‘Melo was a bucket.",
        "'Melo was a bucket.",
        "I love this team 'cause they defend.",
        "Let ’em cook ’til the crowd gets loud.",
        "Those '90s Knicks were nasty.",
        "Those 1990s Knicks were nasty.",
        "The 2025-2026 Knicks were fun.",
        "For 2025/26, I like the Knicks' chances.",
        "What if Brunson scored fifty?",
        "What happens if Brunson scores fifty?",
        "If Brunson scored forty, I'd love our chances.",
        "I'd take two wings over one center for this hypothetical roster.",
        "He's a top-five point guard, easy.",
        "Run a two-for-one at the end of the quarter.",
        "That's a fifty-fifty call.",
        "I have twenty concerns about this roster.",
        "A thousand thoughts, but defense comes first.",
        'So I\'m the wrong guy for a "what went down tonight" update.',
        'I cannot answer a "who won tonight" question without live news.',
        'Your "what changed" request needs current reporting.',
    ],
)
async def test_language_prose_streams_unchanged(runtime, prose):
    await plan(runtime, [text_call(prose)])
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message("Give me a Knicks take."))
        persisted = await current(client, headers)
    public_only(updates)
    assert "".join(data["text"] for kind, data in updates if kind == "delta") == prose
    assert settled(updates) == persisted
    assert persisted["exchanges"][0]["reply"]["text"] == prose
    assert persisted["exchanges"][0]["reply"]["status"] == "complete"
    assert len((await state(runtime))["requests"]) == 1


@pytest.mark.parametrize(
    "unsupported",
    [
        "Brunson went for forty on Boston.",
        "Brunson had forty against Boston.",
        "Brunson had forty last night.",
        "The Knicks beat Boston by twelve.",
        "He was putting up thirty a night.",
        "Brunson was averaging thirty a game.",
        "Brunson hung forty on Boston.",
        "Brunson torched Boston for forty.",
        "Brunson drops forty on Boston.",
        "They went fifty and thirty.",
        "Ewing made eleven All-Star teams.",
        "Brunson hit seven triples.",
        "Unless I'm misremembering Brunson scored forty on Boston.",
        "If you recall Brunson scored forty on Boston that night.",
        "If he's healthy — and Brunson scored forty last time — we win.",
        "If he's healthy (Brunson scored forty last time) we win.",
        "I'd take Brunson's forty against Boston over anything.",
        "Imagine forgetting Brunson's forty-point night against Boston.",
        "He shot a hundred percent from the line.",
        "He scored fifty-fifty points.",
        "He scored two-for-one points.",
        "The Knicks scored 90 in the '90s.",
        "The 2025-2026 Knicks scored forty.",
        "Brunson scored forty in 2026.",
        "Brunson said 'em cook.'",
        "Brunson said 'no.'",
        "Brunson said ‘Melo was a bucket.’",
        "Brunson said 'trade me",
        'Brunson said "what went down tonight".',
        '"what went down tonight".',
        'Brunson said the "what went down tonight" update was accurate.',
        'Your "Brunson scored forty" update is accurate.',
        'The "2026 championship" update is accurate.',
    ],
)
async def test_asserted_stats_years_and_quotes_stay_withheld(runtime, unsupported):
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
    assert persisted["exchanges"][0]["reply"]["text"] == REPLACEMENT
    assert persisted["exchanges"][0]["reply"]["status"] == "complete"
    assert len((await state(runtime))["requests"]) == 2


async def test_fragmented_elisions_release_individual_sentences(runtime):
    prose = "Let 'em cook. The bench is fun. Hart is a menace."
    await plan(
        runtime,
        [
            {
                "steps": [
                    *({"data": packet(char)} for char in prose),
                    {"data": packet(finish="stop")},
                    {"data": "[DONE]"},
                ]
            }
        ],
    )
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, token(), message("Give me a Knicks take."))
    deltas = [data["text"] for kind, data in updates if kind == "delta"]
    assert deltas == ["Let 'em cook.", " The bench is fun.", " Hart is a menace."]
    assert settled(updates)["exchanges"][0]["reply"]["status"] == "complete"
    assert len((await state(runtime))["requests"]) == 1
