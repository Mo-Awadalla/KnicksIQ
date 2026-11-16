"""Population identity survives lookup, reference expansion, and persisted HTTP reads."""

from __future__ import annotations

import json
import os
import re
from datetime import date

import httpx
import pytest
from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
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


@pytest.fixture(autouse=True)
def postgres_fixture(monkeypatch):
    url = os.environ.get("READINESS_TEST_DATABASE_URL")
    if not url:
        pytest.fail("READINESS_TEST_DATABASE_URL is required for population HTTP tests")
    monkeypatch.setenv("CHAT_E2E_DATABASE_URL", url)


def lookup(question, index):
    return {
        "steps": [
            {
                "data": packet(
                    tool_calls=[
                        {
                            "index": 0,
                            "id": f"population_{index}",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": json.dumps({"question": question}),
                            },
                        }
                    ]
                )
            },
            {"data": packet(finish="tool_calls")},
            {"data": "[DONE]"},
        ]
    }


async def seed_populations(runtime):
    engine = create_async_engine(runtime.url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            original = (
                await session.execute(select(Game).where(Game.nba_game_id == "analytics-1"))
            ).scalar_one()
            player = (
                await session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
            ).scalar_one()
            for day, opponent, phase, points in [
                (4, "BKN", "regular", 20),
                (5, "BKN", "regular", 30),
                (6, "BOS", "regular", 20),
                (7, "BOS", "regular", 30),
                (8, "BKN", "playoffs", 20),
                (9, "BKN", "playoffs", 30),
            ]:
                game = Game(
                    release_id=original.release_id,
                    nba_game_id=f"population-{day}",
                    season="2025-26",
                    game_date=date(2026, 1, day),
                    home_team_id="NYK",
                    away_team_id=opponent,
                    home_score=110,
                    away_score=100,
                    status="final",
                    season_type=phase,
                    source_name="test",
                    source_game_id=f"population-{day}",
                )
                session.add(game)
                await session.flush()
                session.add(
                    PlayerGameStat(
                        release_id=original.release_id,
                        game_id=game.id,
                        player_id=player.id,
                        team_id="NYK",
                        minutes=34,
                        points=points,
                        field_goals_attempted=10,
                    )
                )
            session.add(
                Report(
                    game_id=original.id,
                    release_id=original.release_id,
                    reviewed=True,
                    title="Show the report for Boston on January 1, 2026.",
                    summary="Jalen Brunson and the Knicks kept the ball moving against Boston.",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("slice_kind", ["opponent", "window", "phase"])
async def test_equal_totals_keep_distinct_populations_through_http(runtime, slice_kind):
    await seed_populations(runtime)
    questions = {
        "opponent": [
            "How many total points did Jalen Brunson score against Boston "
            "from January 1 to January 3, 2026?",
            "How many total points did Jalen Brunson score against Brooklyn "
            "from January 4 to January 5, 2026?",
        ],
        "window": [
            "How many total points did Jalen Brunson score against Boston "
            "from January 1 to January 3, 2026?",
            "How many total points did Jalen Brunson score against Boston "
            "from January 6 to January 7, 2026?",
        ],
        "phase": [
            "How many total points did Jalen Brunson score against Brooklyn in the regular season?",
            "How many total points did Jalen Brunson score against Brooklyn in the playoffs?",
        ],
    }[slice_kind]
    await plan(
        runtime, [lookup(q, i) for i, q in enumerate(questions)] + [text_call("[[f1]] [[f2]]")]
    )
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url,
        headers={"X-Forwarded-Proto": "https"},
        timeout=30,
    ) as client:
        updates = await turn(client, headers, message("Compare those Brunson slices."))
        persisted = await current(client, headers)
    requests = (await state(runtime))["requests"]
    found = [
        json.loads(item["content"]) for item in requests[-1]["messages"] if item["role"] == "tool"
    ]
    assert len(found) == 2, found
    assert all(item["status"] == "found" for item in found), found
    first, second = [item["facts"][0] for item in found]
    assert all(re.search(r"\b50(?:\.0+)? points\b", item["text"]) for item in (first, second))
    assert first["ref"] != second["ref"], found
    assert first["text"] != second["text"], found
    assert all(
        re.search(r"\b2 (?:recorded )?(?:games|appearances)\b", item["text"])
        for item in (first, second)
    )
    assert all("all season phases" not in item["text"] for item in (first, second))
    if slice_kind == "opponent":
        assert "BOS" in first["text"] and "BKN" in second["text"]
    if slice_kind == "window":
        assert "2026-01-01" in first["text"] and "2026-01-03" in first["text"]
        assert "2026-01-06" in second["text"] and "2026-01-07" in second["text"]
    if slice_kind == "phase":
        assert "regular" in first["text"] and "playoffs" in second["text"]
    canonical = f"{first['text']} {second['text']}"
    public_only(updates)
    assert "".join(data["text"] for kind, data in updates if kind == "delta") == canonical
    assert settled(updates) == persisted
    assert persisted["exchanges"][0]["reply"]["text"] == canonical
    assert persisted["exchanges"][0]["reply"]["status"] == "complete"
    print(json.dumps({"case": slice_kind, "facts": [first, second], "reply": canonical}))


async def test_single_game_date_binding_and_requested_report_survive(runtime):
    await seed_populations(runtime)
    questions = [
        "How many points did Jalen Brunson score against Boston on January 1, 2026?",
        "Show the report for Boston on January 1, 2026.",
    ]
    await plan(
        runtime, [lookup(q, i) for i, q in enumerate(questions)] + [text_call("[[f1]] [[f2]]")]
    )
    headers = token()
    async with httpx.AsyncClient(
        base_url=runtime.base_url,
        headers={"X-Forwarded-Proto": "https"},
        timeout=30,
    ) as client:
        updates = await turn(client, headers, message("Tell me about Brunson and Boston."))
        persisted = await current(client, headers)
    requests = (await state(runtime))["requests"]
    found = [
        json.loads(item["content"]) for item in requests[-1]["messages"] if item["role"] == "tool"
    ]
    assert all(item.get("status") == "found" for item in found), found
    stat, report = [item["facts"][0] for item in found]
    assert re.search(r"\b20(?:\.0+)? points\b", stat["text"]) and "2026-01-01" in stat["text"]
    assert "all season phases" not in stat["text"]
    assert "BOS at NYK" in stat["text"]
    assert "Jalen Brunson and the Knicks kept the ball moving against Boston." in report["text"]
    assert "2026-01-01" in report["text"]
    assert settled(updates) == persisted
    assert persisted["exchanges"][0]["reply"]["text"] == f"{stat['text']} {report['text']}"
    print(json.dumps({"case": "single_game_report", "facts": [stat, report]}))
