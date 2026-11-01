"""Explicit event instants shared by lexical and vector retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_EXPLICIT_CLOCK = re.compile(r"\b(?:at|with)\s+(\d{1,2}):(\d{2})(?!\d|\.\d)", re.IGNORECASE)
_PERIOD_CONTEXT = re.compile(r"\b(?:quarter|q[1-9]|overtime)\b", re.IGNORECASE)
_REMAINING = re.compile(r"\s+(?:left|remaining)\b", re.IGNORECASE)


@dataclass(frozen=True)
class GameMoment:
    period: int
    seconds_remaining: int

    def __post_init__(self) -> None:
        if type(self.period) is not int or self.period < 1:
            raise ValueError("An event instant requires a positive period")
        maximum = 720 if self.period <= 4 else 300
        if type(self.seconds_remaining) is not int or not 0 <= self.seconds_remaining <= maximum:
            raise ValueError("The clock is outside its regulation or overtime period")

    @property
    def clock_variants(self) -> tuple[str, ...]:
        minutes, seconds = divmod(self.seconds_remaining, 60)
        return tuple(dict.fromkeys((f"{minutes}:{seconds:02d}", f"{minutes:02d}:{seconds:02d}")))

    def matches(self, row: dict[str, Any]) -> bool:
        return row.get("period") == self.period and row.get("clock") in self.clock_variants

    def as_filter(self) -> dict[str, int]:
        return {"period": self.period, "seconds_remaining": self.seconds_remaining}

    @classmethod
    def from_filter(cls, value: Any) -> GameMoment | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"period", "seconds_remaining"}:
            raise ValueError("An event instant has unexpected or missing fields")
        return cls(period=value["period"], seconds_remaining=value["seconds_remaining"])


def moment_from_question(question: str, periods: list[int]) -> GameMoment | None:
    scoped_periods = set(periods)
    matches = list(_EXPLICIT_CLOCK.finditer(question))
    if len(scoped_periods) != 1 or not matches:
        return None
    instants = set()
    period_context = _PERIOD_CONTEXT.search(question) is not None
    for match in matches:
        if not period_context and not _REMAINING.match(question[match.end() :]):
            return None
        minutes, seconds = int(match[1]), int(match[2])
        if seconds >= 60:
            return None
        instants.add(minutes * 60 + seconds)
    if len(instants) != 1:
        return None
    try:
        return GameMoment(period=next(iter(scoped_periods)), seconds_remaining=instants.pop())
    except ValueError:
        return None
