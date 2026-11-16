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
    plan,
    public_only,
    runtime,
    settled,
    text_call,
    token,
    turn,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

__all__ = ["runtime"]


@pytest.mark.parametrize("scores", [(105, 97, 106), (2, 0, 4)])
async def test_missing_event_scores_never_carry_into_a_checked_play(runtime, scores):
    home, away, later_home = scores
    engine = create_async_engine(runtime.url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            game = (
                await session.execute(select(Game).where(Game.nba_game_id == "analytics-1"))
            ).scalar_one()
            player = (
                await session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
            ).scalar_one()
            await session.execute(delete(GameEvent).where(GameEvent.game_id == game.id))
            rows = [
                (1, "06:40", "missed_shot", "Brunson missed an early jumper", 0, 0),
                (2, "06:28", "made_shot", "Brunson made a pullup jumper", home, away),
                (3, "05:15", "missed_shot", "Brunson missed a stepback jumper", 0, 0),
                (4, "04:40", "free_throw", "Brunson made the free throw", later_home, away),
            ]
            session.add_all(
                GameEvent(
                    game_id=game.id,
                    sequence=sequence,
                    period=4,
                    clock=clock,
                    event_type=kind,
                    description=description,
                    team_id="NYK",
                    player_id=player.id,
                    home_score=home_score,
                    away_score=away_score,
                )
                for sequence, clock, kind, description, home_score, away_score in rows
            )
            await session.commit()
    finally:
        await engine.dispose()
    await plan(runtime, [text_call("[[f1]]")])
    headers = token()
    question = "What happened at 05:15 in Q4 against Boston on January 1, 2026?"
    async with httpx.AsyncClient(
        base_url=runtime.base_url, headers={"X-Forwarded-Proto": "https"}, timeout=20
    ) as client:
        updates = await turn(
            client,
            headers,
            message(question),
        )
        persisted = await current(client, headers)
    public_only(updates)
    reply = persisted["exchanges"][0]["reply"]
    assert reply["status"] == "complete"
    assert settled(updates) == persisted
    assert "".join(data["text"] for kind, data in updates if kind == "delta") == reply["text"]
    assert "Q4 05:15: Brunson missed a stepback jumper." in reply["text"]
    assert "2026-01-01" in reply["text"]
    assert "Q4 06:40" not in reply["text"] and "Q4 04:40" not in reply["text"]
    assert not any(team in reply["text"] for team in ("(BOS 0,", "(NYK 0,"))
    print(json.dumps({"source_scores": scores, "public_reply": reply["text"]}))
