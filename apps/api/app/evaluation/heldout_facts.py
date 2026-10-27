"""Deterministic archive facts for the held-out analyst evaluation set.

Every value is read from the active local release. The held-out questions are generated from
these facts, never labelled by a model. Run with DB_URL pointing at a restored release.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import asyncpg

KNICKS = "NYK"
METRICS = (
    "points",
    "rebounds",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "three_pointers_made",
    "minutes",
    "plus_minus",
)


def dsn() -> str:
    value = os.environ.get("DB_URL", "")
    if not value:
        raise SystemExit("DB_URL is required")
    return value.replace("postgresql+asyncpg://", "postgresql://")


@dataclass(frozen=True)
class Game:
    id: int
    game_date: date
    season_type: str
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int

    @property
    def knicks_home(self) -> bool:
        return self.home_team_id == KNICKS

    @property
    def opponent(self) -> str:
        return self.away_team_id if self.knicks_home else self.home_team_id

    @property
    def knicks_points(self) -> int:
        return self.home_score if self.knicks_home else self.away_score

    @property
    def opponent_points(self) -> int:
        return self.away_score if self.knicks_home else self.home_score

    @property
    def won(self) -> bool:
        return self.knicks_points > self.opponent_points

    @property
    def margin(self) -> int:
        return self.knicks_points - self.opponent_points


@dataclass(frozen=True)
class Line:
    game_id: int
    player: str
    points: int
    rebounds: int
    assists: int
    turnovers: int
    steals: int
    blocks: int
    three_pointers_made: int
    minutes: float
    plus_minus: int


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def record(games: list[Game]) -> tuple[int, int]:
    wins = sum(1 for game in games if game.won)
    return wins, len(games) - wins


def avg_points(games: list[Game]) -> float:
    return round(_mean([float(game.knicks_points) for game in games]), 2)


def avg_opponent_points(games: list[Game]) -> float:
    return round(_mean([float(game.opponent_points) for game in games]), 2)


def avg_margin(games: list[Game]) -> float:
    return round(_mean([float(game.margin) for game in games]), 2)


class Archive:
    def __init__(
        self,
        release: str,
        games: list[Game],
        lines: list[Line],
        quarters: dict[int, list[Quarter]],
    ) -> None:
        self.release = release
        self.games = sorted(games, key=lambda game: (game.game_date, game.id))
        self.lines = [line for line in lines if line.game_id in {game.id for game in self.games}]
        self.quarters = quarters
        self._by_game: dict[int, list[Line]] = {}
        for line in self.lines:
            self._by_game.setdefault(line.game_id, []).append(line)

    def game(self, game_id: int) -> Game:
        return next(game for game in self.games if game.id == game_id)

    def select(
        self,
        *,
        season_type: str | None = None,
        opponent: str | None = None,
        start: date | None = None,
        end: date | None = None,
        site: str | None = None,
    ) -> list[Game]:
        result = []
        for game in self.games:
            if season_type and game.season_type != season_type:
                continue
            if opponent and game.opponent != opponent:
                continue
            if start and game.game_date < start:
                continue
            if end and game.game_date > end:
                continue
            if site == "home" and not game.knicks_home:
                continue
            if site == "away" and game.knicks_home:
                continue
            result.append(game)
        return result

    def last(self, count: int, *, season_type: str | None = None) -> list[Game]:
        return self.select(season_type=season_type)[-count:]

    def first(self, count: int, *, season_type: str | None = None) -> list[Game]:
        return self.select(season_type=season_type)[:count]

    def line(self, player: str, game_id: int) -> Line:
        return next(
            line for line in self._by_game[game_id] if line.player.casefold() == player.casefold()
        )

    def player_games(
        self,
        player: str,
        *,
        season_type: str | None = None,
        games: list[Game] | None = None,
        include_dnp: bool = False,
    ) -> list[Line]:
        """Player rows, by default only games the player actually appeared in.

        A zero-minute row is a did-not-play record. Counting it in a per-game average
        divides by games the player did not play; the app's metrics exclude it.
        """
        allowed = {game.id for game in games} if games is not None else None
        type_by_id = {game.id: game.season_type for game in self.games}
        return [
            line
            for line in self.lines
            if line.player.casefold() == player.casefold()
            and (allowed is None or line.game_id in allowed)
            and (season_type is None or type_by_id[line.game_id] == season_type)
            and (include_dnp or line.minutes > 0)
        ]

    def player_avg(
        self,
        player: str,
        metric: str,
        *,
        season_type: str | None = None,
        games: list[Game] | None = None,
    ) -> float:
        if metric not in METRICS:
            raise ValueError(metric)
        observed = self.player_games(player, season_type=season_type, games=games)
        return round(_mean([float(getattr(line, metric)) for line in observed]), 2)

    def player_total(self, player: str, metric: str, *, season_type: str | None = None) -> int:
        observed = self.player_games(player, season_type=season_type)
        return int(sum(getattr(line, metric) for line in observed))

    def top_scorer(self, game_id: int) -> Line:
        return max(self._by_game[game_id], key=lambda line: (line.points, line.rebounds))

    def largest_quarter(self, game_id: int, *, by: str = "margin") -> Quarter:
        """The Knicks' best quarter. Period scores are the authoritative period totals."""
        quarters = self.quarters[game_id]
        if by == "margin":
            return max(quarters, key=lambda item: (item.margin, item.nyk_points, -item.period))
        if by == "points":
            return max(quarters, key=lambda item: (item.nyk_points, item.margin, -item.period))
        raise ValueError(by)

    def worst_quarter(self, game_id: int) -> Quarter:
        """The quarter the opponent won by the most, used for losses."""
        return min(self.quarters[game_id], key=lambda item: (item.margin, -item.period))


