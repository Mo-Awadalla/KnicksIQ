"""Raw-table oracle for the replacement factual audit.

Loads only raw restore tables through psql, then recomputes games, period sums,
player lines and play-by-play timelines in this process. No application
calculation module is imported.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

PSQL = os.environ.get(
    "KIQ_PSQL", "docker exec kiq-integrate-postgres-1 psql -U knicksiq -d knicksiq"
)

SCORING = {"made_shot", "free_throw"}


def query(sql: str) -> Any:
    proc = subprocess.run(PSQL.split() + ["-At", "-c", sql], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    out = proc.stdout.strip()
    return json.loads(out) if out else None


@dataclass
class Game:
    id: int
    date: str
    season_type: str
    home: str
    away: str
    home_score: int
    away_score: int
    nyk_score: int = 0
    opp_score: int = 0
    opp: str = ""
    loc: str = ""
    win: bool = False
    periods: dict[int, dict[str, int]] = field(default_factory=dict)

    @property
    def margin(self) -> int:
        return self.nyk_score - self.opp_score

    @property
    def score_text(self) -> str:
        return f"{self.nyk_score}-{self.opp_score}"


@dataclass
class Play:
    sequence: int
    period: int
    clock: str
    team: str
    points: int
    nyk_before: int
    opp_before: int
    nyk_after: int
    opp_after: int

    @property
    def margin_before(self) -> int:
        return self.nyk_before - self.opp_before

    @property
    def margin_after(self) -> int:
        return self.nyk_after - self.opp_after


def clock_seconds(clock: str) -> int:
    try:
        minutes, seconds = clock.split(":")
        return int(minutes) * 60 + int(seconds)
    except (AttributeError, ValueError):
        return 0


class Oracle:
    def __init__(self) -> None:
        teams = query(
            "select json_agg(x) from (select id, name, city, abbreviation "
            "from teams order by id) x"
        )
        self.teams = {row["id"]: row for row in teams or []}
        self.team_aliases = self._aliases(self.teams)
        players = query("select json_agg(x) from (select id, full_name from players order by id) x")
        self.player_names = [row["full_name"] for row in players or []]
        self._load_games()
        self._load_periods()
        self._load_stats()
        self._load_events()

    @staticmethod
    def _aliases(teams: dict[str, dict]) -> dict[str, str]:
        aliases = {"NYK": "NYK", "New York": "NYK", "Knicks": "NYK"}
        nicknames = {
            "ATL": ["Hawks", "Atlanta"],
            "BKN": ["Nets", "Brooklyn"],
            "BOS": ["Celtics", "Boston", "Celts", "C's"],
            "CHA": ["Hornets", "Charlotte"],
            "CHI": ["Bulls", "Chicago"],
            "CLE": ["Cavaliers", "Cleveland", "Cavs"],
            "DAL": ["Mavericks", "Dallas", "Mavs"],
            "DEN": ["Nuggets", "Denver"],
            "DET": ["Pistons", "Detroit"],
            "GSW": ["Warriors", "Golden State"],
            "HOU": ["Rockets", "Houston"],
            "IND": ["Pacers", "Indiana"],
            "LAC": ["Clippers"],
            "LAL": ["Lakers", "Los Angeles Lakers"],
            "MEM": ["Grizzlies", "Memphis"],
            "MIA": ["Heat", "Miami"],
            "MIL": ["Bucks", "Milwaukee"],
            "MIN": ["Timberwolves", "Minnesota"],
            "NOP": ["Pelicans", "New Orleans"],
            "OKC": ["Thunder", "Oklahoma City"],
            "ORL": ["Magic", "Orlando"],
            "PHI": ["76ers", "Philadelphia", "Sixers"],
            "PHX": ["Suns", "Phoenix"],
            "POR": ["Trail Blazers", "Portland"],
            "SAC": ["Kings", "Sacramento"],
            "SAS": ["Spurs", "San Antonio"],
            "TOR": ["Raptors", "Toronto", "Raps"],
            "UTA": ["Jazz", "Utah"],
            "WAS": ["Wizards", "Washington"],
        }
        for abbr, rows in teams.items():
            aliases[abbr] = abbr
            aliases[rows["name"]] = abbr
            aliases[rows["city"]] = abbr
        for abbr, names in nicknames.items():
            for name in names:
                aliases[name] = abbr
        return aliases

    def _load_games(self) -> None:
        rows = query(
            "select json_agg(x) from (select g.id, g.game_date::text as game_date, "
            "g.season_type::text as season_type, g.home_team_id, g.away_team_id, "
            "g.home_score, g.away_score from games g "
            "where 'NYK' in (g.home_team_id, g.away_team_id) order by g.id) x"
        )
        self.games: list[Game] = []
        for r in rows or []:
            nyk_home = r["home_team_id"] == "NYK"
            g = Game(
                id=r["id"],
                date=r["game_date"],
                season_type=r["season_type"],
                home=r["home_team_id"],
                away=r["away_team_id"],
                home_score=r["home_score"],
                away_score=r["away_score"],
            )
            g.nyk_score = g.home_score if nyk_home else g.away_score
            g.opp_score = g.away_score if nyk_home else g.home_score
            g.opp = g.away if nyk_home else g.home
            g.loc = "home" if nyk_home else "away"
            g.win = g.nyk_score > g.opp_score
            g.periods = {}
            self.games.append(g)
        self.by_id = {g.id: g for g in self.games}
        self.by_date: dict[str, list[Game]] = {}
        for g in self.games:
            self.by_date.setdefault(g.date, []).append(g)
        self.asb_start = self._asb_start()

    def _asb_start(self) -> str | None:
        """First regular-season game after the archive's longest mid-season gap.

        The archive is a regular season plus playoffs, so the only multi-day
        break in the regular-season calendar is the All-Star break.
        """
        from datetime import date as _date

        regular = sorted({g.date for g in self.games if g.season_type == "regular"})
        best_gap, best_date = 0, None
        for before, after in zip(regular, regular[1:]):
            gap = (_date.fromisoformat(after) - _date.fromisoformat(before)).days
            if gap > best_gap:
                best_gap, best_date = gap, after
        return best_date

    def _load_periods(self) -> None:
        rows = query(
            "select json_agg(x) from (select game_id, period, team_id, points "
            "from period_scores order by game_id, period, team_id) x"
        )
        for r in rows or []:
            game = self.by_id.get(r["game_id"])
            if game is not None:
                game.periods.setdefault(r["period"], {})[r["team_id"]] = r["points"]

    def _load_stats(self) -> None:
        rows = query(
            "select json_agg(x) from (select s.game_id, p.full_name, s.team_id, "
            "s.minutes, s.points, s.rebounds, s.assists, s.turnovers, s.steals, "
            "s.blocks, s.field_goals_made, s.field_goals_attempted, "
            "s.three_pointers_made, s.three_pointers_attempted, s.free_throws_made, "
            "s.free_throws_attempted, s.plus_minus from player_game_stats s "
            "join players p on p.id=s.player_id) x"
        )
        self.stats = rows or []
        for row in self.stats:
            row["game"] = self.by_id.get(row["game_id"])

    def _load_events(self) -> None:
        rows = query(
            "select json_agg(x) from (select game_id, sequence, period, clock, "
            "team_id, event_type::text as event_type, shot_type::text as shot_type, "
            "shot_result::text as shot_result, home_score, away_score "
            "from game_events order by game_id, sequence) x"
        )
        by_game: dict[int, list[dict]] = {}
        for row in rows or []:
            by_game.setdefault(row["game_id"], []).append(row)
        self.plays: dict[int, list[Play]] = {}
        for game in self.games:
            self.plays[game.id] = self._build_plays(game, by_game.get(game.id, []))

    @staticmethod
    def _build_plays(game: Game, events: list[dict]) -> list[Play]:
        previous = (0, 0)
        plays: list[Play] = []
        for event in events:
            current = (event["home_score"], event["away_score"])
            if current == (0, 0):
                current = previous
            home_delta = current[0] - previous[0]
            away_delta = current[1] - previous[1]
            if event["event_type"] not in SCORING:
                previous = current
                continue
            if home_delta > 0 and away_delta <= 0:
                team, points = game.home, home_delta
            elif away_delta > 0 and home_delta <= 0:
                team, points = game.away, away_delta
            elif home_delta > 0 and away_delta > 0:
                team = event["team_id"] or game.home
                points = max(home_delta, away_delta)
            else:
                previous = current
                continue
            if points <= 0:
                previous = current
                continue
            nyk_home = game.home == "NYK"
            home_before, away_before = previous
            nyk_before = home_before if nyk_home else away_before
            opp_before = away_before if nyk_home else home_before
            nyk_after = current[0] if nyk_home else current[1]
            opp_after = current[1] if nyk_home else current[0]
            plays.append(
                Play(
                    sequence=event["sequence"],
                    period=event["period"],
                    clock=event["clock"],
                    team=team,
                    points=points,
                    nyk_before=nyk_before,
                    opp_before=opp_before,
                    nyk_after=nyk_after,
                    opp_after=opp_after,
                )
            )
            previous = current
        return plays

    # -- scope resolution -------------------------------------------------

    def games_for(
        self,
        *,
        season_type: str | None = None,
        opp: str | None = None,
        loc: str | None = None,
        start: str | None = None,
        end: str | None = None,
        last_n: int | None = None,
        first_n: int | None = None,
        result: str | None = None,
        game_ids: list[int] | None = None,
    ) -> list[Game]:
        rows = self.games
        if game_ids is not None:
            wanted = set(game_ids)
            rows = [g for g in rows if g.id in wanted]
        if season_type and season_type != "all":
            rows = [g for g in rows if g.season_type == season_type]
        if opp:
            rows = [g for g in rows if g.opp == opp]
        if loc:
            rows = [g for g in rows if g.loc == loc]
        if start:
            rows = [g for g in rows if g.date >= start]
        if end:
            rows = [g for g in rows if g.date <= end]
        if result == "W":
            rows = [g for g in rows if g.win]
        elif result == "L":
            rows = [g for g in rows if not g.win]
        rows = sorted(rows, key=lambda g: (g.date, g.id))
        if last_n is not None:
            rows = rows[-last_n:]
        if first_n is not None:
            rows = rows[:first_n]
        return rows

    def team_scope(self, **filters: Any) -> dict[str, Any]:
        games = self.games_for(**filters)
        count = len(games)
        wins = sum(1 for g in games if g.win)
        points = sum(g.nyk_score for g in games)
        opp_points = sum(g.opp_score for g in games)
        margin = points - opp_points
        return {
            "games": count,
            "wins": wins,
            "losses": count - wins,
            "points": points,
            "opp_points": opp_points,
            "margin": margin,
            "avg_points": (points / count) if count else None,
            "avg_opp": (opp_points / count) if count else None,
            "avg_margin": (margin / count) if count else None,
            "rows": [
                {"id": g.id, "date": g.date, "opp": g.opp, "loc": g.loc,
                 "score": g.score_text, "win": g.win}
                for g in games
            ],
            "sql": self._team_sql(filters),
        }

    @staticmethod
    def _team_sql(filters: dict[str, Any]) -> str:
        clauses = ["'NYK' in (home_team_id, away_team_id)"]
        if filters.get("game_ids") is not None:
            ids = ",".join(str(i) for i in filters["game_ids"])
            clauses.append(f"id in ({ids})")
        if filters.get("season_type") and filters["season_type"] != "all":
            clauses.append(f"season_type = '{filters['season_type']}'")
        if filters.get("opp"):
            clauses.append(
                f"((home_team_id='NYK' and away_team_id='{filters['opp']}') or "
                f"(away_team_id='NYK' and home_team_id='{filters['opp']}'))"
            )
        if filters.get("loc") == "home":
            clauses.append("home_team_id='NYK'")
        elif filters.get("loc") == "away":
            clauses.append("away_team_id='NYK'")
        if filters.get("start"):
            clauses.append(f"game_date >= '{filters['start']}'")
        if filters.get("end"):
            clauses.append(f"game_date <= '{filters['end']}'")
        if filters.get("result") == "W":
            clauses.append(
                "(home_team_id='NYK' and home_score>away_score) or "
                "(away_team_id='NYK' and away_score>home_score)"
            )
        elif filters.get("result") == "L":
            clauses.append(
                "(home_team_id='NYK' and home_score<away_score) or "
                "(away_team_id='NYK' and away_score<home_score)"
            )
        where = " and ".join(f"({c})" for c in clauses)
        order = "game_date"
        tail = ""
        if filters.get("last_n") is not None:
            order = "game_date desc"
            tail = f" limit {filters['last_n']}"
        elif filters.get("first_n") is not None:
            order = "game_date asc"
            tail = f" limit {filters['first_n']}"
        return (
            "select id, game_date, season_type, home_team_id, away_team_id, "
            "home_score, away_score from games where " + where
            + f" order by {order}{tail}"
        )

    def player_rows(self, player: str, **filters: Any) -> list[dict[str, Any]]:
        rows = [
            r for r in self.stats
            if r["full_name"] == player and r["game"] is not None and r["team_id"] == "NYK"
        ]
        games = {g.id: g for g in self.games_for(**filters)}
        rows = [r for r in rows if r["game_id"] in games]
        return sorted(rows, key=lambda r: (r["game"].date, r["game_id"]))

    def player_scope(self, player: str, appearances: bool = True, **filters: Any) -> dict[str, Any]:
        rows = self.player_rows(player, **filters)
        if appearances:
            rows = [r for r in rows if (r["minutes"] or 0) > 0]
        count = len(rows)
        points = sum(r["points"] for r in rows)
        rebounds = sum(r["rebounds"] for r in rows)
        assists = sum(r["assists"] for r in rows)
        turnovers = sum(r["turnovers"] for r in rows)
        return {
            "appearances": count,
            "points": points,
            "rebounds": rebounds,
            "assists": assists,
            "turnovers": turnovers,
            "avg_points": points / count if count else None,
            "avg_rebounds": rebounds / count if count else None,
            "avg_assists": assists / count if count else None,
            "avg_turnovers": turnovers / count if count else None,
            "rows": [
                {"date": r["game"].date, "opp": r["game"].opp, "game_id": r["game_id"],
                 "points": r["points"], "rebounds": r["rebounds"],
                 "assists": r["assists"], "turnovers": r["turnovers"]}
                for r in rows
            ],
            "sql": self._player_sql(player, appearances, filters),
        }

    @staticmethod
    def _player_sql(player: str, appearances: bool, filters: dict[str, Any]) -> str:
        sql = (
            "select g.game_date, g.id, s.points, s.rebounds, s.assists, s.turnovers "
            "from player_game_stats s join players p on p.id=s.player_id "
            "join games g on g.id=s.game_id where s.team_id='NYK' "
            f"and p.full_name='{player}'"
        )
        if appearances:
            sql += " and s.minutes > 0"
        if filters.get("season_type") and filters["season_type"] != "all":
            sql += f" and g.season_type='{filters['season_type']}'"
        if filters.get("opp"):
            sql += (
                " and ((g.home_team_id='NYK' and g.away_team_id="
                f"'{filters['opp']}') or (g.away_team_id='NYK' and "
                f"g.home_team_id='{filters['opp']}'))"
            )
        if filters.get("start"):
            sql += f" and g.game_date >= '{filters['start']}'"
        if filters.get("end"):
            sql += f" and g.game_date <= '{filters['end']}'"
        sql += " order by g.game_date"
        return sql


def oracle() -> Oracle:
    return Oracle()
