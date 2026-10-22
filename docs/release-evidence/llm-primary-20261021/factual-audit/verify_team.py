"""Team records, totals, rates, game counts and extremes."""

from __future__ import annotations

import re
from typing import Any

from model import Session, number, tolerance
from verify_common import mark_pair, pair_atom, scope_for, scalar_atom


def verify_records(s: Session) -> None:
    seen: set[int] = set()

    def record(start: int, end: int, won: int, lost: int, scope: Scope, kind: str) -> None:
        stats = s.oracle.team_scope(**scope.filters())
        atom = s.atom_at(start, end)
        if atom is None or not s.free(atom):
            return
        seen.add(atom.index)
        mark_pair(s, atom, won, lost, stats["wins"], stats["losses"],
                  f"{kind} record {scope.filters()}", stats["sql"])

    for m in re.finditer(
        r"\b(?:went|going|record(?: was| of)?|finished)\s+(\d{1,3})\s*-\s*(\d{1,3})",
        s.text, re.I,
    ):
        scope = scope_for(s, m.start())
        record(m.start(1), m.end(2), int(m.group(1)), int(m.group(2)), scope, "team")
    for m in re.finditer(r"record[^.\n]{0,55}?(\d{1,3})\s*-\s*(\d{1,3})", s.text, re.I):
        scope = scope_for(s, m.start())
        record(m.start(1), m.end(2), int(m.group(1)), int(m.group(2)), scope, "team")
    for m in re.finditer(r"\((\d{1,3})\s*-\s*(\d{1,3})\s+(?:home|road|away)?\s*record\)", s.text, re.I):
        scope = scope_for(s, m.start())
        record(m.start(1), m.end(2), int(m.group(1)), int(m.group(2)), scope, "split")
    for m in re.finditer(r"\b(\d{1,3})\s*-\s*(\d{1,3})\s+(?:in the )?(regular season|playoffs)\b", s.text, re.I):
        scope = scope_for(s, m.start())
        if m.group(3).lower().startswith("regular"):
            scope.season_type = "regular"
        else:
            scope.season_type = "playoffs"
        record(m.start(1), m.end(2), int(m.group(1)), int(m.group(2)), scope, "phase")
    # "X wins and Y losses over N games" / "X wins and Y losses"
    for m in re.finditer(r"\b(\d{1,3})\s+wins?(?:\s+and|\s*,\s*)\s*(\d{1,3})\s+losses?", s.text, re.I):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected, fact in (
            (1, stats["wins"], "wins"), (2, stats["losses"], "losses"),
        ):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, int(m.group(group)), expected, f"{fact} {scope.filters()}", stats["sql"])
    # "N wins" and "N losses" without the other noun close by.
    for m in re.finditer(r"\b(\d{1,3})\s+(?:regular-season |regular season |archived )?(wins|losses)\b", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom):
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        expected = stats["wins"] if m.group(2).lower() == "wins" else stats["losses"]
        s.mark(atom, int(m.group(1)), expected, f"{m.group(2).lower()} {scope.filters()}", stats["sql"])
    # "won W of their N games (and lost L)".
    for m in re.finditer(
        r"\bwon\s+(\d{1,3})\s+of\s+(?:their\s+)?(\d{1,3})\s+"
        r"(?:(?:archived\s+|regular-season\s+)?(home|road|away)\s+)?(?:archived\s+)?games?"
        r"(?:\s+in\s+(\w+)(?:\s+(\d{4}))?)?(?:\s*\(and\s+lost\s+(\d{1,3})\))?",
        s.text, re.I,
    ):
        scope = scope_for(s, m.start())
        if m.group(3):
            scope.loc = "home" if m.group(3).lower() == "home" else "away"
        if m.group(4):
            month = m.group(4).lower()
            if month.startswith("dec"):
                scope.start, scope.end = "2025-12-01", "2025-12-31"
            elif month.startswith("jan"):
                scope.start, scope.end = "2026-01-01", "2026-01-31"
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected, fact in (
            (1, stats["wins"], "wins"), (2, stats["games"], "games"),
            (6, stats["losses"], "losses"),
        ):
            if not m.group(group):
                continue
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, int(m.group(group)), expected, f"{fact} {scope.filters()}", stats["sql"])
    # "won 3 of 4" without the word games.
    for m in re.finditer(r"\bwon\s+(\d{1,3})\s+of\s+(\d{1,3})\b", s.text, re.I):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected, fact in ((1, stats["wins"], "wins"), (2, stats["games"], "games")):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom) and atom.kind == "number":
                s.mark(atom, int(m.group(group)), expected, f"{fact} {scope.filters()}", stats["sql"])




