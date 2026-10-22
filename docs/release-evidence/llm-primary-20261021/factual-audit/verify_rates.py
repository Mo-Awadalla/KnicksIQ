"""Team totals, per-game rates, margins and single-game extremes."""

from __future__ import annotations

import re

from model import Session, number
from verify_common import claim_number, scope_for, scalar_atom


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
                s.mark(atom, claim_number(s, m, group), expected, "points for/against per game", stats["sql"])
    # "averaged 113.26 points for and 106.59 against"
    for m in re.finditer(
        r"([+-]?\d+(?:\.\d+)?)\s+points? for and\s+([+-]?\d+(?:\.\d+)?)\s+against", s.text, re.I,
    ):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected in ((1, stats["avg_points"]), (2, stats["opp_points"] / stats["games"] if stats["games"] else None)):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, claim_number(s, m, group), expected, "points for/against per game", stats["sql"])
    # "scoring 121.8 and allowing 112.7"
    for m in re.finditer(r"scoring\s+([+-]?\d+(?:\.\d+)?)\s+and allowing\s+([+-]?\d+(?:\.\d+)?)", s.text, re.I):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected, fact in (
            (1, stats["avg_points"], "points per game"),
            (2, stats["opp_points"] / stats["games"] if stats["games"] else None, "opponent points per game"),
        ):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom):
                s.mark(atom, claim_number(s, m, group), expected, fact, stats["sql"])
    # "112.7 allowed" after an average.
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s+allowed\b", s.text, re.I):
        before = s.text[max(0, m.start() - 60):m.start()].lower()
        if "averag" not in before and "scored" not in before:
            continue
        _team_rate(s, m, 1, "avg_opp", "opponent points per game")
    # "a +6.67 per-game margin".
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s+per-game margin", s.text, re.I):
        _team_rate(s, m, 1, "avg_margin", "average margin")
    # "a plus-519 point differential" and "with a +44 cumulative point differential".
    for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s+(?:cumulative\s+)?point differential", s.text, re.I):
        _team_rate(s, m, 1, "margin", "cumulative point differential")
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
    # "average margin was about +6.33 points per game": the word margin wins.
    clause = re.split(r"[;.]", s.text[max(0, m.start() - 70):m.start()])[-1].lower()
    if key == "avg_points" and re.search(r"\bmargin\b", clause):
        key, fact = "avg_margin", "average margin"
    scope = scope_for(s, m.start())
    local = s.text[max(0, m.start() - 120):m.end() + 40].lower()
    if "regular" in local and "playoff" in local and re.search(r"averag", local):
        scope.season_type = None
    stats = s.oracle.team_scope(**scope.filters())
    expected = stats[key]
    s.mark(atom, claim_number(s, m, group), expected, f"{fact} {scope.filters()}", stats["sql"])

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
    # "biggest win by margin was 54 points: 120-66 vs BKN on 2026-01-21"
    for m in re.finditer(r"biggest win by margin was\s+(\d{1,3})\s+points?", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom and s.free(atom):
            s.mark(atom, int(m.group(1)), best.margin,
                   f"biggest regular-season win {best.date} vs {best.opp}",
                   "select ... order by (home_score-away_score) desc")
    for m in re.finditer(r"worst loss by margin was\s+(\d{1,3})\s+points?", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom and s.free(atom):
            s.mark(atom, int(m.group(1)), abs(worst.margin),
                   f"worst regular-season loss {worst.date} vs {worst.opp}",
                   "select ... order by (home_score-away_score) asc")
    # "a 54-point margin" in one game.
    for m in re.finditer(r"\b(\d{1,3})-point margin\b", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom):
            continue
        scope = scope_for(s, m.start())
        games = s.oracle.games_for(**scope.filters())
        if len(games) == 1:
            game = games[0]
            s.mark(atom, int(m.group(1)), abs(game.margin),
                   f"margin {game.date} vs {game.opp}",
                   "select home_score, away_score from games where id=" + str(game.id))
