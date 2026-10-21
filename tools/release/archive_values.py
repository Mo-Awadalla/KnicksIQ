"""Archive-wide and question-scoped value indexes for reduced response artifacts.

A reduced artifact keeps only citation counts, not claim values. Numbers can then be checked
only against values the release actually contains; this is not claim-level proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import asyncpg
from app.evaluation.heldout_facts import (
    avg_margin,
    avg_opponent_points,
    avg_points,
    dsn,
    load_archive,
    record,
)
from team_aliases import PLAYER_ALIASES, TEAM_ALIASES


@dataclass
class ArchiveValues:
    numbers: list[float] = field(default_factory=list)
    text: str = ""
    entities: set[str] = field(default_factory=set)
    universe: dict[str, tuple[str, ...]] = field(default_factory=dict)
    archive: object | None = None
    team_ids: dict[str, str] = field(default_factory=dict)
    team_names: dict[str, str] = field(default_factory=dict)


def _add(values: list[float], *items: object) -> None:
    for item in items:
        if isinstance(item, bool) or item is None:
            continue
        if isinstance(item, (int, float)):
            values.append(float(item))


def _without_duplicates(values: list[float]) -> list[float]:
    return list(dict.fromkeys(round(value, 6) for value in values))


async def build(connection: asyncpg.Connection | None = None) -> ArchiveValues:
    owned = connection is None
    connection = connection or await asyncpg.connect(dsn())
    try:
        archive = await load_archive(connection)
        players = await connection.fetch("select full_name from players")
        teams = await connection.fetch("select id, name from teams")
    finally:
        if owned:
            await connection.close()
    roster = [row["full_name"] for row in players if not row["full_name"].startswith("NBA Player")]
    values: list[float] = []
    universe: dict[str, tuple[str, ...]] = {}
    names: list[str] = []
    for game in archive.games:
        _add(
            values,
            game.home_score,
            game.away_score,
            game.knicks_points,
            game.opponent_points,
            game.margin,
        )
        _add(values, game.home_score - game.away_score, game.away_score - game.home_score)
    for line in archive.lines:
        _add(
            values,
            line.points,
            line.rebounds,
            line.assists,
            line.turnovers,
            line.steals,
            line.blocks,
            line.three_pointers_made,
            line.plus_minus,
            round(line.minutes, 1),
            round(line.minutes, 2),
        )
    for season_type in ("regular", "playoffs"):
        games = archive.select(season_type=season_type)
        wins, losses = record(games)
        _add(
            values,
            wins,
            losses,
            len(games),
            avg_points(games),
            avg_opponent_points(games),
            avg_margin(games),
        )
    for site in ("home", "away"):
        games = archive.select(site=site)
        wins, losses = record(games)
        _add(
            values,
            wins,
            losses,
            len(games),
            avg_points(games),
            avg_opponent_points(games),
            avg_margin(games),
        )
    wins, losses = record(archive.games)
    _add(
        values,
        wins,
        losses,
        len(archive.games),
        avg_points(archive.games),
        avg_opponent_points(archive.games),
        avg_margin(archive.games),
    )
    _add(
        values,
        len(archive.select()),
        len(archive.select(season_type="regular")),
        len(archive.select(season_type="playoffs")),
    )
    for _game, quarters in archive.quarters.items():
        for quarter in quarters:
            _add(
                values, quarter.period, quarter.nyk_points, quarter.opponent_points, quarter.margin
            )
    for game in archive.games:
        dates = (game.game_date.year, game.game_date.month, game.game_date.day)
        _add(values, *dates)
    for season_type in (None, "regular", "playoffs"):
        games = archive.select(season_type=season_type) if season_type else archive.games
        wins, losses = record(games)
        _add(
            values,
            wins,
            losses,
            len(games),
            sum(game.knicks_points for game in games),
            sum(game.opponent_points for game in games),
            sum(game.margin for game in games),
            avg_points(games),
            avg_opponent_points(games),
            avg_margin(games),
        )
    for opponent in {game.opponent for game in archive.games}:
        games = archive.select(opponent=opponent)
        wins, losses = record(games)
        _add(
            values,
            wins,
            losses,
            len(games),
            sum(game.knicks_points for game in games),
            sum(game.opponent_points for game in games),
            avg_points(games),
            avg_opponent_points(games),
            avg_margin(games),
        )
    for month in (
        (2025, 10),
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
        (2026, 3),
        (2026, 4),
        (2026, 5),
        (2026, 6),
    ):
        games = [
            game for game in archive.games if (game.game_date.year, game.game_date.month) == month
        ]
        if not games:
            continue
        wins, losses = record(games)
        _add(
            values,
            wins,
            losses,
            len(games),
            sum(game.knicks_points for game in games),
            sum(game.opponent_points for game in games),
            sum(game.margin for game in games),
            avg_points(games),
            avg_opponent_points(games),
            avg_margin(games),
        )
    for count in range(1, 16):
        for games in (archive.last(count), archive.first(count)):
            wins, losses = record(games)
            _add(
                values,
                wins,
                losses,
                len(games),
                sum(game.knicks_points for game in games),
                sum(game.opponent_points for game in games),
                sum(game.margin for game in games),
                avg_points(games),
                avg_opponent_points(games),
                avg_margin(games),
            )
    for player in roster:
        for season_type in (None, "regular", "playoffs"):
            observed = archive.player_games(player, season_type=season_type)
            if not observed:
                continue
            for metric in (
                "points",
                "rebounds",
                "assists",
                "turnovers",
                "steals",
                "blocks",
                "three_pointers_made",
                "plus_minus",
            ):
                total = sum(getattr(line, metric) for line in observed)
                _add(
                    values, total, round(total / len(observed), 1), round(total / len(observed), 2)
                )
    surnames: dict[str, int] = {}
    for name in roster:
        surnames[name.split()[-1]] = surnames.get(name.split()[-1], 0) + 1
    for name in roster:
        aliases = PLAYER_ALIASES.get(name, ())
        surname = name.split()[-1]
        if surnames[surname] == 1:
            aliases = (surname, *aliases)
        universe[name] = tuple(dict.fromkeys((name, *aliases)))
        names.extend(universe[name])
    for team in teams:
        canonical = TEAM_ALIASES.get(team["name"], (team["name"],))
        universe[team["name"]] = canonical
        names.extend(canonical)
    team_ids: dict[str, str] = {}
    team_names: dict[str, str] = {}
    for team in teams:
        canonical = TEAM_ALIASES.get(team["name"], (team["name"],))
        team_names[team["id"]] = team["name"]
        for alias in canonical:
            team_ids[alias.casefold()] = team["id"]
        team_ids[team["id"].casefold()] = team["id"]
    return ArchiveValues(
        numbers=_without_duplicates(values),
        text=" ".join(dict.fromkeys(names)).casefold(),
        entities=set(),
        universe=universe,
        archive=archive,
        team_ids=team_ids,
        team_names=team_names,
    )


MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


@dataclass
class Scope:
    text: str
    numbers: list[float]
    entities: set[str]
    games: int = 0


def _contains(text: str, alias: str) -> bool:
    token = alias.casefold()
    if not token:
        return False
    if " " not in token:
        return re.search(rf"\b{re.escape(token)}\b", text) is not None
    return token in text


def _months(text: str) -> list[tuple[int, int | None]]:
    found: list[tuple[int, int | None]] = []
    for name, month in MONTHS.items():
        for match in re.finditer(rf"\b{name}\b\.?\s*(\d{{1,2}})?", text):
            day = int(match.group(1)) if match.group(1) else None
            if day and day > 31:
                day = None
            found.append((month, day))
    return found


def _window(text: str) -> tuple[str, int] | None:
    match = re.search(
        r"\b(last|final|first)\s+(\d+)\s+(?:archived\s+|regular-season\s+|playoff\s+)?games\b", text
    )
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _team_ids(text: str, values: ArchiveValues) -> set[str]:
    found = set()
    for alias, team_id in values.team_ids.items():
        if alias == "was":
            continue
        if team_id != "NYK" and _contains(text, alias):
            found.add(team_id)
    return found


def _player_names(text: str, values: ArchiveValues) -> set[str]:
    found = set()
    for name, aliases in values.universe.items():
        if not any(line.player == name for line in values.archive.lines):
            continue
        if any(_contains(text, alias) for alias in aliases):
            found.add(name)
    return found


def _add_team_values(values: list[float], games: list, archive) -> None:
    for game in games:
        _add(
            values,
            game.home_score,
            game.away_score,
            game.knicks_points,
            game.opponent_points,
            game.margin,
        )
        _add(values, game.game_date.year, game.game_date.month, game.game_date.day)
    if not games:
        return
    wins, losses = record(games)
    _add(
        values,
        wins,
        losses,
        len(games),
        sum(game.knicks_points for game in games),
        sum(game.opponent_points for game in games),
        sum(game.margin for game in games),
        avg_points(games),
        avg_opponent_points(games),
        avg_margin(games),
    )
    for site in ("home", "away"):
        subset = [
            game for game in games if (game.knicks_home if site == "home" else not game.knicks_home)
        ]
        if subset:
            site_wins, site_losses = record(subset)
            _add(
                values,
                site_wins,
                site_losses,
                len(subset),
                sum(game.knicks_points for game in subset),
                sum(game.opponent_points for game in subset),
                avg_points(subset),
                avg_opponent_points(subset),
                avg_margin(subset),
            )
    for season_type in ("regular", "playoffs"):
        subset = [game for game in games if game.season_type == season_type]
        if subset:
            type_wins, type_losses = record(subset)
            _add(
                values,
                type_wins,
                type_losses,
                len(subset),
                sum(game.knicks_points for game in subset),
                sum(game.opponent_points for game in subset),
                avg_points(subset),
                avg_opponent_points(subset),
                avg_margin(subset),
            )
    most = max(games, key=lambda game: game.knicks_points)
    fewest = min(games, key=lambda game: game.knicks_points)
    _add(values, most.knicks_points, most.opponent_points, most.margin)
    _add(values, fewest.knicks_points, fewest.opponent_points, fewest.margin)
    biggest = max(games, key=lambda game: game.margin)
    worst = min(games, key=lambda game: game.margin)
    _add(values, biggest.knicks_points, biggest.opponent_points, biggest.margin)
    _add(values, worst.knicks_points, worst.opponent_points, worst.margin)
    for game in games[:40]:
        for quarter in archive.quarters.get(game.id, []):
            _add(
                values, quarter.period, quarter.nyk_points, quarter.opponent_points, quarter.margin
            )


def _metric(text: str) -> str | None:
    lowered = text.casefold()
    for words, metric in (
        (("rebound", "glass"), "rebounds"),
        (("assist",), "assists"),
        (("turnover",), "turnovers"),
        (("steal",), "steals"),
        (("block",), "blocks"),
        (("three", "3-point"), "three_pointers_made"),
        (("minute",), "minutes"),
        (("plus-minus", "plus/minus"), "plus_minus"),
        (("point", "scor"), "points"),
    ):
        if any(word in lowered for word in words):
            return metric
    return None


def _add_player_values(
    values: list[float], archive, players: set[str], games: list, metric: str | None = None
) -> None:
    game_ids = {game.id for game in games}
    metrics = (
        (metric,)
        if metric
        else (
            "points",
            "rebounds",
            "assists",
            "turnovers",
            "steals",
            "blocks",
            "three_pointers_made",
            "plus_minus",
        )
    )
    for player in players:
        lines = [
            line for line in archive.lines if line.player == player and line.game_id in game_ids
        ]
        if not lines:
            continue
        for line in lines:
            _add(values, *(getattr(line, item) for item in metrics))
            if not metric:
                _add(values, round(line.minutes, 1), round(line.minutes, 2))
        for item in metrics:
            total = sum(getattr(line, item) for line in lines)
            _add(values, total, round(total / len(lines), 1), round(total / len(lines), 2))
        _add(values, len(lines))


def scoped_corpus(
    values: ArchiveValues, question: str, case: dict, answer: str = ""
) -> Scope | None:
    archive = values.archive
    if archive is None:
        return None
    filters = case.get("filters") or {}
    games = list(archive.games)

    game_id = filters.get("game_id")
    if game_id:
        games = [game for game in games if game.id == int(game_id)]
    opponents = set()
    if filters.get("opponent"):
        opponents.add(str(filters["opponent"]))
    for item in filters.get("opponents") or []:
        opponents.add(str(item))
    opponents |= _team_ids(question.casefold(), values)
    if opponents:
        games = [game for game in games if game.opponent in opponents]

    season_types = filters.get("season_types") or []
    if filters.get("season_type"):
        season_types = [str(filters["season_type"])]
    if season_types:
        games = [game for game in games if game.season_type in season_types]

    site = filters.get("site")
    lowered = question.casefold()
    if not site:
        if "home" in lowered and not re.search(r"\b(road|away)\b", lowered):
            site = "home"
        elif re.search(r"\b(road|away)\b", lowered) and "home" not in lowered:
            site = "away"
    if isinstance(site, str):
        if site == "home":
            games = [game for game in games if game.knicks_home]
        elif site == "away":
            games = [game for game in games if not game.knicks_home]

    months: list[int] = []
    days: list[int] = []
    if filters.get("month"):
        parts = str(filters["month"]).split("-")
        months.append(int(parts[1]))
    for month, day in _months(question.casefold()):
        if month not in months:
            months.append(month)
        if day is not None and len(months) == 1:
            days.append(day)
    if months:
        games = [game for game in games if game.game_date.month in months]
    if days:
        games = [game for game in games if game.game_date.day in days]

    window = filters.get("window")
    if isinstance(window, str):
        match = re.search(r"(last|first)(\d+)", window)
        if match:
            count = int(match.group(2))
            games = games[-count:] if match.group(1) == "last" else games[:count]
    else:
        parsed = _window(question.casefold())
        if parsed:
            kind, count = parsed
            games = games[-count:] if kind in {"last", "final"} else games[:count]

    if not games:
        return None
    players = set()
    for key in ("player",):
        if filters.get(key):
            players.add(str(filters[key]))
    for item in filters.get("players") or []:
        players.add(str(item))
    players |= _player_names(question.casefold(), values)
    if not players and case.get("category") in {
        "single_game_narrative",
        "turning_points",
        "aliases_typos",
    }:
        players |= _player_names(answer.casefold(), values)
    if not players and (
        "who" in question.casefold()
        or "which player" in question.casefold()
        or not case.get("answerable", True)
    ):
        players |= _player_names(answer.casefold(), values)
    players = {name for name in players if name in {line.player for line in archive.lines}}

    numbers: list[float] = []
    _add_team_values(numbers, games, archive)
    metric = (
        _metric(question)
        if case.get("category") in {"exact_statistics", "comparisons", "date_range_last_n"}
        else None
    )
    _add_player_values(numbers, archive, players, games, metric)
    if not players:
        numbers = [value for value in numbers if value != 0]
    names: list[str] = []
    for game in games:
        for team_id in (game.home_team_id, game.away_team_id):
            name = values.team_names.get(team_id)
            if name:
                names.extend(values.universe.get(name, (name,)))
                names.append(team_id)
    for player in players:
        names.extend(values.universe.get(player, (player,)))
    return Scope(
        text=" ".join(dict.fromkeys(names)).casefold(),
        numbers=_without_duplicates(numbers),
        entities=set(players),
        games=len(games),
    )