async def load_archive(connection: asyncpg.Connection) -> Archive:
    release = await connection.fetchrow(
        "select id, version from dataset_releases "
        "where status = 'active' and validation_passed is true"
    )
    if release is None:
        raise SystemExit("no active validated release")
    game_rows = await connection.fetch(
        "select id, game_date, season_type::text as season_type, home_team_id, away_team_id, "
        "home_score, away_score from games where release_id = $1",
        release["id"],
    )
    quarter_rows = await connection.fetch(
        "select game_id, period, "
        "sum(case when team_id = $2 then points else 0 end) as nyk_points, "
        "sum(case when team_id <> $2 then points else 0 end) as opponent_points "
        "from period_scores where release_id = $1 group by game_id, period",
        release["id"],
        KNICKS,
    )
    line_rows = await connection.fetch(
        "select s.game_id, p.full_name, s.points, s.rebounds, s.assists, s.turnovers, "
        "s.steals, s.blocks, s.three_pointers_made, s.minutes, s.plus_minus "
        "from player_game_stats s join players p on p.id = s.player_id "
        "where s.release_id = $1 and s.team_id = $2",
        release["id"],
        KNICKS,
    )
    games = [
        Game(
            id=row["id"],
            game_date=row["game_date"],
            season_type=row["season_type"],
            home_team_id=row["home_team_id"],
            away_team_id=row["away_team_id"],
            home_score=row["home_score"],
            away_score=row["away_score"],
        )
        for row in game_rows
    ]
    lines = [
        Line(
            game_id=row["game_id"],
            player=row["full_name"],
            points=row["points"],
            rebounds=row["rebounds"],
            assists=row["assists"],
            turnovers=row["turnovers"],
            steals=row["steals"],
            blocks=row["blocks"],
            three_pointers_made=row["three_pointers_made"],
            minutes=float(row["minutes"]),
            plus_minus=row["plus_minus"],
        )
        for row in line_rows
    ]
    quarters: dict[int, list[Quarter]] = {}
    for row in quarter_rows:
        quarters.setdefault(row["game_id"], []).append(
            Quarter(
                period=row["period"],
                nyk_points=row["nyk_points"],
                opponent_points=row["opponent_points"],
            )
        )
    for items in quarters.values():
        items.sort(key=lambda item: item.period)
    return Archive(str(release["version"]), games, lines, quarters)


@dataclass(frozen=True)
class Quarter:
    period: int
    nyk_points: int
    opponent_points: int

    @property
    def margin(self) -> int:
        return self.nyk_points - self.opponent_points
