"""Seeded releases and analyst tools for the evaluator's arithmetic contracts.

Four archive shapes cover the recipes: a mixed home/away season with one four-game
losing run, a season whose longest losing run ties twice, the discovery archive where a
subject's latest ten appearances differ from his prior four, and the policy record every
catalog claim declares about its own qualifiers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

VERSION = "2025-26.arithmetic-test"


ARCHIVE = (
    ("2025-11-05", "NYK", "BOS", 112, 104),
    ("2025-11-20", "BOS", "NYK", 100, 108),
    ("2025-12-05", "NYK", "BOS", 118, 110),
    ("2025-12-15", "BOS", "NYK", 120, 99),
    ("2025-12-31", "SAS", "NYK", 134, 132),
    ("2026-01-02", "NYK", "ATL", 99, 111),
    ("2026-01-05", "NYK", "MIA", 98, 105),
    ("2026-01-08", "DET", "NYK", 96, 101),
)


TIES = (
    ("2025-11-01", "NYK", "BOS", 100, 105),
    ("2025-11-03", "NYK", "BOS", 98, 110),
    ("2025-11-05", "NYK", "BOS", 95, 102),
    ("2025-11-07", "NYK", "BOS", 90, 99),
    ("2025-11-09", "NYK", "BOS", 110, 100),
    ("2025-11-11", "NYK", "BOS", 112, 104),
    ("2025-11-13", "NYK", "BOS", 118, 111),
    ("2025-11-15", "NYK", "BOS", 120, 119),
    ("2025-11-17", "NYK", "BOS", 101, 108),
    ("2025-11-19", "NYK", "BOS", 104, 111),
    ("2025-11-21", "NYK", "BOS", 99, 107),
    ("2025-11-23", "NYK", "BOS", 96, 105),
)


POLICY = {
    "policy_version": "player-intelligence-v1",
    "minimum_appearances": 4,
    "appearance": "minutes > 0",
    "true_shooting_minimum_fga_per_appearance": 5,
    "recent_window": 10,
    "prior_minimum_appearances": 4,
    "population": "Knicks qualifiers in complete release window",
}


DISCOVERY_GAMES = tuple(
    (f"2025-11-{day:02d}", "NYK", "BOS", 110 + index, 100)
    for index, day in enumerate(range(1, 28, 2))
)


DISCOVERY_BOX = {
    "Jalen Brunson": (14, 8, 30, {"rebounds": 4, "assists": 6, "threes": 2, "fga": 20, "fta": 8}),
    "Karl-Anthony Towns": (
        14,
        25,
        25,
        {"rebounds": 8, "assists": 4, "threes": 1, "fga": 18, "fta": 6},
    ),
    "OG Anunoby": (14, 14, 14, {"rebounds": 6, "assists": 3, "threes": 3, "fga": 3, "fta": 2}),
    "Mikal Bridges": (14, 12, 12, {"rebounds": 5, "assists": 2, "threes": 0, "fga": 10, "fta": 3}),
    "Josh Hart": (3, 40, 40, {"rebounds": 10, "assists": 5, "threes": 3, "fga": 12, "fta": 4}),
}


HART_GAMES = (7, 8, 9)


async def _seed(db_session, archive=ARCHIVE) -> DatasetRelease:
    release = DatasetRelease(
        version=VERSION,
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
    bench = (
        await db_session.execute(select(Player).where(Player.full_name == "Mikal Bridges"))
    ).scalar_one()
    for index, (day, home, away, home_score, away_score) in enumerate(archive):
        game = await _game(db_session, release, index, day, home, away, home_score, away_score)
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=player.id,
                team_id="NYK",
                starter=True,
                minutes=34.0,
                points=20 + index,
                assists=6,
            )
        )
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=bench.id,
                team_id="NYK",
                starter=False,
                position="F",
                minutes=20.0,
                points=10,
                assists=2,
            )
        )
        db_session.add(
            TeamGameStat(
                release_id=release.id,
                game_id=game.id,
                team_id="NYK",
                points=home_score if home == "NYK" else away_score,
                field_goals_made=7 + index,
                field_goals_attempted=15 + index,
                three_pointers_made=2,
                three_pointers_attempted=5,
                free_throws_made=4,
                free_throws_attempted=5,
                offensive_rebounds=3,
                defensive_rebounds=9,
                rebounds=12,
                assists=8,
                steals=2,
                blocks=1,
                turnovers=3,
                personal_fouls=4,
                plus_minus=index - 2,
            )
        )
        db_session.add(
            PeriodScore(release_id=release.id, game_id=game.id, team_id="NYK", period=1, points=25)
        )
    await db_session.commit()
    return release


async def _game(db_session, release, index: int, day, home, away, home_score, away_score) -> Game:
    game = Game(
        release_id=release.id,
        nba_game_id=f"00225000{index:02d}",
        season="2025-26",
        game_date=date.fromisoformat(day),
        home_team_id=home,
        away_team_id=away,
        home_score=home_score,
        away_score=away_score,
        status="final",
        season_type="regular",
        data_status="analysis_ready",
        source_name="test",
        source_game_id=f"00225000{index:02d}",
        source_url="https://example.test/game",
        source_payload_hash="0" * 64,
        source_fetched_at=datetime.now(UTC),
    )
    db_session.add(game)
    await db_session.flush()
    return game


async def _seed_discovery(db_session) -> DatasetRelease:
    release = DatasetRelease(
        version=VERSION,
        season="2025-26",
        source="test",
        manifest_sha256="b" * 64,
        validation_passed=True,
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    players = {}
    for name in DISCOVERY_BOX:
        player = (
            await db_session.execute(select(Player).where(Player.full_name == name))
        ).scalar_one()
        players[name] = player
    for index, (day, home, away, home_score, away_score) in enumerate(DISCOVERY_GAMES):
        game = await _game(db_session, release, index, day, home, away, home_score, away_score)
        for name, (games, early, late, stats) in DISCOVERY_BOX.items():
            if name == "Josh Hart" and index not in HART_GAMES:
                continue
            if name != "Josh Hart" and games <= index:
                continue
            db_session.add(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=game.id,
                    player_id=players[name].id,
                    team_id="NYK",
                    starter=True,
                    minutes=30.0,
                    points=late if name == "Jalen Brunson" and index >= 4 else early,
                    rebounds=stats["rebounds"],
                    assists=stats["assists"],
                    three_pointers_made=stats["threes"],
                    three_pointers_attempted=stats["threes"] + 3,
                    field_goals_made=stats["fga"] // 2,
                    field_goals_attempted=stats["fga"],
                    free_throws_made=stats["fta"] // 2,
                    free_throws_attempted=stats["fta"],
                )
            )
    await db_session.commit()
    return release


async def _tools(db_session, question: str, archive=ARCHIVE) -> AnalystTools:
    release = await _seed(db_session, archive)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    return tools


async def _discovery_tools(db_session) -> AnalystTools:
    release = await _seed_discovery(db_session)
    tools = AnalystTools(db_session, release, "Give me an interesting stat", release.season, {})
    await tools.prepare()
    return tools


def _appearances(tools: AnalystTools, player_id: int) -> list:
    """One player's (game, row) pairs in archive order, exactly as the producers order them."""
    return [
        (game, pair)
        for game in tools.games
        for pair in tools.rows
        if pair[0].player_id == player_id and pair[0].game_id == game.id and pair[0].minutes > 0
    ]