def verify_record_lines(s: Session) -> None:
    for m in re.finditer(r"\b(wins|losses):\s*(\d{1,3})\s+over\s+(\d{1,3})\s+archived games", s.text, re.I):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        expected = stats["wins"] if m.group(1).lower() == "wins" else stats["losses"]
        for group, exp, fact in ((2, expected, m.group(1).lower()), (3, stats["games"], "games")):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom) and atom.kind == "number":
                s.mark(atom, int(m.group(group)), exp, f"{fact} {scope.filters()}", stats["sql"])
    for m in re.finditer(r"\blosing\s+(\d{1,3})\b", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        s.mark(atom, int(m.group(1)), stats["losses"], f"losses {scope.filters()}", stats["sql"])


def verify_points_lines(s: Session) -> None:
    for m in re.finditer(r"points:\s*([\d,]+)\s+over\s+(\d{1,3})\s+archived games", s.text, re.I):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected, fact in (("1", stats["points"], "team points"), ("2", stats["games"], "games")):
            atom = scalar_atom(s, m, int(group))
            if atom and s.free(atom) and atom.kind == "number":
                s.mark(atom, number(m.group(int(group))), expected, f"{fact} {scope.filters()}", stats["sql"])
    for m in re.finditer(r"\b(?:lost|win|won)\s+(\d{1,3})\s+games?\b", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        expected = stats["losses"] if m.group(0).lower().startswith("lost") else stats["wins"]
        s.mark(atom, int(m.group(1)), expected, f"games {scope.filters()}", stats["sql"])


def verify_games_counts(s: Session) -> None:
    patterns = [
        r"\bacross\s+(\d{1,3})\s+(?:archived\s+)?games\b",
        r"\bover\s+(\d{1,3})\s+(?:archived\s+)?games\b",
        r"\b(\d{1,3})\s+archived\s+games\b",
        r"\b(\d{1,3})\s+(?:regular-season|regular season|archived)\s+games\b",
        r"\bacross\s+(\d{1,3})\s+games\b",
        r"\b(\d{1,3})\s+games\b",
        r"\b(\d{1,3})\s+(?:home|road|away) games\b",
        r"\bacross\s+(\d{1,3})\s+(?:home|road|away|archived\s+)*games\b",
        r"\b(\d{1,3})\s+Knicks games\b",
        r"\b(\d{1,3})\s+of\s+(\d{1,3})\s+games\b",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, s.text, re.I):
            group = 2 if m.lastindex and m.lastindex == 2 and m.group(1) == m.group(2) else 1
            if m.lastindex == 2 and pattern.startswith(r"\b(\d{1,3})\s+of"):
                group = 2
            atom = scalar_atom(s, m, group)
            if atom is None or not s.free(atom):
                continue
            prefix = s.text[max(0, m.start() - 18):m.start()].lower()
            if re.search(r"\b(?:won|lost|win|loss)\s+$", prefix):
                continue
            scope = scope_for(s, m.start())
            matched = m.group(0).lower()
            if "regular-season" in matched or "regular season" in matched:
                scope.season_type = "regular"
            elif "playoff" in matched:
                scope.season_type = "playoffs"
            stats = s.oracle.team_scope(**scope.filters())
            s.mark(atom, int(m.group(group)), stats["games"], f"game count {scope.filters()}", stats["sql"])


def verify_team_rates(s: Session) -> None:
    # totals
    for m in re.finditer(r"(?:scored|scoring)\s+([\d,]+)\s+(?:total\s+)?points", s.text, re.I):
        _team_total(s, m, 1)
    for m in re.finditer(r"([\d,]+)\s+total points", s.text, re.I):
        _team_total(s, m, 1)
    # average points
    for m in re.finditer(r"(?:averaged|averaging)\s+([+-]?\d+(?:\.\d+)?)\s+points?(?:\s+per\s+(?:game|appearance))?", s.text, re.I):
        _team_rate(s, m, 1, "avg_points", "points per game")
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s+points per game", s.text, re.I):
        _team_rate(s, m, 1, "avg_points", "points per game")
    # margin
    for m in re.finditer(r"average margin (?:was|of)\s+([+-]?\d+(?:\.\d+)?)", s.text, re.I):
        _team_rate(s, m, 1, "avg_margin", "average margin")
    for m in re.finditer(r"home margin of\s+([+-]?\d+(?:\.\d+)?)\s+per game compared with\s+([+-]?\d+(?:\.\d+)?)\s+on the road", s.text, re.I):
        for group, loc in ((1, "home"), (2, "away")):
            scope = scope_for(s, m.start())
            scope.loc = loc
            stats = s.oracle.team_scope(**scope.filters())
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, number(m.group(group)), stats["avg_margin"], f"margin per game {loc} {scope.filters()}", stats["sql"])
    for m in re.finditer(r"margin per game:\s*([+-]?\d+(?:\.\d+)?)", s.text, re.I):
        _team_rate(s, m, 1, "avg_margin", "average margin")
    for m in re.finditer(r"margin of\s+([+-]?\d+(?:\.\d+)?)(?:\s+points)?(?:\s+per game)?", s.text, re.I):
        _team_rate(s, m, 1, "avg_margin", "margin per game")
    for m in re.finditer(r"with an?\s+([+-]?\d+(?:\.\d+)?)\s+cumulative margin", s.text, re.I):
        _team_rate(s, m, 1, "margin", "cumulative margin")
    for m in re.finditer(r"(?:with|and) an?\s+([+-]?\d+(?:\.\d+)?)\s+(?:average\s+)?margin", s.text, re.I):
        _team_rate(s, m, 1, "avg_margin", "average margin")
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s+(?:average\s+)?margin per game", s.text, re.I):
        _team_rate(s, m, 1, "avg_margin", "average margin")
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s+average margin", s.text, re.I):
        _team_rate(s, m, 1, "avg_margin", "average margin")
    # "119.00 for, 108.97 against" and "allowed 108.97 at home versus 111.21 on the road"
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s+for,\s*([+-]?\d+(?:\.\d+)?)\s+against", s.text, re.I):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected in ((1, stats["avg_points"]), (2, stats["opp_points"] / stats["games"] if stats["games"] else None)):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, number(m.group(group)), expected, "points for/against per game", stats["sql"])
    for m in re.finditer(r"allowed\s+([+-]?\d+(?:\.\d+)?)\s+at home(?:\s+versus\s+([+-]?\d+(?:\.\d+)?)\s+on the road)?", s.text, re.I):
        for group, loc in ((1, "home"), (2, "away")):
            if not m.group(group):
                continue
            scope = scope_for(s, m.start())
            scope.loc = loc
            stats = s.oracle.team_scope(**scope.filters())
            expected = stats["opp_points"] / stats["games"] if stats["games"] else None
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, number(m.group(group)), expected, f"opponent points per game {loc}", stats["sql"])


