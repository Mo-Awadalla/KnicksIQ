"""Numeric atom extraction and per-response verification ledger."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTH_RE = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?"
)
ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DATE_RANGE_YEARS = re.compile(
    rf"\b({MONTH_RE})\s+(\d{{1,2}})\s*[–-]\s*(\d{{1,2}}),?\s+(\d{{4}})\b"
)
DATE_RANGE_FULL = re.compile(
    rf"\b({MONTH_RE})\s+(\d{{1,2}}),?\s+(\d{{4}})\s*[–-]\s*({MONTH_RE})"
    rf"\s+(\d{{1,2}}),?\s+(\d{{4}})\b"
)
MONTH_DATE = re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}}),?\s+(\d{{4}})\b")
DATE_RANGE_NO_YEAR = re.compile(
    rf"\b({MONTH_RE})\s+(\d{{1,2}})\s*[–-]\s*(\d{{1,2}})\b"
)
MONTH_DAY = re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}})\b")
SEASON = re.compile(r"\b(20\d{2})-(20\d{2}|\d{2})\b")
CLOCK = re.compile(r"\bQ([1-4])\s+(\d{1,2}:\d{2})\b")
BARE_CLOCK = re.compile(r"\b(\d{1,2}:\d{2})\b")
GAME_NO = re.compile(r"\bgame\s+(\d+)\b(?!\s*[-–])", re.I)
PERIOD_TOKEN = re.compile(r"\bQ([1-4])\b|\b([1-4])Q\b")
PAIR = re.compile(r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*[–-]\s*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)")
PERCENT = re.compile(r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*%")
NUMBER = re.compile(r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)")


def number(value: str) -> float:
    return float(value.replace(",", ""))


def decimals(value: str) -> int:
    return len(value.split(".", 1)[1]) if "." in value else 0


def parse_month(name: str) -> int:
    return MONTHS[name.lower().rstrip(".")]


def month_bounds(year: int, month: int) -> tuple[str, str]:
    if month == 12:
        return f"{year:04d}-12-01", f"{year:04d}-12-31"
    nxt = month + 1
    last = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31,
            9: 30, 10: 31, 11: 30, 12: 31}[month]
    if year % 4 == 0 and month == 2:
        last = 29
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


@dataclass
class Atom:
    index: int
    start: int
    end: int
    raw: str
    kind: str
    values: tuple[Any, ...] = ()

    @property
    def is_int(self) -> bool:
        return self.kind == "number" and "." not in self.raw

    def first(self) -> float:
        if self.kind == "pair":
            return number(self.values[0])
        return number(self.raw.strip("+")) if self.kind == "number" else float(self.values[0])


@dataclass
class Result:
    indexes: tuple[int, ...]
    claimed: Any
    expected: Any
    status: str
    fact: str
    sql: str
    detail: str = ""


@dataclass
class Session:
    response: dict[str, Any]
    oracle: Any
    text: str
    atoms: list[Atom] = field(default_factory=list)
    results: dict[int, Result] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.atoms = tokenize(self.text)

    def free(self, atom: Atom) -> bool:
        return atom.index not in self.results

    def inside(self, start: int, end: int) -> list[Atom]:
        return [a for a in self.atoms if self.free(a) and a.start >= start and a.end <= end]

    def atom_at(self, start: int, end: int) -> Atom | None:
        for atom in self.atoms:
            if atom.start >= start and atom.end <= end:
                return atom
        return None

    def mark(
        self,
        atom: Atom,
        claimed: Any,
        expected: Any,
        fact: str,
        sql: str,
        tol: float | None = None,
        status: str | None = None,
        detail: str = "",
    ) -> None:
        if atom.index in self.results:
            return
        if status is None:
            status = compare(claimed, expected, tol if tol is not None else tolerance(atom.raw))
        self.results[atom.index] = Result(
            indexes=(atom.index,), claimed=claimed, expected=expected,
            status=status, fact=fact, sql=sql, detail=detail,
        )

    def mark_group(
        self,
        atoms: list[Atom],
        claimed: list[Any],
        expected: list[Any],
        fact: str,
        sql: str,
        tol: float | None = None,
    ) -> None:
        for atom, claim, exp in zip(atoms, claimed, expected):
            self.mark(atom, claim, exp, fact, sql, tol=tol)


def tolerance(raw: str) -> float:
    value = raw.lstrip("+")
    places = decimals(value)
    if places:
        return 0.5 * (10 ** -places) + 1e-9
    return 0.5 + 1e-9


def compare(claimed: Any, expected: Any, tol: float) -> str:
    if expected is None:
        return "unverified"
    try:
        if isinstance(expected, (list, tuple)):
            return "verified" if any(
                abs(Decimal(str(claimed)) - Decimal(str(item))) <= Decimal(str(tol))
                for item in expected
            ) else "wrong"
        a = Decimal(str(claimed))
        b = Decimal(str(expected))
    except Exception:
        return "verified" if str(claimed) == str(expected) else "wrong"
    return "verified" if abs(a - b) <= Decimal(str(tol)) + Decimal("1e-9") else "wrong"


def tokenize(text: str) -> list[Atom]:
    used = [False] * len(text)
    atoms: list[Atom] = []

    def free(start: int, end: int) -> bool:
        return not any(used[start:end])

    def add(start: int, end: int, kind: str, values: tuple[Any, ...] = ()) -> None:
        for i in range(start, end):
            used[i] = True
        atoms.append(Atom(len(atoms), start, end, text[start:end], kind, values))

    # Dates and date ranges first; they otherwise split into pairs and numbers.
    for m in ISO_DATE.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "date", (int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in DATE_RANGE_FULL.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "date_range", (
                int(m.group(3)), parse_month(m.group(1)), int(m.group(2)),
                int(m.group(6)), parse_month(m.group(4)), int(m.group(5)),
            ))
    for m in DATE_RANGE_YEARS.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "date_range", (
                int(m.group(4)), parse_month(m.group(1)), int(m.group(2)),
                int(m.group(4)), parse_month(m.group(1)), int(m.group(3)),
            ))
    for m in DATE_RANGE_NO_YEAR.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "date_range", (
                0, parse_month(m.group(1)), int(m.group(2)),
                0, parse_month(m.group(1)), int(m.group(3)),
            ))
    for m in MONTH_DATE.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "date", (
                int(m.group(3)), parse_month(m.group(1)), int(m.group(2)),
            ))
    for m in MONTH_DAY.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "date_no_year", (parse_month(m.group(1)), int(m.group(2))))
    for m in SEASON.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "season", (m.group(1) + "-" + m.group(2),))
    for m in CLOCK.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "clock", (int(m.group(1)), m.group(2)))
    for m in GAME_NO.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "game_no", (int(m.group(1)),))
    for m in PERIOD_TOKEN.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "period", (int(m.group(1) or m.group(2)),))
    for m in BARE_CLOCK.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "clock", (None, m.group(1)))
    for m in PAIR.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "pair", (m.group(1), m.group(2)))
    for m in PERCENT.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "percent", (m.group(1),))
    for m in NUMBER.finditer(text):
        if free(m.start(), m.end()):
            add(m.start(), m.end(), "number", (m.group(1),))
    atoms.sort(key=lambda a: a.start)
    for i, atom in enumerate(atoms):
        atom.index = i
    return atoms


def split_pair(atom: Atom) -> tuple[str, str]:
    assert atom.kind == "pair"
    return str(atom.values[0]), str(atom.values[1])
