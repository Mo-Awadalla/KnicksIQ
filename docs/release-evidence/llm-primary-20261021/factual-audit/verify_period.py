"""Quarter and period aggregate verification from period_scores and events."""

from __future__ import annotations

import re
from dataclasses import replace

from model import Session, number
from verify_common import scope_for, scalar_atom


def period_stats(s: Session, scope, period: int) -> dict:
    games = s.oracle.games_for(
        season_type=scope.season_type, opp=scope.opp, loc=scope.loc,
        start=scope.start, end=scope.end, last_n=scope.last_n,
        first_n=scope.first_n, result=scope.result,
    )
    games = [g for g in games if period in g.periods]
    count = len(games)
    nyk = sum(g.periods[period].get("NYK", 0) for g in games)
    opp = sum(g.periods[period].get(g.opp, 0) for g in games)
    sql = (
        "select p.period, sum(p.points) filter (where p.team_id='NYK') nyk, "
        "sum(p.points) filter (where p.team_id<>'NYK') opp, count(distinct p.game_id) games "
        "from period_scores p join games g on g.id=p.game_id "
        "where 'NYK' in (g.home_team_id,g.away_team_id) and p.period=" + str(period)
    )
    return {
        "games": count, "nyk": nyk, "opp": opp, "diff": nyk - opp,
        "avg": nyk / count if count else None,
        "avg_opp": opp / count if count else None,
        "avg_diff": (nyk - opp) / count if count else None,
        "sql": sql,
    }


def _mark(s: Session, m: re.Match, group: str, expected, fact: str, sql: str, scope) -> None:
    index = int(group)
    atom = scalar_atom(s, m, index)
    if atom is None or not s.free(atom) or atom.kind != "number":
        return
    s.mark(atom, number(m.group(index)), expected, fact, sql)


def verify_periods(s: Session) -> None:
    text = s.text
    for m in re.finditer(
        r"([\d,]+)\s+points in Q3\s*\(([+\-]?[\d.]+) per game\)\s+versus\s+"
        r"([\d,]+) in Q4\s*\(([+\-]?[\d.]+) per game\),?\s*a difference of\s+([+\-]?[\d,]+)\s+total points"
        r"\s*\(([+\-]?[\d.]+) per game\)",
        text, re.I,
    ):
        scope = scope_for(s, m.start())
        q3 = period_stats(s, scope, 3)
        q4 = period_stats(s, scope, 4)
        for group, expected, fact, stats in (
            ("1", q3["nyk"], "Q3 points", q3), ("2", q3["avg"], "Q3 points per game", q3),
            ("3", q4["nyk"], "Q4 points", q4), ("4", q4["avg"], "Q4 points per game", q4),
            ("5", q3["nyk"] - q4["nyk"], "Q3 minus Q4 points", q3),
            ("6", (q3["nyk"] - q4["nyk"]) / q3["games"] if q3["games"] else None,
             "Q3 minus Q4 per game", q3),
        ):
            _mark(s, m, group, expected, f"{fact} {scope.filters()}", stats["sql"], scope)
    for m in re.finditer(
        r"allowed\s+([\d,]+)\s+points in Q3\s*\(([+\-]?[\d.]+) per game\)\s+but only\s+"
        r"([\d,]+) in Q4\s*\(([+\-]?[\d.]+) per game\),?\s*giving a\s+"
        r"Q3 point differential of\s+([+\-]?[\d,]+)\s+and a\s+Q4 differential of\s+([+\-]?[\d,]+)",
        text, re.I,
    ):
        scope = scope_for(s, m.start())
        q3 = period_stats(s, scope, 3)
        q4 = period_stats(s, scope, 4)
        for group, expected, fact, stats in (
            ("1", q3["opp"], "Q3 points allowed", q3), ("2", q3["avg_opp"], "Q3 allowed per game", q3),
            ("3", q4["opp"], "Q4 points allowed", q4), ("4", q4["avg_opp"], "Q4 allowed per game", q4),
            ("5", q3["diff"], "Q3 differential", q3), ("6", q4["diff"], "Q4 differential", q4),
        ):
            _mark(s, m, group, expected, f"{fact} {scope.filters()}", stats["sql"], scope)
    for m in re.finditer(r"Q3 point differential of\s+([+\-]?\d+)\s+and a\s+Q4 differential of\s+([+\-]?\d+)", text, re.I):
        scope = scope_for(s, m.start())
        for group, period in (("1", 3), ("2", 4)):
            stats = period_stats(s, scope, period)
            _mark(s, m, group, stats["diff"], f"Q{period} differential {scope.filters()}", stats["sql"], scope)
    for m in re.finditer(r"(\d+)\s+of\s+(\d+)\s+games", text, re.I):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected in (("1", stats["games"]), ("2", stats["games"])):
            _mark(s, m, group, expected, f"games {scope.filters()}", stats["sql"], scope)
    # "Phases: 3 reg, 6 playoffs" / "(3 regular season, 6 playoffs)".
    for m in re.finditer(
        r"(?:Phases?:\s*)?\(?(?<![\d-])(\d{1,3})\s+(?:reg(?:ular season)?|regular-season)"
        r"[,;]?\s+(?<![\d-])(\d{1,3})\s+playoffs?",
        text, re.I,
    ):
        scope = scope_for(s, m.start())
        for group, phase in ((1, "regular"), (2, "playoffs")):
            local = replace(scope, season_type=phase)
            stats = s.oracle.team_scope(**local.filters())
            atom = scalar_atom(s, m, group)
            if atom is None or not s.free(atom) or atom.kind != "number":
                continue
            s.mark(atom, int(m.group(group)), stats["games"],
                   f"{phase} games {local.filters()}", stats["sql"])
    for m in re.finditer(r"\(?\s*(\d+)\s+games,\s+(\d+)\s+Q4 scoring plays\s*\)?", text, re.I):
        scope = scope_for(s, m.start())
        games = s.oracle.games_for(
            season_type=scope.season_type, opp=scope.opp, loc=scope.loc,
            start=scope.start, end=scope.end,
        )
        plays = sum(1 for g in games for p in s.oracle.plays[g.id] if p.period == 4)
        sql = (
            "select count(*) from game_events e join games g on g.id=e.game_id "
            "where g.away_team_id='" + str(scope.opp) + "' or g.home_team_id='" + str(scope.opp) + "' "
            "and e.period=4"
        )
        _mark(s, m, "1", len(games), f"games {scope.filters()}", s.oracle._team_sql(scope.filters()), scope)
        _mark(s, m, "2", plays, "Q4 scoring plays", sql, scope)
