"""Play descriptions below are synthetic fixtures, not historical NBA records."""

from __future__ import annotations

import re

import httpx
import pytest
from app.models.game import Game
from app.models.game_event import GameEvent
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


@pytest.mark.parametrize("named_player", [False, True])
async def test_one_checked_reference_describes_one_play_without_source_boilerplate(
    runtime, named_player
):
    engine = create_async_engine(runtime.url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            game = (
                await session.execute(select(Game).where(Game.nba_game_id == "analytics-1"))
            ).scalar_one()
            brunson = (
                await session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
            ).scalar_one()
            session.add_all(
                [
                    GameEvent(
                        game_id=game.id,
                        sequence=1,
                        period=1,
                        clock="12:00",
                        event_type="jump_ball",
                        description="Jump ball: tip to Boston.",
                        team_id="BOS",
                    ),
                    GameEvent(
                        game_id=game.id,
                        sequence=2,
                        period=1,
                        clock="11:45",
                        event_type="made_shot",
                        description="Boston 2PT jump shot.",
                        team_id="BOS",
                        home_score=0,
                        away_score=2,
                    ),
                    GameEvent(
                        game_id=game.id,
                        sequence=3,
                        period=1,
                        clock="11:20",
                        event_type="made_shot",
                        description="Brunson 3PT jump shot (Towns assist).",
                        team_id="NYK",
                        player_id=brunson.id,
                        home_score=3,
                        away_score=2,
                        shot_type="3pt",
                        shot_result="made",
                    ),
                ]
            )
    finally:
        await engine.dispose()
    await plan(runtime, [text_call("Here's one. [[f1]]"), text_call("[[f1]]")])
    subject = "Jalen Brunson " if named_player else ""
    question = f"Show me one {subject}play from the play-by-play against Boston on January 1, 2026."
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(client, headers, message(question))
        persisted = await current(client, headers)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert len(re.findall(r"\bQ\d+ \d{1,2}:\d{2}", reply["text"])) == 1
    assert "From the " not in reply["text"] and "recorded events" not in reply["text"]
    assert "[[" not in reply["text"] and "BOS 0, NYK 0" not in reply["text"]
    if named_player:
        assert "Brunson 3PT" in reply["text"] and "Towns assist" in reply["text"]
        assert "Jump ball" not in reply["text"] and "Boston 2PT" not in reply["text"]
    assert settled(updates) == persisted
    assert "".join(value["text"] for kind, value in updates if kind == "delta") == reply["text"]
    assert len((await state(runtime))["requests"]) == 1
