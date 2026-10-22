"""Helpers shared by the verifier families."""

from __future__ import annotations

import re
from typing import Any

from model import (
    Atom, DATE_RANGE_FULL, DATE_RANGE_NO_YEAR, DATE_RANGE_YEARS, ISO_DATE,
    MONTH_DATE, Session, number, parse_month, tolerance,
)
from scope import Scope, parse_scope, sentences, team_mentions


PHASE_TOKEN = re.compile(r"\bregular\b|\bplayoffs?\b|\bpostseason\b", re.I)
MONTH_NAMES = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)


def phase_of(text: str) -> str | None:
    """One phase, both phases, or none named."""
    regular = re.search(r"\bregular\b", text, re.I)
    playoffs = re.search(r"\bplayoffs?\b|\bpostseason\b", text, re.I)
    if regular and playoffs:
        return "all"
    if playoffs:
        return "playoffs"
    if regular:
        return "regular"
    return None


def dates_of(text: str) -> list[tuple[str, str]]:
    """Absolute date windows named in text, as (start, end) ISO pairs."""
    out: list[tuple[str, str]] = []
    for m in DATE_RANGE_FULL.finditer(text):
        y1, mo1, d1, y2, mo2, d2 = (
            int(m.group(3)), parse_month(m.group(1)), int(m.group(2)),
            int(m.group(6)), parse_month(m.group(4)), int(m.group(5)),
        )
        out.append((f"{y1:04d}-{mo1:02d}-{d1:02d}", f"{y2:04d}-{mo2:02d}-{d2:02d}"))
    for m in DATE_RANGE_YEARS.finditer(text):
        year, mo1, d1, d2 = int(m.group(4)), parse_month(m.group(1)), int(m.group(2)), int(m.group(3))
        out.append((f"{year:04d}-{mo1:02d}-{d1:02d}", f"{year:04d}-{mo1:02d}-{d2:02d}"))
    for m in re.finditer(
        r"\b(" + MONTH_NAMES + r")\s+(\d{1,2})\s+(?:through|to|and)\s+"
        r"(?:(?P<m2>" + MONTH_NAMES + r")\s+)?(\d{1,2})(?:,?\s+(\d{4}))?",
        text, re.I,
    ):
        mo1, d1 = parse_month(m.group(1)), int(m.group(2))
        mo2 = parse_month(m.group("m2")) if m.group("m2") else mo1
        d2 = int(m.group(4))
        year = int(m.group(5)) if m.group(5) else (2025 if mo1 >= 8 else 2026)
        year2 = year if mo2 >= mo1 else year + 1
        out.append((f"{year:04d}-{mo1:02d}-{d1:02d}", f"{year2:04d}-{mo2:02d}-{d2:02d}"))
    for m in re.finditer(
        r"\bbetween\s+(" + MONTH_NAMES + r")\s+(\d{1,2})\s+and\s+"
        r"(?:(?P<m2>" + MONTH_NAMES + r")\s+)?(\d{1,2})(?:,?\s+(\d{4}))?",
        text, re.I,
    ):
        mo1, d1 = parse_month(m.group(1)), int(m.group(2))
        mo2 = parse_month(m.group("m2")) if m.group("m2") else mo1
        d2 = int(m.group(4))
        year = int(m.group(5)) if m.group(5) else (2025 if mo1 >= 8 else 2026)
        year2 = year if mo2 >= mo1 else year + 1
        out.append((f"{year:04d}-{mo1:02d}-{d1:02d}", f"{year2:04d}-{mo2:02d}-{d2:02d}"))
    for m in ISO_DATE.finditer(text):
        d = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        out.append((d, d))
    for m in MONTH_DATE.finditer(text):
        year, month, day = int(m.group(3)), parse_month(m.group(1)), int(m.group(2))
        d = f"{year:04d}-{month:02d}-{day:02d}"
        out.append((d, d))
    for m in DATE_RANGE_NO_YEAR.finditer(text):
        mo1, d1, d2 = parse_month(m.group(1)), int(m.group(2)), int(m.group(3))
        year = 2025 if mo1 >= 8 else 2026
        out.append((f"{year:04d}-{mo1:02d}-{d1:02d}", f"{year:04d}-{mo1:02d}-{d2:02d}"))
    return out


def unique_windows(text: str) -> set[tuple[str, str]]:
    """Distinct date windows, dropping single dates that lie inside a range."""
    found = dates_of(text)
    ranges = [w for w in found if w[0] != w[1]]
    singles = [
        w for w in found
        if w[0] == w[1] and not any(r[0] <= w[0] and w[1] <= r[1] for r in ranges)
    ]
    return set(ranges) | set(singles)


def _resolve(s: Session, scope: Scope) -> Scope:
    if scope.asb and not scope.start:
        scope.start = s.oracle.asb_start
    return scope


def _clause_scope(s: Session, inherited: Scope, sentence: str, offset: int) -> Scope:
    aliases = s.oracle.team_aliases
    prefix = sentence[:offset]
    # Nearest team to the atom wins: 103.25 is in the Boston clause even
    # though Toronto is named earlier in the same sentence.
    scope = parse_scope(prefix, inherited, aliases, pos=len(prefix))
    if not PHASE_TOKEN.search(prefix):
        phase = phase_of(sentence)
        if phase == "regular":
            scope.season_type = "regular"
        elif phase == "playoffs":
            scope.season_type = "playoffs"
        elif phase == "all":
            scope.season_type = None
    if not dates_of(prefix):
        found = unique_windows(sentence[offset:])
        if len(found) == 1:
            scope.start, scope.end = found.pop()
    if not team_mentions(prefix, aliases):
        # "Opponent: Atlanta." or a single opponent named after the number.
        named = {abbr for _, abbr in team_mentions(sentence[offset:], aliases) if abbr != "NYK"}
        if len(named) == 1:
            scope.opp = named.pop()
    return _resolve(s, scope)



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
            return _clause_scope(s, current, sentence, pos - start)
        current = parse_scope(sentence, current, s.oracle.team_aliases, pos=0, final=True)
    return _resolve(s, current)


def claim_number(s: Session, m: re.Match, group: int) -> float:
    """The claimed value, preferring the extracted atom (sign words included)."""
    atom = scalar_atom(s, m, group)
    if atom is not None and atom.kind in {"number", "percent"}:
        try:
            return number(atom.raw)
        except ValueError:
            pass
    return number(m.group(group))


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
