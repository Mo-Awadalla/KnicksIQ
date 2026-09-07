"""Deterministic game scopes for archive team questions."""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any

from app.services.team_aliases import team_ids_in_text

_MONTHS = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
_EAST = {
    "ATL",
    "BOS",
    "BKN",
    "CHA",
    "CHI",
    "CLE",
    "DET",
    "IND",
    "MIA",
    "MIL",
    "NYK",
    "ORL",
    "PHI",
    "TOR",
    "WAS",
}


def scores(game: Any) -> tuple[int, int]:
    return (
        (game.home_score, game.away_score)
        if game.home_team_id == "NYK"
        else (game.away_score, game.home_score)
    )


def scope_games(question: str, games: list[Any], *, window: bool = True) -> list[Any]:
    q = question.lower().replace("-", " ")
    selected = sorted(games, key=lambda g: (g.game_date, g.id))
    opponents = team_ids_in_text(question) - {"NYK"}
    if opponents:
        selected = [g for g in selected if opponents & {g.home_team_id, g.away_team_id}]
    if "regular season" in q:
        selected = [g for g in selected if g.season_type == "regular"]
    elif "playoff" in q or "postseason" in q:
        selected = [g for g in selected if g.season_type in {"play_in", "playoffs"}]
    home, away = bool(re.search(r"\bhome\b", q)), bool(re.search(r"\b(?:road|away)\b", q))
    if home != away:
        selected = [g for g in selected if (g.home_team_id == "NYK") == home]
    dates = [
        date.fromisoformat(value) for value in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", question)
    ]
    named = list(re.finditer(r"\b(" + "|".join(_MONTHS) + r")\b(?:\s+(\d{1,2}))?", q))
    if dates:
        if len(dates) > 1:
            selected = [g for g in selected if dates[0] <= g.game_date <= dates[-1]]
        elif "after" in q:
            selected = [g for g in selected if g.game_date > dates[0]]
        elif "before" in q:
            selected = [g for g in selected if g.game_date < dates[0]]
        elif "since" in q:
            selected = [g for g in selected if g.game_date >= dates[0]]
        else:
            selected = [g for g in selected if g.game_date == dates[0]]
    elif named:
        first, last = named[0], named[-1]
        start_month, end_month = _MONTHS[first[1]], _MONTHS[last[1]]
        start_day, end_day = int(first[2] or 1), int(last[2] or 31)
        start_year = next(
            (
                g.game_date.year
                for g in sorted(games, key=lambda g: g.game_date)
                if g.game_date.month == start_month
            ),
            games[-1].game_date.year if games else 2026,
        )
        end_year = start_year + (end_month < start_month)
        selected = [
            g
            for g in selected
            if (start_year, start_month, start_day)
            <= (g.game_date.year, g.game_date.month, g.game_date.day)
            <= (end_year, end_month, end_day)
        ]
    if "all star" in q and games:
        # The archive's mid-February schedule gap separates pre/post-break games.
        february = sorted({g.game_date for g in games if g.game_date.month == 2})
        gaps = [
            (b - a, a, b)
            for a, b in zip(february, february[1:], strict=False)
            if 8 <= a.day <= 18 and 14 <= b.day <= 25
        ]
        if gaps:
            _, before, after = max(gaps)
            if "after" in q and "before" not in q:
                selected = [g for g in selected if g.game_date >= after]
            elif "before" in q and "after" not in q:
                selected = [g for g in selected if g.game_date <= before]
    if window:
        match = re.search(r"\b(last|final|first)\s+(\d+)\s+(?:regular season\s+)?games?\b", q)
        if match:
            count = int(match[2])
            selected = (
                selected[:count] if match[1] == "first" else selected[-count:] if count else []
            )
    return selected


def comparison_groups(question: str, games: list[Any]) -> list[tuple[str, list[Any]]]:
    q = question.lower()
    if not any(term in q for term in ("compare", "better", "home or away", "eastern or western")):
        return []
    if "home" in q and ("road" in q or "away" in q):
        return [
            ("Home", [g for g in games if g.home_team_id == "NYK"]),
            ("Away", [g for g in games if g.away_team_id == "NYK"]),
        ]
    if "wins" in q and "losses" in q:
        return [
            ("Wins", [g for g in games if scores(g)[0] > scores(g)[1]]),
            ("Losses", [g for g in games if scores(g)[0] < scores(g)[1]]),
        ]
    if "eastern" in q and "western" in q:
        return [
            (
                label,
                [
                    g
                    for g in games
                    if (({g.home_team_id, g.away_team_id} - {"NYK"}).pop() in _EAST) == east
                ],
            )
            for label, east in [("Eastern", True), ("Western", False)]
        ]
    opponents = team_ids_in_text(question) - {"NYK"}
    if len(opponents) > 1:
        return [
            (opponent, [g for g in games if opponent in {g.home_team_id, g.away_team_id}])
            for opponent in sorted(opponents)
        ]
    windows = re.findall(r"\b(first|last|final)\s+(\d+)\s+games\b", q)
    if len(windows) > 1:
        return [
            (
                f"{direction.title()} {count} games",
                games[: int(count)] if direction == "first" else games[-int(count) :],
            )
            for direction, count in windows
        ]
    months = [name for name in _MONTHS if re.search(r"\b" + name + r"\b", q)]
    if len(months) > 1:
        return [
            (name.title(), [g for g in games if g.game_date.month == _MONTHS[name]])
            for name in months
        ]
    return []


def score_summary(label: str, games: list[Any]) -> str:
    if not games:
        return f"{label}: no matching games."
    pairs = [scores(game) for game in games]
    wins = sum(own > other for own, other in pairs)
    return (
        f"{label}: {wins}-{len(games) - wins} across {len(games)} games; "
        f"{sum(own for own, _ in pairs) / len(games):.1f} points per game, "
        f"{sum(other for _, other in pairs) / len(games):.1f} points allowed per game, "
        f"{sum(own - other for own, other in pairs) / len(games):+.1f} average margin."
    )
