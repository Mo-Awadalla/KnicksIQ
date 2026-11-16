from __future__ import annotations

import httpx
import pytest
from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

__all__ = ["runtime"]


@pytest.mark.parametrize(
    ("draft", "metric", "expected_calls"),
    [
        ("Karl-Anthony Towns had 16 points.", "points", 1),
        ("Towns had 16 points.", "average points", 1),
        ("Towns had -5 plus minus.", "plus minus", 1),
        ("Karl-Anthony Towns had -5 plus minus.", "plus minus", 1),
        ("Towns had −5 plus minus.", "plus minus", 1),
        ("Towns had +5 plus minus.", "plus minus", 2),
        ("Towns had --5 plus minus.", "plus minus", 2),
        ("Towns had .5 plus minus.", "plus minus", 2),
        ("player0 had -5 plus minus.", "plus minus", 2),
        ("Towns had -5 plus minus against team999.", "plus minus", 2),
    ],
)
async def test_source_names_and_signed_values_preserve_checked_meaning(
    runtime, draft, metric, expected_calls
):
    if metric == "plus minus":
        engine = create_async_engine(runtime.url)
        try:
            async with async_sessionmaker(engine)() as session, session.begin():
                row = (
                    await session.execute(
                        select(PlayerGameStat)
                        .join(Player)
                        .join(Game, Game.id == PlayerGameStat.game_id)
                        .where(
                            Player.full_name == "Karl-Anthony Towns",
                            Game.nba_game_id == "analytics-1",
                        )
                    )
                ).scalar_one()
                row.plus_minus = -5
        finally:
            await engine.dispose()
    repair = "[[f1]]" if expected_calls == 2 else draft + " [[f1]]"
    await plan(runtime, [text_call(draft + " [[f1]]"), text_call(repair)])
    headers = token()
    question = f"How many {metric} did Karl-Anthony Towns have against Boston on January 1, 2026?"
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message(question))
        persisted = await current(client, headers)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert "Karl-Anthony Towns" in reply["text"] and "2026-01-01" in reply["text"]
    assert ("-5 plus minus" if metric == "plus minus" else "16 points") in reply["text"]
    assert "[[" not in reply["text"] and "had" not in reply["text"]
    assert settled(updates) == persisted
    assert "".join(value["text"] for kind, value in updates if kind == "delta") == reply["text"]
    assert len((await state(runtime))["requests"]) == expected_calls
