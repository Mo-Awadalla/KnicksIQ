from __future__ import annotations

import re
from datetime import date

import httpx
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


async def test_one_observed_appearance_does_not_make_the_considered_scope_one_game(runtime):
    engine = create_async_engine(runtime.url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        select(PlayerGameStat)
                        .join(Player)
                        .join(Game, Game.id == PlayerGameStat.game_id)
                        .where(
                            Player.full_name == "Karl-Anthony Towns",
                            Game.game_date >= date(2026, 1, 1),
                            Game.game_date <= date(2026, 1, 3),
                            (Game.home_team_id == "BOS") | (Game.away_team_id == "BOS"),
                        )
                        .order_by(Game.game_date)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 3
            for row in rows[1:]:
                row.minutes = 0
    finally:
        await engine.dispose()
    await plan(runtime, [text_call("Towns had 16 points in that one. [[f1]]"), text_call("[[f1]]")])
    headers = token()
    question = "What was Karl-Anthony Towns's average points against Boston in January 2026?"
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message(question))
        persisted = await current(client, headers)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert re.search(r"\b16(?:\.0)? points\b", reply["text"])
    assert "per appearance" in reply["text"]
    assert "2026-01-01" in reply["text"]
    assert "in that one" not in reply["text"]
    assert settled(updates) == persisted
    assert len((await state(runtime))["requests"]) == 2
