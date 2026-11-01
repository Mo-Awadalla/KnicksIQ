"""Scope and window invariants for one fact, held over a claim or a projected row.

A canonical fact's scope is an explicit vocabulary: anything outside it is unexpressible
and fails closed. A typed claim states its own filters and window, so the invariants read
the claim's attribution. A projected scoreline has no typed claim, so the game row it is
projected from states the same attribution — the opponent, the venue, the result and the
date window — and a field the row cannot prove stays absent, which fails the scope.

The module is a leaf of the assertion checks: it reports through their shared result
vocabulary and never imports the checks that call it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from app.evaluation.arithmetic_core import HOME_TEAM, number
from app.evaluation.assertion_results import AssertionFailure
from app.evaluation.assertion_vocabulary import ALL_STAR_BREAK, ScopeExpectation
from app.evaluation.labels import CanonicalFact


class ScopeSubject(Protocol):
    """The attribution a scope is checked against, from a claim or a projected row.

    Read-only, because both subjects are frozen: a claim and a projected game expose
    these fields as their own settled attribution, so the invariants only read them.
    """

    @property
    def filters(self) -> dict[str, Any]: ...

    @property
    def window(self) -> dict[str, Any] | None: ...

    @property
    def sample_size(self) -> int | None: ...

    @property
    def season_type(self) -> str | None: ...


def _window_failures(scope: ScopeExpectation, claim: ScopeSubject) -> list[AssertionFailure]:
    """A stated window is proved by the record's own considered dates.

    A producer records the first and last considered date and, when its population
    mixes season types, no single season type. That is the population's own evidence
    of the window it used, so a month, a boundary date or the all-star break is
    checked against containment and coverage rather than against an exact endpoint: a
    month whose considered games begin on the second is still that month.
    """
    window = claim.window or {}
    start = _day(window.get("date_start"))
    end = _day(window.get("date_end"))
    failures: list[AssertionFailure] = []
    stated_month = window.get("month") == scope.month and (
        scope.year is None or window.get("year") == scope.year
    )
    if scope.month and not (stated_month or _inside_month(start, end, scope.month, scope.year)):
        failures.append(AssertionFailure("window_mismatch", scope.raw))
    if scope.after and not _reaches(window.get("after"), start, scope.after):
        failures.append(AssertionFailure("window_mismatch", scope.raw))
    if scope.include_postseason and not (
        window.get("include_postseason") or claim.season_type is None
    ):
        failures.append(AssertionFailure("window_mismatch", "postseason inclusion"))
    if scope.before_all_star or scope.after_all_star:
        direction = "before" if scope.before_all_star else "after"
        proved = window.get("all_star_break") == direction or (
            end is not None and end < ALL_STAR_BREAK
            if scope.before_all_star
            else start is not None and start >= ALL_STAR_BREAK
        )
        if not proved:
            failures.append(AssertionFailure("window_mismatch", f"{direction} all-star break"))
    return failures


def _day(value: Any) -> date | None:
    """One recorded date, or None when it is absent or not a date."""
    if isinstance(value, date) and not isinstance(value, str):
        return value
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _inside_month(start: date | None, end: date | None, month: int, year: int | None) -> bool:
    """Every considered date falls inside the same month, and in the stated year."""
    if start is None or end is None or start > end:
        return False
    if start.month != month or end.month != month or start.year != end.year:
        return False
    return year is None or start.year == year


def _reaches(stated: Any, start: date | None, boundary: date) -> bool:
    """The window starts at or after the boundary, whether it states it or only dates it."""
    recorded = _day(stated)
    return (recorded is not None and recorded >= boundary) or (
        start is not None and start >= boundary
    )


def scope_failures(scope: ScopeExpectation, claim: ScopeSubject) -> list[AssertionFailure]:
    if not scope.parseable:
        return [AssertionFailure("scope_not_expressible", scope.raw)]
    failures: list[AssertionFailure] = []
    if scope.opponent:
        if str(claim.filters.get("opponent_id") or "").upper() != scope.opponent:
            failures.append(AssertionFailure("scope_mismatch", f"opponent {scope.opponent}"))
    if scope.conference:
        filters = claim.filters or {}
        if str(filters.get("conference") or "").casefold() != scope.conference.casefold():
            failures.append(AssertionFailure("scope_mismatch", f"conference {scope.conference}"))
    failures.extend(_window_failures(scope, claim))
    if scope.period is not None:
        periods = claim.filters.get("periods") or []
        if scope.period not in {int(item) for item in periods if str(item).isdigit()}:
            failures.append(AssertionFailure("window_mismatch", f"quarter {scope.period}"))
    if scope.venue:
        if str(claim.filters.get("home_away") or "").casefold() != scope.venue:
            failures.append(AssertionFailure("scope_mismatch", f"venue {scope.venue}"))
    if scope.result:
        if str(claim.filters.get("game_result") or "").casefold() not in {
            scope.result,
            f"{scope.result}s",
        }:
            failures.append(AssertionFailure("scope_mismatch", f"result {scope.result}"))
    # A stated first/last window must be recorded in the same direction and length: a
    # matching sample size alone cannot prove which games a window used.
    for name in ("first_n", "last_n"):
        expected = getattr(scope, name)
        if expected is None:
            continue
        window = claim.window or {}
        if window.get(name) != expected:
            failures.append(AssertionFailure("window_mismatch", f"{name} {expected}"))
        if claim.sample_size != expected:
            failures.append(AssertionFailure("denominator_mismatch", f"sample size {expected}"))
    if scope.appearances and scope.first_n is None and scope.last_n is None:
        if claim.sample_size is None:
            failures.append(AssertionFailure("denominator_mismatch", "appearance count"))
    return failures


@dataclass(frozen=True)
class ProjectedGame:
    """One verified game row read as the subject a scoreline scope is checked against.

    The row is the only attribution a scoreline can prove, so every field the scope
    vocabulary reads is projected from its own columns. A column the row does not carry
    stays absent, which fails the scope closed instead of assuming it holds.
    """

    filters: dict[str, Any]
    window: dict[str, Any] | None
    sample_size: int | None = 1
    season_type: str | None = None

    @classmethod
    def of(cls, row: dict[str, Any], team: str) -> ProjectedGame:
        home, away = row.get("home_team_id"), row.get("away_team_id")
        filters: dict[str, Any] = {
            "opponent_id": None,
            "home_away": None,
            "game_result": None,
            "periods": [],
        }
        if home == team:
            filters["home_away"], filters["opponent_id"] = "home", away
            own, other = row.get("home_score"), row.get("away_score")
        elif away == team:
            filters["home_away"], filters["opponent_id"] = "away", home
            own, other = row.get("away_score"), row.get("home_score")
        else:
            own = other = None
        if number(own) and number(other):
            filters["game_result"] = "win" if own > other else "loss" if own < other else None
        season_type = row.get("season_type")
        return cls(
            filters,
            date_window(row.get("game_date")),
            season_type=season_type if isinstance(season_type, str) else None,
        )


def own_team(fact: CanonicalFact) -> str:
    subject = (fact.subject or "").strip()
    if subject.startswith("team:") and subject.split(":", 1)[1]:
        return subject.split(":", 1)[1].upper()
    return HOME_TEAM


def date_window(value: Any) -> dict[str, Any] | None:
    """The window a game's own date can prove, or None when the date is unreadable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        day = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return {
        "date": day.isoformat(),
        "month": day.month,
        "year": day.year,
        "after": day.isoformat(),
        "all_star_break": "before" if day < ALL_STAR_BREAK else "after",
    }
