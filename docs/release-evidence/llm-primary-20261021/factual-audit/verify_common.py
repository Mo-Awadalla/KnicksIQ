"""Helpers shared by the verifier families."""

from __future__ import annotations

import re
from typing import Any

from model import Atom, Session, number, tolerance
from scope import Scope, parse_scope, sentences


def pair_atom(s: Session, m: re.Match, g1: int, g2: int) -> Atom | None:
    atom = s.atom_at(m.start(g1), m.end(g2))
    return atom if atom is not None and atom.kind == "pair" else None


def scalar_atom(s: Session, m: re.Match, group: int) -> Atom | None:
    return s.atom_at(m.start(group), m.end(group))


def mark_pair(
    s: Session,
    atom: Atom,
    first: float,
    second: float,
    expected_first: float,
    expected_second: float,
    fact: str,
    sql: str,
    tol: float | None = None,
) -> None:
    tol = tolerance(atom.raw) if tol is None else tol
    ok = abs(first - expected_first) <= tol and abs(second - expected_second) <= tol
    detail = ""
    if not ok:
        detail = f"expected {expected_first}-{expected_second}"
    s.mark(
        atom,
        atom.raw,
        f"{expected_first}-{expected_second}",
        fact,
        sql,
        tol=tol,
        status="verified" if ok else "wrong",
        detail=detail,
    )


def mark_scalar(
    s: Session,
    atom: Atom | None,
    expected: Any,
    fact: str,
    sql: str,
    tol: float | None = None,
) -> None:
    if atom is None:
        return
    claimed = number(atom.raw) if atom.kind in {"number", "percent"} else atom.first()
    s.mark(atom, claimed, expected, fact, sql, tol=tol)


def scope_for(s: Session, pos: int) -> Scope:
    current = s.defaults["scope"]
    for start, end, sentence in sentences(s.text):
        if pos < start:
            break
        if start <= pos < end:
            return parse_scope(s.text[start:pos], current, s.oracle.team_aliases, pos=0)
        current = parse_scope(sentence, current, s.oracle.team_aliases, pos=0, final=True)
    return current


def sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    starts = [0] + [m.end() for m in re.finditer(r"[.!?\n]", text)]
    begin = max(x for x in starts if x <= pos)
    ends = [m.start() for m in re.finditer(r"[.!?\n]", text) if m.start() >= pos]
    end = ends[0] if ends else len(text)
    return begin, end


def fmt(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}"


def candidates(s: Session, pos: int) -> tuple[list, Scope]:
    scope = scope_for(s, pos)
    if scope.start and scope.end and scope.start == scope.end:
        games = s.oracle.by_date.get(scope.start, [])
        if scope.opp:
            games = [g for g in games if g.opp == scope.opp]
        return games, scope
    games = s.oracle.games_for(**scope.filters())
    return games, scope


def periods_of(scope: Scope) -> list[int] | None:
    return scope.period if scope.period else None
