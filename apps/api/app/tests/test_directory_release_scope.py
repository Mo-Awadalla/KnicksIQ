"""Public player and team directories are active validated release membership views.

A reader must never see an entity that exists only in a staged, unvalidated, or
superseded release, and an entity outside the active release must 404 rather than
serialize an absent row.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from app.core.db import AsyncSessionLocal
from app.models.box_score import PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.models.team import Team
from app.services import releases
from sqlalchemy import select, update


def _enforce(monkeypatch) -> None:
    """Read the same release boundary a development or production server uses."""
    monkeypatch.setattr(
        releases,
        "get_settings",
        lambda: SimpleNamespace(
            is_production=False,
            test_mode=False,
            require_active_release=True,
        ),
    )


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


async def _add_release(db, *, version: str, status: str, passed: bool = True) -> DatasetRelease:
    release = DatasetRelease(
        version=version,
        season="2025-26",
        source="release-scope-test",
        manifest_sha256=_digest(version),
        validation_passed=passed,
        status=status,
    )
    db.add(release)
    await db.flush()
    return release


async def _seeded_player_id(db, full_name: str) -> int:
    return (await db.execute(select(Player.id).where(Player.full_name == full_name))).scalar_one()


async def _build_releases(db) -> SimpleNamespace:
    """Two releases: one active and validated, one staged with its own entities."""
    active = await _add_release(db, version="scope-active", status="active")
    staged = await _add_release(db, version="scope-staged", status="staged")
    unvalidated = await _add_release(db, version="scope-unvalidated", status="active", passed=False)

    games = (await db.execute(select(Game).order_by(Game.id))).scalars().all()
    await db.execute(update(Game).where(Game.id == games[0].id).values(release_id=active.id))
    await db.execute(update(Game).where(Game.id == games[1].id).values(release_id=staged.id))
    await db.execute(update(Game).where(Game.id == games[2].id).values(release_id=unvalidated.id))

    brunson_id = await _seeded_player_id(db, "Jalen Brunson")
    staged_player = Player(
        nba_player_id=1919001,
        full_name="Staged Only Guard",
        team_id="NYK",
        position="PG",
    )
    db.add(staged_player)
    await db.flush()

    db.add(
        PlayerGameStat(
            release_id=active.id,
            game_id=games[0].id,
            player_id=brunson_id,
            team_id="NYK",
            starter=True,
            minutes=34.0,
            points=28,
        )
    )
    db.add(
        PlayerGameStat(
            release_id=staged.id,
            game_id=games[1].id,
            player_id=staged_player.id,
            team_id="NYK",
            starter=True,
            minutes=30.0,
            points=11,
        )
    )
    # A player whose only facts belong to a release that failed validation.
    unvalidated_player = Player(
        nba_player_id=1919002,
        full_name="Unvalidated Only Forward",
        team_id="NYK",
        position="PF",
    )
    db.add(unvalidated_player)
    await db.flush()
    db.add(
        PlayerGameStat(
            release_id=unvalidated.id,
            game_id=games[2].id,
            player_id=unvalidated_player.id,
            team_id="NYK",
            minutes=12.0,
            points=4,
        )
    )

    staged_team = Team(
        id="ZZZ",
        nba_team_id=1999001,
        name="Ghosts",
        city="Nowhere",
        abbreviation="ZZZ",
    )
    db.add(staged_team)
    await db.flush()
    db.add(
        TeamGameStat(
            release_id=staged.id,
            game_id=games[1].id,
            team_id="ZZZ",
            points=99,
        )
    )
    await db.commit()
    return SimpleNamespace(
        active=active,
        staged=staged,
        brunson_id=brunson_id,
        staged_player_id=staged_player.id,
        unvalidated_player_id=unvalidated_player.id,
    )


async def test_player_directory_lists_only_active_release_members(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        scope = await _build_releases(db)
    _enforce(monkeypatch)

    response = await client.get("/players")
    assert response.status_code == 200
    assert [player["id"] for player in response.json()] == [scope.brunson_id]


async def test_player_detail_404s_outside_active_release(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        scope = await _build_releases(db)
    _enforce(monkeypatch)

    staged = await client.get(f"/players/{scope.staged_player_id}")
    assert staged.status_code == 404
    assert staged.json()["error"]["code"] == "http_404"

    unvalidated = await client.get(f"/players/{scope.unvalidated_player_id}")
    assert unvalidated.status_code == 404

    member = await client.get(f"/players/{scope.brunson_id}")
    assert member.status_code == 200
    assert member.json()["full_name"] == "Jalen Brunson"


async def test_team_directory_excludes_staged_only_teams(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        await _build_releases(db)
    _enforce(monkeypatch)

    response = await client.get("/teams")
    assert response.status_code == 200
    ids = {team["id"] for team in response.json()}
    assert "NYK" in ids
    assert "ZZZ" not in ids


async def test_team_detail_404s_for_unknown_team(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        await _build_releases(db)
    _enforce(monkeypatch)

    response = await client.get("/teams/ZZZ")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"

    known = await client.get("/teams/NYK")
    assert known.status_code == 200
    assert known.json()["city"] == "New York"


async def test_directories_are_empty_without_an_active_validated_release(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        scope = await _build_releases(db)
        await db.execute(update(DatasetRelease).values(status="staged", validation_passed=True))
        await db.commit()
    _enforce(monkeypatch)

    players = await client.get("/players")
    assert players.status_code == 200
    assert players.json() == []
    assert (await client.get("/players?team_id=NYK")).json() == []
    assert (await client.get(f"/players/{scope.brunson_id}")).status_code == 404

    teams = await client.get("/teams")
    assert teams.status_code == 200
    assert teams.json() == []
    assert (await client.get("/teams/NYK")).status_code == 404


async def test_directory_filters_stay_inside_release_membership(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        scope = await _build_releases(db)
    _enforce(monkeypatch)

    filtered = await client.get("/players?team_id=NYK&search=brunson")
    assert filtered.status_code == 200
    assert [player["id"] for player in filtered.json()] == [scope.brunson_id]

    excluded = await client.get("/players?search=staged")
    assert excluded.status_code == 200
    assert excluded.json() == []
