"""Team records, totals, rates, game counts and extremes."""

from __future__ import annotations

import re

from model import Session, number
from verify_common import mark_pair, scope_for, scalar_atom


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
    # "regular season 2-1", "playoffs 4-2": the phase label precedes the record.
    for m in re.finditer(r"\b(regular season|regular-season|playoffs)\s+(\d{1,3})\s*-\s*(\d{1,3})\b", s.text, re.I):
        scope = scope_for(s, m.start())
        scope.season_type = "playoffs" if m.group(1).lower().startswith("playoff") else "regular"
        record(m.start(2), m.end(3), int(m.group(2)), int(m.group(3)), scope, "phase")
    # "Knicks home, regular season: 30-10 in 40 games" and "went 7-3 in their first 10 games".
    for m in re.finditer(r"\b(\d{1,3})\s*-\s*(\d{1,3})\s+in\s+(\d{1,3})\s+games?\b", s.text, re.I):
        scope = scope_for(s, m.start())
        record(m.start(1), m.end(2), int(m.group(1)), int(m.group(2)), scope, "team")
        atom = scalar_atom(s, m, 3)
        if atom is not None and s.free(atom) and atom.kind == "number":
            stats = s.oracle.team_scope(**scope.filters())
            s.mark(atom, int(m.group(3)), stats["games"], f"game count {scope.filters()}", stats["sql"])
    # "over 40 games (30-10)".
    for m in re.finditer(r"\b(\d{1,3})\s+games?\s*\((\d{1,3})\s*-\s*(\d{1,3})\)", s.text, re.I):
        scope = scope_for(s, m.start())
        record(m.start(2), m.end(3), int(m.group(2)), int(m.group(3)), scope, "split")
    # "first 10 games were 7-3".
    for m in re.finditer(
        r"\b(first|last)\s+(\d{1,3})\s+games?\s+(?:were|went)\s+(\d{1,3})\s*-\s*(\d{1,3})",
        s.text, re.I,
    ):
        scope = scope_for(s, m.start())
        if m.group(1).lower() == "first":
            scope.first_n, scope.last_n = int(m.group(2)), None
        else:
            scope.last_n, scope.first_n = int(m.group(2)), None
        record(m.start(3), m.end(4), int(m.group(3)), int(m.group(4)), scope, "window")
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
    # "lost 29 of their 82 archived games (53 wins)".
    for m in re.finditer(
        r"\blost\s+(\d{1,3})\s+of\s+(?:their\s+)?(\d{1,3})\s+(?:archived\s+)?games?", s.text, re.I,
    ):
        scope = scope_for(s, m.start())
        stats = s.oracle.team_scope(**scope.filters())
        for group, expected, fact in ((1, stats["losses"], "losses"), (2, stats["games"], "games")):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom) and atom.kind == "number":
                s.mark(atom, int(m.group(group)), expected, f"{fact} {scope.filters()}", stats["sql"])
    # "10 home losses", "19 road losses".
    for m in re.finditer(r"\b(\d{1,3})\s+(home|road|away)\s+(wins|losses)\b", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        scope = scope_for(s, m.start())
        scope.loc = "home" if m.group(2).lower() == "home" else "away"
        stats = s.oracle.team_scope(**scope.filters())
        expected = stats["wins"] if m.group(3).lower().startswith("win") else stats["losses"]
        s.mark(atom, int(m.group(1)), expected, f"{m.group(3).lower()} {scope.filters()}", stats["sql"])
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
        r"\b(\d{1,3})\s+archived\s+(?:\d{4}-\d{2}\s+)?(?:regular-season\s+|regular season\s+)?(?:[A-Z][a-z]+\s+)?games\b",
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
