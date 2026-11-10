"""First-name identity and ambiguity at the public analyst boundary."""

import pytest
from app.core.db import AsyncSessionLocal
from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from app.tests.support.analytics_workflows import ask, claims, comparison_archive


async def test_unique_first_name_keeps_player_average_not_team_score(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(client, "How many points did Mikal average against Toronto?", version)
    claim = claims(body)["points:average"]
    assert claim["value"] == 10
    assert claim["sample_size"] == 1
    assert claim["game_ids"] == [ids["2025-11-10"]]
    assert claim["release_id"] == version
    assert "Mikal Bridges" in body["answer"]


@pytest.mark.parametrize("other_team", ["NYK", "BOS"])
async def test_shared_first_name_clarifies_without_selecting_player(
    client, monkeypatch, other_team
):
    version, ids = await comparison_archive(monkeypatch)
    async with AsyncSessionLocal() as db:
        players = [
            Player(nba_player_id=999_101, full_name="Alex One", team_id="NYK"),
            Player(nba_player_id=999_102, full_name="Alex Two", team_id=other_team),
        ]
        db.add_all(players)
        await db.flush()
        game = await db.get(Game, ids["2025-11-01"])
        assert game is not None
        db.add_all(
            [
                PlayerGameStat(
                    release_id=game.release_id,
                    game_id=game.id,
                    player_id=player.id,
                    team_id=team,
                    minutes=30,
                    points=10,
                )
                for player, team in zip(players, ("NYK", other_team), strict=True)
            ]
        )
        await db.commit()
    body = await ask(client, "How many points did Alex score?", version)
    assert body["outcome"] == "clarify"
    assert not claims(body)
    assert "Alex One" in body["answer"] and "Alex Two" in body["answer"]


async def test_broad_player_performance_keeps_opponent_population(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(client, "Did Mikal play well against Toronto?", version)
    claim = claims(body)["points:average"]
    assert claim["value"] == 10
    assert claim["sample_size"] == 1
    assert claim["game_ids"] == [ids["2025-11-10"]]
    assert claim["release_id"] == version
