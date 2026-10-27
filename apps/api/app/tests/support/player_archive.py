"""Seed release-scoped player box scores for integration contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from sqlalchemy import select


async def _seed_release_stats(db_session) -> tuple[DatasetRelease, Player]:
    release = DatasetRelease(
        version="analytics-test",
        season="2025-26",
        source="test",
        manifest_sha256="a" * 64,
        validation_passed=True,
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    player = (
        await db_session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
    ).scalar_one()
    towns = (
        await db_session.execute(select(Player).where(Player.full_name == "Karl-Anthony Towns"))
    ).scalar_one()
    for index, (minutes, points) in enumerate(((34.0, 20), (0.0, 0), (36.0, 30)), start=1):
        game = Game(
            release_id=release.id,
            nba_game_id=f"analytics-{index}",
            season="2025-26",
            game_date=date(2026, 1, index),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=110 + index,
            away_score=100,
            status="final",
            season_type="regular",
            source_name="test",
            source_game_id=f"analytics-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=player.id,
                team_id="NYK",
                minutes=minutes,
                points=points,
                field_goals_attempted=10,
            )
        )
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=towns.id,
                team_id="NYK",
                minutes=32,
                points=15 + index,
                rebounds=10,
                assists=3,
                turnovers=1,
                three_pointers_made=1,
                three_pointers_attempted=4,
                field_goals_attempted=12,
            )
        )
    await db_session.commit()
    return release, player
