"""Sentence-level subject, phase, window and opponent parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from model import (
    DATE_RANGE_FULL, DATE_RANGE_NO_YEAR, DATE_RANGE_YEARS, ISO_DATE, MONTH_DATE,
    MONTH_DAY, MONTHS, parse_month,
)


@dataclass
class Scope:
    season_type: str | None = None
    opp: str | None = None
    loc: str | None = None
    start: str | None = None
    end: str | None = None
    last_n: int | None = None
    first_n: int | None = None
    result: str | None = None
    period: list[int] | None = None
    player: str | None = None

    def filters(self) -> dict[str, Any]:
        return {
            "season_type": self.season_type,
            "opp": self.opp,
            "loc": self.loc,
            "start": self.start,
            "end": self.end,
            "last_n": self.last_n,
            "first_n": self.first_n,
            "result": self.result,
        }


SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def sentences(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in SENTENCE.finditer(text):
        if m.group(0).strip():
            out.append((m.start(), m.end(), m.group(0)))
    return out


def team_mentions(text: str, aliases: dict[str, str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for alias, abbr in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
        if abbr == "NYK":
            continue
        flags = 0 if (len(alias) <= 3 and alias.isupper()) else re.I
        pattern = re.compile(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", flags)
        for m in pattern.finditer(text):
            found.append((m.start(), abbr))
    found.sort()
    return found


def nearest_team(text: str, pos: int, aliases: dict[str, str], window: int = 120) -> str | None:
    candidates = [
        (abs(start - pos), start, abbr)
        for start, abbr in team_mentions(text, aliases)
        if abs(start - pos) <= window
    ]
    return min(candidates)[2] if candidates else None


def parse_scope(text: str, base: Scope, aliases: dict[str, str], pos: int = 0, final: bool = False) -> Scope:
    scope = replace(base)
    lower = text.lower()
    regular_at = lower.rfind("regular")
    playoff_at = lower.rfind("playoff")
    if regular_at >= 0 and playoff_at >= 0:
        scope.season_type = None if final else ("playoffs" if playoff_at > regular_at else "regular")
    elif playoff_at >= 0:
        scope.season_type = "playoffs"
    elif regular_at >= 0:
        scope.season_type = "regular"
    if "preseason" in lower:
        scope.season_type = "preseason"

    opp = nearest_team(text, pos, aliases, window=160)
    if opp:
        scope.opp = opp
    home_markers = [m.start() for m in re.finditer(r"\b(?:at home|home games?|home record|home win|home loss|home margin|home offense|home split)\b", lower)]
    away_markers = [m.start() for m in re.finditer(r"\b(?:on the road|road games?|road win|road loss|away games?|away win|road margin|road offense|road split|away offense)\b", lower)]
    if home_markers or away_markers:
        last_home = max(home_markers, default=-1)
        last_away = max(away_markers, default=-1)
        scope.loc = "home" if last_home >= last_away else "away"

    m = re.search(r"\blast\s+(\d+)\b", lower)
    if m:
        scope.last_n = int(m.group(1))
        scope.first_n = None
    m = re.search(r"\bfirst\s+(\d+)\b", lower)
    if m:
        scope.first_n = int(m.group(1))
        scope.last_n = None
    if re.search(r"\bin wins\b|\bonly knicks wins\b", lower):
        scope.result = "W"
    elif re.search(r"\bin losses\b", lower):
        scope.result = "L"
    elif re.search(r"\b(?:went|record|going)\s+\d+\s*-\s*\d+", lower):
        scope.result = None

    iso_all = list(ISO_DATE.finditer(text))
    if iso_all:
        iso = iso_all[-1]
        scope.start = f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
        scope.end = scope.start
    has_range = bool(
        DATE_RANGE_FULL.search(text) or DATE_RANGE_YEARS.search(text) or DATE_RANGE_NO_YEAR.search(text)
    )
    for m in DATE_RANGE_FULL.finditer(text):
        y1, mo1, d1, y2, mo2, d2 = (
            int(m.group(3)), parse_month(m.group(1)), int(m.group(2)),
            int(m.group(6)), parse_month(m.group(4)), int(m.group(5)),
        )
        scope.start, scope.end = f"{y1:04d}-{mo1:02d}-{d1:02d}", f"{y2:04d}-{mo2:02d}-{d2:02d}"
    for m in DATE_RANGE_YEARS.finditer(text):
        year, mo1, d1, d2 = int(m.group(4)), parse_month(m.group(1)), int(m.group(2)), int(m.group(3))
        scope.start, scope.end = f"{year:04d}-{mo1:02d}-{d1:02d}", f"{year:04d}-{mo1:02d}-{d2:02d}"
    for m in DATE_RANGE_NO_YEAR.finditer(text):
        mo1, d1, d2 = parse_month(m.group(1)), int(m.group(2)), int(m.group(3))
        year = 2025 if mo1 >= 8 else 2026
        scope.start, scope.end = f"{year:04d}-{mo1:02d}-{d1:02d}", f"{year:04d}-{mo1:02d}-{d2:02d}"
    if re.search(r"\bthe two games\b|\bthe (?:five|four|three|\d+) [^.]{0,40}games\b|\bfinal scores\b", lower):
        scope.start = scope.end = None
    if re.search(r"\bacross (?:those|the) (?:\w+|\d+) (?:archived )?(?:games|meetings)\b", lower):
        scope.start = scope.end = None
    if re.search(r"\bover (?:those|the) (?:\w+|\d+) games\b", lower):
        scope.start = scope.end = None
    if re.search(r"\boverall\b", lower):
        if re.search(r"\boverall record\b|\boverall scoring\b", lower):
            scope.opp = None
        scope.start = scope.end = None
        scope.result = None
        scope.loc = None
    if re.search(r"\bfull\b[^.]{0,40}\bregular season\b|\bteam totals\b|\bin those \d+ wins\b", lower):
        if not re.search(r"\bagainst\b|\bvs\.?\b|\bversus\b", lower):
            scope.opp = None
        scope.start = scope.end = None
        scope.result = "W" if "in those" in lower else None
        scope.loc = None
    if re.search(r"\bthe (?:four|three|five|\d+) archived\b[^.]{0,30}\bmeetings\b", lower):
        scope.start = scope.end = None
    for m in MONTH_DATE.finditer(text):
        if has_range:
            continue
        year, month, day = int(m.group(3)), parse_month(m.group(1)), int(m.group(2))
        scope.start = f"{year:04d}-{month:02d}-{day:02d}"
        scope.end = scope.start
    for m in MONTH_DAY.finditer(text):
        if has_range:
            break
        if re.search(r"\d{1,2}:\d{2}", m.group(0)):
            continue
        month = parse_month(m.group(1))
        day = int(m.group(2))
        year = int(scope.start[:4]) if scope.start else 2025
        if month >= 8:
            year = 2025
        else:
            year = 2026
        scope.start = f"{year:04d}-{month:02d}-{day:02d}"
        scope.end = scope.start
    m = re.search(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})\s+(?:through|to|and)\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})", lower)
    if m:
        mo1, d1, mo2, d2 = parse_month(m.group(1)), int(m.group(2)), parse_month(m.group(3)), int(m.group(4))
        y1 = 2025 if mo1 >= 8 else 2026
        y2 = 2025 if mo2 >= 8 else 2026
        scope.start, scope.end = f"{y1:04d}-{mo1:02d}-{d1:02d}", f"{y2:04d}-{mo2:02d}-{d2:02d}"
    m = re.search(r"\bbetween\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})\s+and\s+(?:(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+)?(\d{1,2})", lower)
    if m:
        mo1, d1 = parse_month(m.group(1)), int(m.group(2))
        mo2 = parse_month(m.group(3)) if m.group(3) else mo1
        d2 = int(m.group(4))
        y1 = 2025 if mo1 >= 8 else 2026
        y2 = 2025 if mo2 >= 8 else 2026
        scope.start, scope.end = f"{y1:04d}-{mo1:02d}-{d1:02d}", f"{y2:04d}-{mo2:02d}-{d2:02d}"
    if re.search(r"\bin december\b", lower):
        scope.start, scope.end = "2025-12-01", "2025-12-31"
    elif re.search(r"\bin january\b|\bjanuary window\b", lower):
        scope.start, scope.end = "2026-01-01", "2026-01-31"
    elif re.search(r"\bjan(?:uary)?\s+\d{1,2}\s*(?:through|to|[–-])\s*(?:jan(?:uary)?\s+)?\d{1,2}", lower):
        scope.start, scope.end = "2026-01-01", "2026-01-31"
    if re.search(r"\bthird quarter\b", lower):
        scope.period = [3]
    elif re.search(r"\bfourth quarter\b", lower):
        scope.period = [4]
    return scope


def rolling_scopes(text: str, base: Scope, aliases: dict[str, str]) -> list[tuple[int, int, Scope]]:
    rows = []
    current = replace(base)
    for start, end, sentence in sentences(text):
        current = parse_scope(sentence, current, aliases, pos=0, final=True)
        rows.append((start, end, replace(current)))
    return rows


def scope_at(rows: list[tuple[int, int, Scope]], pos: int, base: Scope) -> Scope:
    for start, end, scope in rows:
        if start <= pos < end:
            return scope
    return base


def base_scope(question: str, answer: str, aliases: dict[str, str]) -> Scope:
    scope = Scope()
    return parse_scope(question, scope, aliases, pos=0, final=True)


def month_name(month: int) -> str:
    for name, value in MONTHS.items():
        if value == month and len(name) > 3:
            return name.title()
    return str(month)
