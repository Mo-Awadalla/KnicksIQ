"""Seasons, archived dates, game numbers and month-year labels."""

from __future__ import annotations

import re
from typing import Any

from model import Atom, Session, number, tolerance
from scope import Scope
from verify_common import pair_atom, scope_for, scalar_atom


def verify_seasons(s: Session) -> None:
    seasons = {"2025-26"}
    for atom in s.atoms:
        if atom.kind != "season" or not s.free(atom):
            continue
        claimed = str(atom.values[0])
        s.mark(
            atom, claimed, "2025-26" if claimed in seasons else sorted(seasons),
            "league season", "select distinct season from games", status=(
                "verified" if claimed in seasons else "wrong"
            ),
        )


def _game_on_date(s: Session, date: str, opp: str | None) -> Any:
    games = s.oracle.by_date.get(date, [])
    if opp:
        games = [g for g in games if g.opp == opp]
    return games[0] if len(games) == 1 else None


def verify_dates(s: Session) -> None:
    for atom in s.atoms:
        if atom.kind not in {"date", "date_range", "date_no_year"} or not s.free(atom):
            continue
        scope = scope_for(s, atom.start)
        sentence = s.text[max(0, atom.start - 120):atom.end + 120].lower()
        if atom.kind == "date_no_year":
            month, day = atom.values
            year = 2025 if month >= 8 else 2026
            date = f"{year:04d}-{month:02d}-{day:02d}"
            game = _game_on_date(s, date, scope.opp) or _game_on_date(s, date, None)
            if game is not None:
                s.mark(atom, date, date, "archived game date",
                       "select game_date from games", status="verified")
            else:
                s.mark(atom, date, None, "no archived game on this date",
                       "select count(*) from games where game_date = '" + date + "'",
                       status="wrong", detail="no matching game")
        elif atom.kind == "date":
            year, month, day = atom.values
            date = f"{year:04d}-{month:02d}-{day:02d}"
            if re.search(r"most recent game|coverage ends|archive (?:ends|through)|latest game", sentence):
                expected = max(g.date for g in s.oracle.games)
                s.mark(atom, date, expected, "latest archived game date",
                       "select max(game_date) from games", status="verified" if date == expected else "wrong",
                       detail="" if date == expected else f"expected {expected}")
                continue
            game = _game_on_date(s, date, scope.opp)
            if game is None:
                game = _game_on_date(s, date, None)
            if game is not None:
                s.mark(atom, date, date, "archived game date", "select game_date from games",
                       status="verified")
            else:
                s.mark(atom, date, None, "no archived game on this date",
                       "select count(*) from games where game_date = '" + date + "'",
                       status="wrong" if scope.opp or "game" in sentence else "unverified",
                       detail="no matching game")
        else:
            start = _range_date(atom.values[:3], s)
            end = _range_date(atom.values[3:], s)
            games = s.oracle.games_for(
                season_type=scope.season_type, opp=scope.opp, loc=scope.loc,
                start=start, end=end,
            )
            games = sorted(games, key=lambda g: (g.date, g.id))
            asked = s.defaults["scope"]
            if not games:
                s.mark(atom, f"{start}..{end}", None, "date window has no games",
                       s.oracle._team_sql(scope.filters()), status="unverified")
            elif asked.start == start and asked.end == end:
                # The answer restates the window the question asked for; it is a
                # scope descriptor, not a claim that games were played on both ends.
                s.mark(atom, f"{start}..{end}", f"{start}..{end}",
                       "requested window", s.oracle._team_sql(scope.filters()),
                       status="verified", detail="window restated from the question")
            elif (start, end) == (games[0].date, games[-1].date):
                s.mark(atom, f"{start}..{end}", f"{games[0].date}..{games[-1].date}",
                       "archived date window", s.oracle._team_sql(scope.filters()),
                       status="verified")
            else:
                s.mark(atom, f"{start}..{end}", f"{games[0].date}..{games[-1].date}",
                       "date window endpoints", s.oracle._team_sql(scope.filters()),
                       status="unverified",
                       detail="window neither requested nor equal to the first and last game")


def _range_date(parts: tuple[Any, ...], s: Session) -> str:
    year, month, day = parts
    if not year:
        year = 2025 if month >= 8 else 2026
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def verify_game_numbers(s: Session) -> None:
    for atom in s.atoms:
        if atom.kind != "game_no" or not s.free(atom):
            continue
        gid = int(atom.values[0])
        game = s.oracle.by_id.get(gid)
        if game is None:
            s.mark(atom, gid, None, "no game with this id", "select id from games",
                   status="wrong", detail="game id absent")
            continue
        sentence = s.text[max(0, atom.start - 100):atom.end + 160]
        dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", sentence)
        opps = [a for a in s.oracle.team_aliases.values()]
        expected = f"game {gid} = {game.date} {game.opp}"
        ok = True
        if dates and game.date not in dates:
            ok = False
        for alias, abbr in s.oracle.team_aliases.items():
            if len(alias) < 3 or abbr == "NYK":
                continue
            if re.search(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", sentence):
                if abbr != game.opp:
                    ok = False
                break
        s.mark(atom, gid, expected, "game identity", "select id, game_date, home_team_id, "
               "away_team_id from games", status="verified" if ok else "wrong",
               detail="" if ok else expected)




def verify_month_years(s: Session) -> None:
    for m in re.finditer(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b", s.text):
        atom = scalar_atom(s, m, 2)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        year = int(m.group(2))
        scope = scope_for(s, m.start())
        month = m.group(1)
        expected = 2025 if month in {"October", "November", "December"} else 2026
        s.mark(atom, year, expected, f"{month} year", "select distinct extract(year from game_date) from games",
               status="verified" if year == expected else "wrong")


