from __future__ import annotations

import json

import httpx
import pytest
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

__all__ = ["runtime"]


async def event_turn(runtime, rows, question, model_reply="[[f1]]", prefetch=False):
    engine = create_async_engine(runtime.url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            game = (
                await session.execute(select(Game).where(Game.nba_game_id == "analytics-1"))
            ).scalar_one()
            brunson = (
                await session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
            ).scalar_one()
            await session.execute(delete(GameEvent).where(GameEvent.game_id == game.id))
            session.add_all(
                GameEvent(
                    game_id=game.id,
                    sequence=index,
                    period=period,
                    clock=clock,
                    event_type="made_shot",
                    description=description,
                    team_id="NYK",
                    player_id=brunson.id,
                    home_score=home,
                    away_score=away,
                )
                for index, (period, clock, description, home, away) in enumerate(rows, start=1)
            )
            await session.commit()
    finally:
        await engine.dispose()
    lookup = {
        "index": 0,
        "id": "event-window",
        "type": "function",
        "function": {"name": "lookup", "arguments": json.dumps({"question": question})},
    }
    if prefetch:
        await plan(runtime, [text_call(model_reply)])
    else:
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
                text_call(model_reply),
            ],
        )
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(
            client,
            headers,
            message(question if prefetch else "Tell me something good."),
        )
        snapshot = await current(client, headers)
    public_only(updates)
    assert settled(updates) == snapshot
    assert (
        "".join(value["text"] for kind, value in updates if kind == "delta")
        == snapshot["exchanges"][0]["reply"]["text"]
    )
    requests = (await state(runtime))["requests"]
    if prefetch:
        note = next(
            item["content"]
            for item in requests[0]["messages"]
            if item["role"] == "system"
            and item["content"].startswith("Checked facts for this message")
        )
        facts = {"status": "found", "facts": [], "message": note}
    else:
        facts = [
            json.loads(item["content"])
            for item in requests[1]["messages"]
            if item["role"] == "tool"
        ][0]
    return facts, snapshot["exchanges"][0]["reply"]


async def test_prefetch_discloses_truncated_event_window_to_writer(runtime):
    rows = [
        (4, "01:50", "Early quarter shot.", 100, 98),
        (4, "01:20", "Late window shot one.", 104, 102),
        (4, "00:55", "Late window shot two.", 106, 104),
        (4, "00:30", "Late window shot three.", 108, 106),
        (4, "00:04", "Game sealing shot.", 110, 106),
    ]
    facts, reply = await event_turn(
        runtime,
        rows,
        "What happened in the final two minutes of the fourth quarter "
        "against Boston on January 1, 2026?",
        model_reply="[[f1]] [[f2]] [[f3]]",
        prefetch=True,
    )
    assert reply["status"] == "complete"
    assert "Only the final 3 complete plays are checked" in facts["message"]


@pytest.mark.parametrize("term", ["last minute", "final minute"])
async def test_unqualified_final_minute_means_the_last_sixty_seconds(runtime, term):
    facts, reply = await event_turn(
        runtime,
        [
            (4, "11:40", "Brunson early layup.", 90, 88),
            (4, "00:45", "Brunson late floater.", 106, 108),
            (4, "00:10", "Brunson closing jumper.", 108, 110),
        ],
        f"What happened in the {term} of the fourth quarter against Boston on January 1, 2026?",
    )
    texts = " ".join(fact["text"] for fact in facts["facts"])
    assert facts["status"] == "found" and reply["status"] == "complete"
    assert "Q4 00:45" in texts and "Q4 00:10" in texts
    assert "Q4 11:40" not in texts


async def test_final_window_uses_end_rows_and_discloses_the_fact_limit(runtime):
    rows = [
        (4, "01:50", "Early quarter shot.", 100, 98),
        (4, "01:20", "Late window shot one.", 104, 102),
        (4, "00:55", "Late window shot two.", 106, 104),
        (4, "00:30", "Late window shot three.", 108, 106),
        (4, "00:04", "Game sealing shot.", 110, 106),
    ]
    facts, reply = await event_turn(
        runtime,
        rows,
        "What happened in the final two minutes of the fourth quarter "
        "against Boston on January 1, 2026?",
    )
    texts = " ".join(fact["text"] for fact in facts["facts"])
    assert facts["status"] == "found" and reply["status"] == "complete"
    assert "Q4 00:04" in texts and "Q4 00:30" in texts and "Q4 00:55" in texts
    assert "Q4 01:50" not in texts
    assert "only the final 3" in facts["message"].lower()


async def test_second_half_opening_stays_in_q3(runtime):
    facts, reply = await event_turn(
        runtime,
        [
            (3, "11:30", "Third-quarter opener.", 60, 58),
            (4, "11:30", "Fourth-quarter opener.", 90, 88),
        ],
        "What happened in the first two minutes of the second half "
        "against Boston on January 1, 2026?",
    )
    text = " ".join(fact["text"] for fact in facts["facts"])
    assert facts["status"] == "found" and reply["status"] == "complete"
    assert "Q3 11:30" in text and "Fourth-quarter opener" not in text


async def test_regulation_interval_stops_before_overtime(runtime):
    facts, reply = await event_turn(
        runtime,
        [
            (4, "01:10", "Regulation tying jumper.", 100, 100),
            (5, "01:10", "Overtime jumper.", 106, 110),
        ],
        "What happened in the last two minutes of regulation against Boston on January 1, 2026?",
    )
    text = " ".join(fact["text"] for fact in facts["facts"])
    assert facts["status"] == "found" and reply["status"] == "complete"
    assert "Regulation tying jumper" in text and "Overtime jumper" not in text


async def test_overtime_periods_use_ot_labels(runtime):
    facts, reply = await event_turn(
        runtime,
        [
            (5, "01:10", "First overtime jumper.", 106, 110),
            (6, "01:10", "Second overtime jumper.", 116, 120),
        ],
        "Show me play-by-play from overtime against Boston on January 1, 2026.",
    )
    text = " ".join(fact["text"] for fact in facts["facts"])
    assert facts["status"] == "found" and reply["status"] == "complete"
    assert "OT 01:10" in text and "2OT 01:10" in text
    assert "Q5" not in text and "Q6" not in text


async def test_long_atomic_event_returns_a_limit_instead_of_not_found(runtime):
    long = "Brunson " + "long checked play description " * 12 + "made layup."
    facts, reply = await event_turn(
        runtime,
        [(4, "00:30", long, 113, 109)],
        "What happened at 00:30 in Q4 against Boston on January 1, 2026?",
        model_reply="I cannot verify that complete play from the available record.",
    )
    assert facts["status"] == "limit"
    assert "facts" not in facts
    assert reply["status"] == "complete"
    assert "too long to include" in facts["message"].lower()