def _team_total(s: Session, m: re.Match, group: int) -> None:
    atom = scalar_atom(s, m, group)
    if atom is None or not s.free(atom):
        return
    scope = scope_for(s, m.start())
    stats = s.oracle.team_scope(**scope.filters())
    s.mark(atom, number(m.group(group)), stats["points"], f"team points {scope.filters()}", stats["sql"])


def _team_rate(s: Session, m: re.Match, group: int, key: str, fact: str) -> None:
    atom = scalar_atom(s, m, group)
    if atom is None or not s.free(atom):
        return
    local = s.text[max(0, m.start() - 80):m.end() + 40].lower()
    if "appearance" in local:
        return
    # cumulative margins are totals, not per-game rates
    if "margin" in fact and re.search(r"cumulative|total points", local) and "average" not in local:
        key, fact = "margin", "cumulative margin"
    if key == "avg_points" and re.search(
        r"(?:average\s+)?margin\s+(?:was|of)\s*$",
        s.text[max(0, m.start(group) - 30):m.start(group)],
    ):
        key, fact = "avg_margin", "average margin"
    scope = scope_for(s, m.start())
    local = s.text[max(0, m.start() - 120):m.end() + 40].lower()
    if "regular" in local and "playoff" in local and re.search(r"averag", local):
        scope.season_type = None
    stats = s.oracle.team_scope(**scope.filters())
    expected = stats[key]
    s.mark(atom, number(m.group(group)), expected, f"{fact} {scope.filters()}", stats["sql"])


def verify_extremes(s: Session) -> None:
    regular = [g for g in s.oracle.games if g.season_type == "regular"]
    best = max(regular, key=lambda g: g.margin)
    worst = min(regular, key=lambda g: g.margin)
    high = max(regular, key=lambda g: g.nyk_score)
    for m in re.finditer(
        r"biggest win by margin[^.\n]{0,60}?(\d+)[- ]point(?: victory)?[,:]?\s*(\d+)\s*-\s*(\d+)",
        s.text, re.I,
    ):
        for group, expected, fact in ((1, best.margin, "win margin"), (2, best.nyk_score, "winner score"), (3, best.opp_score, "loser score")):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, int(m.group(group)), expected, f"biggest regular-season win {best.date}", "select ... order by (home_score-away_score) desc")
    for m in re.finditer(
        r"worst[^.\n]{0,60}?loss[^.\n]{0,60}?(\d+)[- ]point(?: defeat)?[,:]?\s*(\d+)\s*-\s*(\d+)",
        s.text, re.I,
    ):
        for group, expected in ((1, abs(worst.margin)), (2, worst.nyk_score), (3, worst.opp_score)):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, int(m.group(group)), expected, f"worst regular-season loss {worst.date}", "select ... order by (home_score-away_score) asc")
    for m in re.finditer(
        r"highest-scoring game[^.\n]{0,80}?(?:was\s+(\d+)\s+points,\s+)?(?:a\s+)?(\d+)\s*-\s*(\d+)\s+win",
        s.text, re.I,
    ):
        for group, expected in ((1, high.nyk_score), (2, high.nyk_score), (3, high.opp_score)):
            if not m.group(group):
                continue
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, int(m.group(group)), expected, f"highest-scoring regular-season game {high.date}", "select ... order by points desc")
