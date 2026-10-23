"""Release-scoped player data retrieval and archive window selection."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.core.config import get_settings
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from basketball_core.analytics import (
    AnalyticsOperation,
    AnalyticsPlan,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_STAT_COLUMNS = (
    "minutes",
    "points",
    "field_goals_made",
    "field_goals_attempted",
    "three_pointers_made",
    "three_pointers_attempted",
    "free_throws_made",
    "free_throws_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "personal_fouls",
    "plus_minus",
)


async def _release_id(db: AsyncSession) -> int | None:
    active = (
        await db.execute(
            select(DatasetRelease.id)
            .where(
                DatasetRelease.status == "active",
                DatasetRelease.validation_passed.is_(True),
            )
            .order_by(DatasetRelease.activated_at.desc(), DatasetRelease.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None or not getattr(get_settings(), "test_mode", False):
        return active
    return (await db.execute(select(func.max(PlayerGameStat.release_id)))).scalar_one_or_none()


async def _archive_players(db: AsyncSession, release_id: int | None) -> list[Player]:
    if release_id is None:
        return list((await db.execute(select(Player).order_by(Player.full_name))).scalars())
    return list(
        (
            await db.execute(
                select(Player)
                .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
                .where(PlayerGameStat.release_id == release_id)
                .distinct()
                .order_by(Player.full_name)
            )
        ).scalars()
    )


def _row_dict(stat: PlayerGameStat, player: Player, game: Game) -> dict[str, Any]:
    home = game.home_team_id == stat.team_id
    own_score = game.home_score if home else game.away_score
    opponent_score = game.away_score if home else game.home_score
    row = {
        "game_id": game.id,
        "date": game.game_date.isoformat(),
        "season_type": game.season_type,
        "player_id": player.id,
        "nba_person_id": player.nba_player_id,
        "player_name": player.full_name,
        "team_id": stat.team_id,
        "opponent": game.away_team_id if home else game.home_team_id,
        "home": home,
        "win": own_score > opponent_score,
        "knicks_win": (
            game.home_score > game.away_score
            if game.home_team_id == "NYK"
            else game.away_score > game.home_score
        ),
        "starter": bool(stat.starter),
        "appeared": float(stat.minutes or 0) > 0,
        "score": {
            stat.team_id: own_score,
            game.away_team_id if home else game.home_team_id: opponent_score,
        },
    }
    row.update({column: getattr(stat, column) for column in _STAT_COLUMNS})
    return row


async def _games_and_rows(
    db: AsyncSession, release_id: int | None, season: str
) -> tuple[list[Game], list[dict[str, Any]]]:
    game_stmt = (
        select(Game)
        .where(
            Game.season == season,
            or_(Game.home_team_id == "NYK", Game.away_team_id == "NYK"),
            Game.status == "final",
        )
        .order_by(Game.game_date, Game.nba_game_id)
    )
    if release_id is not None:
        game_stmt = game_stmt.where(Game.release_id == release_id)
    games = list((await db.execute(game_stmt)).scalars())
    if release_id is None:
        return games, []
    rows = (
        await db.execute(
            select(PlayerGameStat, Player, Game)
            .join(Player, Player.id == PlayerGameStat.player_id)
            .join(Game, Game.id == PlayerGameStat.game_id)
            .where(
                PlayerGameStat.release_id == release_id,
                Game.release_id == release_id,
                Game.season == season,
                or_(Game.home_team_id == "NYK", Game.away_team_id == "NYK"),
            )
            .order_by(Game.game_date, Game.nba_game_id, Player.nba_player_id)
        )
    ).all()
    return games, [_row_dict(stat, player, game) for stat, player, game in rows]


def _select_window(
    games: list[Game], rows: list[dict[str, Any]], plan: AnalyticsPlan
) -> tuple[list[Game], list[dict[str, Any]]]:
    timeframe = plan.timeframe
    period_comparison = plan.operations[0] == AnalyticsOperation.PERIOD_COMPARISON
    scoped_games = games
    if timeframe.kind == "regular_season":
        scoped_games = [game for game in games if game.season_type == "regular"]
    elif timeframe.kind == "playoffs":
        scoped_games = [game for game in games if game.season_type in {"play_in", "playoffs"}]
    elif timeframe.kind == "last_n":
        scope = plan.filters.get("season_scope")
        if scope == "regular":
            scoped_games = [game for game in games if game.season_type == "regular"]
        elif scope == "playoffs":
            scoped_games = [game for game in games if game.season_type in {"play_in", "playoffs"}]
        if timeframe.unit == "archive_games" and not period_comparison:
            scoped_games = scoped_games[-int(timeframe.last_n or 1) :]
    elif timeframe.kind in {"date_range", "month"}:
        start_date = date.fromisoformat(timeframe.start_date) if timeframe.start_date else None
        end_date = date.fromisoformat(timeframe.end_date) if timeframe.end_date else None
        scoped_games = [
            game
            for game in games
            if (start_date is None or game.game_date >= start_date)
            and (end_date is None or game.game_date <= end_date)
        ]
    game_ids = {game.id for game in scoped_games}
    selected = [row for row in rows if row["game_id"] in game_ids]
    player_ids = {player.player_id for player in plan.resolved_players}
    if player_ids:
        selected = [row for row in selected if row["player_id"] in player_ids]
    if (
        timeframe.kind == "last_n"
        and timeframe.unit == "appearances"
        and player_ids
        and not period_comparison
    ):
        by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in selected:
            if row["appeared"]:
                by_player[row["player_id"]].append(row)
        keep = {
            (row["player_id"], row["game_id"])
            for player_rows in by_player.values()
            for row in player_rows[-int(timeframe.last_n or 1) :]
        }
        selected = [row for row in selected if (row["player_id"], row["game_id"]) in keep]
        keep_game_ids = {game_id for _, game_id in keep}
        scoped_games = [game for game in scoped_games if game.id in keep_game_ids]
    for key, value in plan.filters.items():
        if key == "outcome":
            selected = [row for row in selected if row["win"] is (value == "win")]
        elif key == "location":
            selected = [row for row in selected if row["home"] is (value == "home")]
        elif key == "starter":
            selected = [row for row in selected if row["starter"] is bool(value)]
        elif key == "opponent":
            selected = [row for row in selected if row["opponent"] == value]
    if plan.filters.get("outcome"):
        want_win = plan.filters["outcome"] == "win"
        scoped_games = [
            game
            for game in scoped_games
            if (
                (game.home_score > game.away_score)
                if game.home_team_id == "NYK"
                else (game.away_score > game.home_score)
            )
            is want_win
        ]
    if plan.filters.get("location"):
        want_home = plan.filters["location"] == "home"
        scoped_games = [game for game in scoped_games if (game.home_team_id == "NYK") is want_home]
    if plan.filters.get("opponent"):
        opponent = plan.filters["opponent"]
        scoped_games = [
            game for game in scoped_games if opponent in {game.home_team_id, game.away_team_id}
        ]
    if plan.filters.get("game_selector") == "largest_win_margin" and scoped_games:

        def margin(game: Game) -> int:
            return (
                game.home_score - game.away_score
                if game.home_team_id == "NYK"
                else game.away_score - game.home_score
            )

        biggest = max(margin(game) for game in scoped_games)
        scoped_games = [game for game in scoped_games if margin(game) == biggest and biggest > 0]
        selected_ids = {game.id for game in scoped_games}
        selected = [row for row in selected if row["game_id"] in selected_ids]
    return scoped_games, selected


def _coverage(games: list[Game], rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {game.id for game in games}
    covered = {row["game_id"] for row in rows}
    missing = sorted(expected - covered)
    return {
        "expected_game_count": len(expected),
        "covered_game_count": len(expected & covered),
        "missing_game_ids": missing,
        "completeness": 1.0 if not expected else round(len(expected & covered) / len(expected), 4),
        "data_through": max((game.game_date.isoformat() for game in games), default=None),
    }


def _validate_requested_window(
    plan: AnalyticsPlan, games: list[Game], all_rows: list[dict[str, Any]]
) -> str | None:
    timeframe = plan.timeframe
    if timeframe.kind == "last_n":
        scoped_games = games
        scope = plan.filters.get("season_scope")
        if scope == "regular":
            scoped_games = [game for game in games if game.season_type == "regular"]
        elif scope == "playoffs":
            scoped_games = [game for game in games if game.season_type in {"play_in", "playoffs"}]
        requested = int(timeframe.last_n or 0)
        if timeframe.unit == "archive_games" and requested > len(scoped_games):
            return (
                f"That window requests {requested} games, but only {len(scoped_games)} "
                "matching archive games are available."
            )
        if timeframe.unit == "appearances" and plan.resolved_players:
            scoped_ids = {game.id for game in scoped_games}
            available = []
            for player in plan.resolved_players:
                available.append(
                    sum(
                        bool(row["appeared"])
                        for row in all_rows
                        if row["game_id"] in scoped_ids and row["player_id"] == player.player_id
                    )
                )
            if any(requested > count for count in available):
                return (
                    f"That window requests {requested} appearances, but the smallest resolved "
                    f"player sample contains {min(available, default=0)}."
                )
    if timeframe.kind in {"date_range", "month"}:
        start = date.fromisoformat(timeframe.start_date) if timeframe.start_date else date.min
        end = date.fromisoformat(timeframe.end_date) if timeframe.end_date else date.max
        if start > end:
            return "The requested date range ends before it starts."
        if not any(start <= game.game_date <= end for game in games):
            return "No active-release Knicks games fall inside that requested date window."
    return None
